"""Validate the small, non-HTML document format used by trade notes."""
import json
import re
from rest_framework import serializers

NODES = {"doc", "paragraph", "text", "heading", "bulletList", "orderedList", "listItem", "blockquote", "hardBreak"}
MARKS = {"bold", "italic", "strike", "underline", "code", "textStyle"}

def validate_notes_document(value):
    if value == {}:
        return value
    def invalid():
        raise serializers.ValidationError("Use a valid trade notes document.")
    if not isinstance(value, dict) or value.get("version") != 1 or len(json.dumps(value)) > 200000:
        invalid()
    count = 0
    def node(item, depth=0):
        nonlocal count
        count += 1
        if count > 5000 or depth > 30 or not isinstance(item, dict) or item.get("type") not in NODES:
            invalid()
        if "text" in item and not isinstance(item["text"], str):
            invalid()
        attrs = item.get("attrs") or {}
        if not isinstance(attrs, dict) or (item["type"] == "heading" and attrs.get("level") not in (1, 2, 3)):
            invalid()
        marks = item.get("marks", [])
        if not isinstance(marks, list):
            invalid()
        for mark in marks:
            if not isinstance(mark, dict) or mark.get("type") not in MARKS:
                invalid()
            if mark["type"] == "textStyle":
                mark_attrs = mark.get("attrs") or {}
                if not isinstance(mark_attrs, dict):
                    invalid()
                color = mark_attrs.get("color")
                if color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
                    invalid()
        content = item.get("content", [])
        if not isinstance(content, list):
            invalid()
        for child in content:
            node(child, depth + 1)
    def document(doc):
        if not isinstance(doc, dict) or doc.get("type") != "doc":
            invalid()
        node(doc)
    document(value.get("general"))
    sections = value.get("sections")
    if not isinstance(sections, list) or len(sections) > 50:
        invalid()
    ids = set()
    for section in sections:
        if not isinstance(section, dict):
            invalid()
        for key in ("id", "title"):
            if not isinstance(section.get(key), str) or not 1 <= len(section[key]) <= 100:
                invalid()
        if section["id"] in ids:
            invalid()
        ids.add(section["id"])
        document(section.get("content"))
    return value
