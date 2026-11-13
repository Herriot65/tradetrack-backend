import hashlib
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from core.models import TradeDraft, TradeDraftImage
from tests.factories import JournalFactory, TradeFactory

pytestmark = pytest.mark.django_db


def setup():
    journal = JournalFactory()
    client = APIClient()
    client.force_authenticate(journal.user)
    return journal, client, f"/api/journals/{journal.pk}/drafts/new/"


def snapshot():
    return {"values": {"asset": "", "risk_percent": "unfinished"}, "sections": [], "generalDocument": {"type": "doc", "content": []}}


def test_draft_partial_values_scope_revisions_and_tombstone():
    journal, client, url = setup()
    assert client.get(url).data["revision"] == 0
    response = client.put(url, {"revision": 0, "data": snapshot()}, format="json")
    assert response.status_code == 200
    assert response.data["revision"] == 1
    assert journal.trades.count() == 0
    second = APIClient()
    second.force_authenticate(journal.user)
    assert second.get(url).data["data"] == snapshot()
    conflict = second.put(url, {"revision": 0, "data": snapshot()}, format="json")
    assert conflict.status_code == 409
    assert client.delete(url, {"revision": 1}, format="json").status_code == 200
    assert second.put(url, {"revision": 1, "data": snapshot()}, format="json").status_code == 409
    assert second.get(url).data["data"] is None
    foreign = JournalFactory()
    assert client.get(f"/api/journals/{foreign.pk}/drafts/new/").status_code == 404
    assert APIClient().get(url).status_code == 401
    trade = TradeFactory(journal=foreign)
    assert client.get(url.replace("new/", f"{trade.pk}/")).status_code == 404
    trade = TradeFactory(journal=journal)
    own_url = url.replace("new/", f"{trade.pk}/")
    assert client.put(own_url, {"revision": 0, "data": snapshot()}, format="json").status_code == 200
    assert client.get(url).data["data"] is None
    scope=str(trade.pk)
    trade.delete()
    assert not TradeDraft.objects.filter(journal=journal,scope=scope).exists()


def test_private_attachments_reuse_limits_ownership_and_cleanup():
    journal, client, url = setup()
    content = b'\x89PNG\r\n\x1a\nprivate draft image'
    digest = hashlib.sha256(content).hexdigest()
    image_url = url + f"images/{digest}/"
    def upload():
        return client.put(image_url, {"file": SimpleUploadedFile("chart.png", content, "image/png")}, format="multipart")
    assert upload().status_code == 200
    assert upload().status_code == 200
    assert TradeDraftImage.objects.count() == 1
    image = client.get(image_url)
    assert image.content == content
    assert image["Cache-Control"] == "private, no-store"
    outsider = APIClient()
    outsider.force_authenticate(JournalFactory().user)
    assert outsider.get(image_url).status_code == 404
    data = snapshot()
    data["sections"] = [{"id": "before", "title": "Before", "images": [{"id": "a", "file": None, "cloudFile": {"digest": digest}}]}]
    assert client.put(url, {"revision": 0, "data": data}, format="json").status_code == 200
    data["sections"][0]["images"][0]["cloudFile"]["digest"] = "f" * 64
    assert client.put(url, {"revision": 1, "data": data}, format="json").status_code == 400
    assert client.delete(url, {"revision": 1}, format="json").status_code == 200
    assert not TradeDraftImage.objects.exists()
    assert client.get(image_url).status_code == 404
    assert client.put(url + "images/" + "0" * 64 + "/", {"file": SimpleUploadedFile("x.png", content, "image/png")}, format="multipart").status_code == 400
    assert client.put(image_url, {"file": SimpleUploadedFile("x.svg", b'<svg/>', "image/svg+xml")}, format="multipart").status_code == 400
    draft = TradeDraft.objects.get(journal=journal)
    TradeDraftImage.objects.create(draft=draft,digest='1'*64,content=b'x',size=30*1024*1024,content_type='image/png',name='big.png')
    assert upload().status_code == 400


def test_draft_invalid_payload_and_foreign_saved_id():
    journal, client, url = setup()
    for body in [{"revision": -1, "data": snapshot()}, {"revision": True, "data": snapshot()}, {"revision": 0, "data": []}, {"revision": 0, "data": {**snapshot(), "sections": [{}]}}]:
        assert client.put(url, body, format="json").status_code == 400
    assert client.put(url, {"revision": 0, "data": {**snapshot(), "savedTradeId": TradeFactory().pk}}, format="json").status_code == 404


def test_screenshot_upload_retry_has_stable_identity():
    journal, client, _ = setup()
    trade = TradeFactory(journal=journal)
    url = f"/api/journals/{journal.pk}/trades/{trade.pk}/screenshots/"
    with patch('core.supabase_client.upload_screenshot',return_value='https://example.test/chart.png') as upload:
        first = client.post(url, {"file": SimpleUploadedFile('a.png',b'png','image/png'),"client_id":"same-image"},format='multipart')
        second = client.post(url, {"file": SimpleUploadedFile('a.png',b'png','image/png'),"client_id":"same-image"},format='multipart')
        assert first.status_code == 201
        assert second.status_code == 200
        assert first.data['id'] == second.data['id']
        assert upload.call_count == 1
        assert trade.screenshots.count() == 1
