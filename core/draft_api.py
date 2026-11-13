"""Private, revisioned drafts. Partial trades never enter analytics/history."""
import hashlib
import json
import re

from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .note_documents import validate_notes_document
from .models import Journal, Trade, TradeDraft, TradeDraftImage


def journal_scope(request, journal_id, scope):
    journal = get_object_or_404(Journal, pk=journal_id, user=request.user)
    if scope != "new":
        if not re.fullmatch(r"[1-9][0-9]{0,18}", scope):
            raise serializers.ValidationError("Invalid draft scope.")
        get_object_or_404(Trade, journal=journal, pk=int(scope))
    return journal


def representation(draft):
    return {"revision": draft.revision, "data": draft.data or None, "updated_at": draft.updated_at.isoformat()}


def validate_snapshot(data, journal, scope):
    if not isinstance(data, dict) or len(json.dumps(data)) > 1000000:
        raise serializers.ValidationError("Draft must be an object of at most 1 MB.")
    if not isinstance(data.get("values"), dict) or not isinstance(data.get("sections"), list) or len(data["sections"]) > 50:
        raise serializers.ValidationError("Invalid draft fields or sections.")
    saved_id = data.get("savedTradeId")
    if saved_id is not None:
        if type(saved_id) is not int or (scope != "new" and saved_id != int(scope)):
            raise serializers.ValidationError("Invalid draft trade.")
        get_object_or_404(Trade, journal=journal, pk=saved_id)
    images = []
    note_sections = []
    for section in data["sections"]:
        if not isinstance(section, dict) or not isinstance(section.get("images"), list) or len(section["images"]) > 50:
            raise serializers.ValidationError("Invalid draft images.")
        if not isinstance(section.get("id"), str) or not isinstance(section.get("title"), str):
            raise serializers.ValidationError("Draft sections need an ID and title.")
        text = section.get("text", "")
        if not isinstance(text, str):
            raise serializers.ValidationError("Draft notes must be text.")
        fallback = {"type": "doc", "content": [{"type": "paragraph", **({"content": [{"type": "text", "text": text}]} if text else {})}]}
        note_section = {"id": section["id"], "title": section["title"], "content": section.get("content") or fallback, "image_notes": {}, "image_details": {}}
        note_sections.append(note_section)
        for image in section["images"]:
            if not isinstance(image, dict) or image.get("file") is not None:
                raise serializers.ValidationError("Upload attachments separately.")
            image_id = str(image.get("id", ""))
            if not 1 <= len(image_id) <= 100:
                raise serializers.ValidationError("Invalid draft image ID.")
            if image.get("afterContent") is not None:
                note_section["image_notes"][image_id] = image["afterContent"]
            if "annotations" in image or "caption" in image:
                note_section["image_details"][image_id] = {"annotations": image.get("annotations", []), "caption": image.get("caption", "")}
            attachment = image.get("cloudFile")
            if attachment:
                if not isinstance(attachment, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(attachment.get("digest", ""))):
                    raise serializers.ValidationError("Invalid draft attachment.")
                images.append(attachment["digest"])
    if len(images) > 50:
        raise serializers.ValidationError("Use up to 50 draft attachments.")
    validate_notes_document({"version": 1, "general": data.get("generalDocument"), "sections": note_sections})
    return set(images)


class TradeDraftView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, journal_id, scope):
        journal = journal_scope(request, journal_id, scope)
        draft = TradeDraft.objects.filter(journal=journal, scope=scope).first()
        return Response(representation(draft) if draft else {"revision": 0, "data": None, "updated_at": None})

    def mutate(self, request, journal_id, scope, clear=False):
        journal = journal_scope(request, journal_id, scope)
        revision = request.data.get("revision")
        if type(revision) is not int or revision < 0:
            raise serializers.ValidationError({"revision": "Provide the draft revision."})
        data = {} if clear else request.data.get("data")
        attachments = set() if clear else validate_snapshot(data, journal, scope)
        with transaction.atomic():
            draft, _ = TradeDraft.objects.get_or_create(journal=journal, scope=scope, defaults={"trade_id": None if scope == "new" else int(scope)})
            draft = TradeDraft.objects.select_for_update().get(pk=draft.pk)
            if revision != draft.revision:
                return Response({**representation(draft), "detail": "This draft changed on another device."}, status=status.HTTP_409_CONFLICT)
            if attachments - set(draft.images.values_list("digest", flat=True)):
                raise serializers.ValidationError("Upload draft images before saving the draft.")
            draft.data = data
            if not clear:
                draft.trade_id = int(scope) if scope != "new" else data.get("savedTradeId")
            draft.revision += 1
            draft.save(update_fields=["data", "trade", "revision", "updated_at"])
            # Retain a revision tombstone so stale devices cannot resurrect a discarded draft.
            if clear:
                draft.images.all().delete()
        return Response(representation(draft))

    def put(self, request, journal_id, scope):
        return self.mutate(request, journal_id, scope)

    def delete(self, request, journal_id, scope):
        return self.mutate(request, journal_id, scope, clear=True)


class TradeDraftImageView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]

    def get(self, request, journal_id, scope, digest):
        journal = journal_scope(request, journal_id, scope)
        image = get_object_or_404(TradeDraftImage, draft__journal=journal, draft__scope=scope, digest=digest)
        response = HttpResponse(bytes(image.content), content_type=image.content_type)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def put(self, request, journal_id, scope, digest):
        journal = journal_scope(request, journal_id, scope)
        upload = request.FILES.get("file")
        if not upload or upload.content_type not in {"image/png", "image/jpeg", "image/webp"} or upload.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Use a PNG, JPEG or WebP image up to 5 MB.")
        content = upload.read()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or hashlib.sha256(content).hexdigest() != digest:
            raise serializers.ValidationError("Image digest does not match.")
        with transaction.atomic():
            draft, _ = TradeDraft.objects.get_or_create(journal=journal, scope=scope, defaults={"trade_id": None if scope == "new" else int(scope)})
            draft = TradeDraft.objects.select_for_update().get(pk=draft.pk)
            image = draft.images.only("id").filter(digest=digest).first()
            if not image:
                total = draft.images.aggregate(total=Sum("size"))["total"] or 0
                if draft.images.count() >= 50 or total + len(content) > 30 * 1024 * 1024:
                    raise serializers.ValidationError("Draft attachments can use up to 30 MB across 50 images.")
                TradeDraftImage.objects.create(draft=draft, digest=digest, content=content, size=len(content), content_type=upload.content_type, name=upload.name[:200])
        return Response({"digest": digest})
