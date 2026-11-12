from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from core.models import Trade
from tests.factories import AssetFactory, EmotionTagFactory, JournalFactory, MistakeTagFactory, SetupTagFactory, TradeFactory, UserFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def journal(user):
    return JournalFactory(user=user)


@pytest.fixture
def authenticated_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


def trade_payload(journal, **overrides):
    asset = AssetFactory(journal=journal, symbol="GBPUSD")
    emotion = EmotionTagFactory(journal=journal, label="Focused")
    payload = {
        "asset_id": asset.id,
        "side": "BUY",
        "entry_datetime": "2026-06-01T10:00:00Z",
        "exit_datetime": "2026-06-01T11:00:00Z",
        "risk_percent": "1.00",
        "pnl_r": "2.00",
        "emotion_ids": [emotion.id],
        "mistake_ids": [],
        "notes": "Clean entry",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_trade_basis_precision_and_display_preference(authenticated_client, journal):
    journal.starting_capital = Decimal("10000")
    journal.save()
    url = f"/api/journals/{journal.pk}/"
    created = authenticated_client.post(url+"trades/", trade_payload(journal, pnl_r="1.2345"), format="json")
    assert created.status_code == 201
    trade = Trade.objects.get(pk=created.data["id"])
    assert (trade.capital_basis, trade.risk_amount, trade.pnl_amount) == (Decimal("10000"), Decimal("100"), Decimal("123.45"))
    assert authenticated_client.patch(url, {"starting_capital":"20000", "display_unit":"USD"}, format="json").status_code == 200
    trade.refresh_from_db()
    assert (trade.capital_basis, trade.risk_amount, trade.pnl_amount) == (Decimal("10000"), Decimal("100"), Decimal("123.45"))
    assert authenticated_client.get(url).data["display_unit"] == "USD"
    assert authenticated_client.patch(url, {"display_unit":"invalid"}, format="json").status_code == 400
    detail = url+f"trades/{trade.pk}/"
    assert authenticated_client.patch(detail, {"notes":"Unchanged amounts"}, format="json").status_code == 200
    trade.refresh_from_db()
    assert trade.pnl_amount == Decimal("123.45")
    assert authenticated_client.patch(detail, {"risk_percent":"2"}, format="json").status_code == 200
    trade.refresh_from_db()
    assert trade.risk_amount == Decimal("200")
    assert trade.pnl_amount == Decimal("246.9")


@pytest.mark.django_db
def test_unit_sorting_uses_full_dataset_and_missing_values_last(authenticated_client, journal):
    journal.starting_capital = Decimal("10000")
    journal.save()
    small = TradeFactory(journal=journal, pnl_r=Decimal("5"), risk_percent=Decimal("0.1"))
    large = TradeFactory(journal=journal, pnl_r=Decimal("2"), risk_percent=Decimal("2"))
    TradeFactory(journal=journal, pnl_r=None, risk_percent=None)
    url = f"/api/journals/{journal.pk}/trades/"
    assert authenticated_client.get(url,{"ordering":"-pnl_amount,-id"}).data["results"][0]["id"] == large.pk
    assert authenticated_client.get(url,{"ordering":"-pnl_percent,-id"}).data["results"][0]["id"] == large.pk
    assert authenticated_client.get(url,{"ordering":"-display_pnl_r,-id"}).data["results"][0]["id"] == small.pk


@pytest.mark.django_db
def test_create_trade_assigns_correct_journal(authenticated_client, user, journal):
    response = authenticated_client.post(
        f"/api/journals/{journal.id}/trades/", trade_payload(journal), format="json"
    )

    assert response.status_code == 201
    trade = Trade.objects.get(id=response.data["id"])
    assert trade.journal == journal


@pytest.mark.django_db
def test_list_trades_scoped_to_journal(authenticated_client, user, journal):
    other_journal = JournalFactory(user=user, name="FTMO")
    own_trade = TradeFactory(journal=journal)
    TradeFactory(journal=other_journal)
    TradeFactory()  # different user entirely

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == own_trade.id


@pytest.mark.django_db
def test_list_trades_returns_paginated_response(authenticated_client, user, journal):
    TradeFactory.create_batch(3, journal=journal)

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/")

    assert response.status_code == 200
    assert "count" in response.data
    assert "results" in response.data


@pytest.mark.django_db
def test_user_cannot_access_another_users_journal(authenticated_client):
    other_journal = JournalFactory()

    response = authenticated_client.get(f"/api/journals/{other_journal.id}/trades/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_user_cannot_retrieve_another_users_trade(authenticated_client, user, journal):
    other_trade = TradeFactory()

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/{other_trade.id}/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_rejects_invalid_exit_datetime(authenticated_client, user, journal):
    trade = TradeFactory(journal=journal)

    response = authenticated_client.patch(
        f"/api/journals/{journal.id}/trades/{trade.id}/",
        {"exit_datetime": "2026-05-01T09:00:00Z", "entry_datetime": "2026-05-01T10:00:00Z"},
        format="json",
    )

    assert response.status_code == 400
    assert "exit_datetime" in response.data


@pytest.mark.django_db
def test_trade_response_includes_nested_asset_and_emotions(authenticated_client, user, journal):
    asset = AssetFactory(journal=journal, symbol="EURUSD")
    emotion = EmotionTagFactory(journal=journal, label="Calm")
    trade = TradeFactory(journal=journal, asset=asset, emotions=[emotion])

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/{trade.id}/")

    assert response.status_code == 200
    assert response.data["asset"] == {"id": asset.id, "symbol": "EURUSD"}
    assert {"id": emotion.id, "label": "Calm"} in response.data["emotions"]


@pytest.mark.django_db
def test_trade_search_by_asset_symbol(authenticated_client, user, journal):
    eur_asset = AssetFactory(journal=journal, symbol="EURUSD")
    gbp_asset = AssetFactory(journal=journal, symbol="GBPUSD")
    expected = TradeFactory(journal=journal, asset=eur_asset, pnl_r=Decimal("1.00"))
    TradeFactory(journal=journal, asset=gbp_asset, pnl_r=Decimal("2.00"))

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/?search=EURUSD")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == expected.id


@pytest.mark.django_db
def test_trade_filter_by_status(authenticated_client, user, journal):
    win_trade = TradeFactory(journal=journal, status="WIN", pnl_r=Decimal("2.00"))
    TradeFactory(journal=journal, status="LOSS", pnl_r=Decimal("-1.00"))

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/?status=WIN")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == win_trade.id


@pytest.mark.django_db
def test_journal_crud_is_user_scoped(authenticated_client, user):
    response = authenticated_client.post(
        "/api/journals/",
        {
            "name": "FTMO",
            "journal_type": "trading",
            "starting_capital": "10000.00",
            "currency": "USD",
            "break_even_method": "ratio",
        },
        format="json",
    )

    assert response.status_code == 201
    journal_id = response.data["id"]

    detail = authenticated_client.get(f"/api/journals/{journal_id}/")
    assert detail.status_code == 200
    assert detail.data["name"] == "FTMO"

    other_journal = JournalFactory()
    other_detail = authenticated_client.get(f"/api/journals/{other_journal.id}/")
    assert other_detail.status_code == 404


@pytest.mark.django_db
def test_catalog_asset_crud(authenticated_client, user, journal):
    response = authenticated_client.post(
        f"/api/journals/{journal.id}/assets/", {"symbol": "eurusd", "name": "Euro"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["symbol"] == "EURUSD"

    asset_id = response.data["id"]
    patch = authenticated_client.patch(
        f"/api/journals/{journal.id}/assets/{asset_id}/", {"symbol": "GBPUSD"}, format="json"
    )
    assert patch.status_code == 200
    assert patch.data["symbol"] == "GBPUSD"


@pytest.mark.django_db
def test_catalog_asset_delete_archives_when_referenced(authenticated_client, user, journal):
    asset = AssetFactory(journal=journal, symbol="EURUSD")
    TradeFactory(journal=journal, asset=asset)

    response = authenticated_client.delete(f"/api/journals/{journal.id}/assets/{asset.id}/")

    assert response.status_code == 200
    asset.refresh_from_db()
    assert asset.is_archived is True


@pytest.mark.django_db
def test_setup_tag_pnl_grouping(authenticated_client, user, journal):
    setup = SetupTagFactory(journal=journal, label="Breakout")
    TradeFactory(journal=journal, setup=setup, pnl_r=Decimal("3.00"))
    TradeFactory(journal=journal, setup=setup, pnl_r=Decimal("-1.00"))

    response = authenticated_client.get(f"/api/journals/{journal.id}/analytics/pnl-by-setup/")

    assert response.status_code == 200
    assert response.data == [{"setup": "Breakout", "total_r": 2.0}]


@pytest.mark.django_db
def test_reference_timeframe_and_score_round_trip(authenticated_client, journal):
    created = authenticated_client.post(
        f"/api/journals/{journal.id}/trades/",
        trade_payload(journal, reference_timeframe="D1", trade_score=0), format="json",
    )
    assert created.status_code == 201
    assert created.data["reference_timeframe"] == "D1"
    assert created.data["trade_score"] == 0
    trade_id = created.data["id"]
    detail_url = f"/api/journals/{journal.id}/trades/{trade_id}/"
    updated = authenticated_client.patch(detail_url, {"reference_timeframe": "H4", "trade_score": 10}, format="json")
    assert updated.status_code == 200
    reread = authenticated_client.get(detail_url)
    assert reread.data["reference_timeframe"] == "H4"
    assert reread.data["trade_score"] == 10
    listed = authenticated_client.get(f"/api/journals/{journal.id}/trades/")
    assert listed.data["results"][0]["trade_score"] == 10
    unchanged = authenticated_client.patch(detail_url, {"notes": "Other edits"}, format="json")
    assert unchanged.data["trade_score"] == 10
    cleared = authenticated_client.patch(detail_url, {"reference_timeframe": None, "trade_score": None}, format="json")
    assert cleared.status_code == 200
    assert cleared.data["reference_timeframe"] is None
    assert cleared.data["trade_score"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("score", [-1, 11, "not a score"])
def test_trade_score_rejects_values_outside_scale(authenticated_client, journal, score):
    response = authenticated_client.post(
        f"/api/journals/{journal.id}/trades/", trade_payload(journal, trade_score=score), format="json",
    )
    assert response.status_code == 400
    assert "trade_score" in response.data


@pytest.mark.django_db
def test_existing_trades_have_optional_reference_and_score(authenticated_client, journal):
    trade = TradeFactory(journal=journal)
    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/{trade.id}/")
    assert response.data["reference_timeframe"] is None
    assert response.data["trade_score"] is None


@pytest.mark.django_db
def test_trade_score_database_constraint(journal):
    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        TradeFactory(journal=journal, trade_score=11)


@pytest.mark.django_db
def test_decimal_trade_score_round_trip(authenticated_client, journal):
    response = authenticated_client.post(f"/api/journals/{journal.pk}/trades/", trade_payload(journal, trade_score=7.25), format="json")
    assert response.status_code == 201
    trade = Trade.objects.get(pk=response.data["id"])
    assert trade.trade_score == Decimal("7.25")
    assert authenticated_client.get(f"/api/journals/{journal.pk}/trades/{trade.pk}/").data["trade_score"] == Decimal("7.25")


@pytest.mark.django_db
def test_filters_and_sorting_apply_before_pagination(authenticated_client, journal):
    from django.utils import timezone
    asset = AssetFactory(journal=journal, symbol="EURUSD")
    older_asset = AssetFactory(journal=journal, symbol="XAUUSD")
    setup = SetupTagFactory(journal=journal)
    now = timezone.now()
    records = []
    for index in range(45):
        entry = now - timezone.timedelta(days=index)
        records.append(Trade(journal=journal, asset=asset if index < 25 else older_asset, side="BUY", entry_datetime=entry, exit_datetime=entry + timezone.timedelta(hours=1), pnl_r=Decimal("-1") if index < 25 else Decimal(index), setup=setup if index >= 25 else None))
    Trade.objects.bulk_create(records)
    url = f"/api/journals/{journal.id}/trades/"
    first = authenticated_client.get(url)
    assert first.data["count"] == 45
    assert all(row["effective_status"] == "LOSS" for row in first.data["results"])
    wins = authenticated_client.get(url, {"status": "WIN"})
    assert wins.status_code == 200
    assert wins.data["count"] == 20
    assert len(wins.data["results"]) == 20
    assert all(row["effective_status"] == "WIN" for row in wins.data["results"])
    assert authenticated_client.get(url, {"status": "LOSS"}).data["count"] == 25
    second = authenticated_client.get(url, {"status": "LOSS", "page": 2})
    assert len(second.data["results"]) == 5
    assert authenticated_client.get(url, {"search": "XAUUSD"}).data["count"] == 20
    assert authenticated_client.get(url, {"asset": older_asset.id, "status": "WIN"}).data["count"] == 20
    assert authenticated_client.get(url, {"setup": setup.id}).data["count"] == 20
    sorted_rows = authenticated_client.get(url, {"ordering": "-pnl_r,-id"})
    assert Decimal(sorted_rows.data["results"][0]["pnl_r"]) == Decimal("44")
    asset_sorted = authenticated_client.get(url, {"ordering": "-asset__symbol,-id"})
    assert asset_sorted.data["results"][0]["asset"]["symbol"] == "XAUUSD"
    TradeFactory(journal=journal, pnl_r=None, exit_datetime=None)
    with_open = authenticated_client.get(url, {"ordering": "-pnl_r,-id"})
    assert Decimal(with_open.data["results"][0]["pnl_r"]) == Decimal("44")


@pytest.mark.django_db
def test_status_filters_follow_be_rule_manual_overrides_and_open_trades(authenticated_client, journal):
    journal.break_even_value = Decimal("0.20")
    journal.save()
    for value in ["0.1", "-0.1", "1", "-1"]:
        TradeFactory(journal=journal, pnl_r=Decimal(value), status=None)
    TradeFactory(journal=journal, pnl_r=Decimal("0.1"), status="WIN")
    TradeFactory(journal=journal, pnl_r=None, exit_datetime=None)
    TradeFactory(journal=journal, pnl_r=Decimal("1"), exit_datetime=None)
    url = f"/api/journals/{journal.id}/trades/"
    for status, count in [("WIN", 2), ("LOSS", 1), ("BE", 2), ("OPEN", 2)]:
        response = authenticated_client.get(url, {"status": status})
        assert response.status_code == 200
        assert response.data["count"] == count
        assert all(row["effective_status"] == status for row in response.data["results"])
    assert authenticated_client.get(url, {"status": "not-a-status"}).status_code == 400


@pytest.mark.django_db
def test_journal_custom_fields_round_trip_and_stay_scoped(authenticated_client, journal):
    from core.models import TradeCustomField
    field_url = f"/api/journals/{journal.id}/custom-fields/"
    definitions = []
    for section, kind, options in [("setup", "select", ["Trending", "Ranging"]), ("execution", "number", []), ("psychology", "boolean", []), ("notes", "text", [])]:
        created = authenticated_client.post(field_url, {"section": section, "label": f"Extra {kind}", "field_type": kind, "options": options}, format="json")
        assert created.status_code == 201
        definitions.append(created.data)
    values = {str(definitions[0]["id"]): "Trending", str(definitions[1]["id"]): 0, str(definitions[2]["id"]): False, str(definitions[3]["id"]): "A patient entry"}
    response = authenticated_client.post(f"/api/journals/{journal.id}/trades/", trade_payload(journal, custom_fields=values), format="json")
    assert response.status_code == 201
    url = f"/api/journals/{journal.id}/trades/{response.data['id']}/"
    assert authenticated_client.get(url).data["custom_fields"] == values
    unchanged = authenticated_client.patch(url, {"notes": "Edited"}, format="json")
    assert unchanged.data["custom_fields"] == values
    cleared = authenticated_client.patch(url, {"custom_fields": {str(definitions[0]["id"]): None}}, format="json")
    assert cleared.status_code == 200
    assert cleared.data["custom_fields"] == {str(definitions[0]["id"]): None}
    assert len(authenticated_client.get(field_url).data) == 4
    foreign_journal = JournalFactory()
    foreign_field = TradeCustomField.objects.create(journal=foreign_journal, section="setup", label="Private")
    invalid = authenticated_client.patch(url, {"custom_fields": {str(foreign_field.id): "No"}}, format="json")
    assert invalid.status_code == 400
    assert authenticated_client.get(f"/api/journals/{foreign_journal.id}/custom-fields/").status_code == 404
    assert authenticated_client.post(f"/api/journals/{foreign_journal.id}/custom-fields/", {"section":"setup", "label":"No access"}, format="json").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("kind,options,value", [("number", [], "not a number"), ("number", [], True), ("boolean", [], "yes"), ("select", ["A", "B"], "C"), ("text", [], {"nested": "object"})])
def test_custom_field_values_are_typed(authenticated_client, journal, kind, options, value):
    from core.models import TradeCustomField
    definition = TradeCustomField.objects.create(journal=journal, section="setup", label="Typed", field_type=kind, options=options)
    response = authenticated_client.post(f"/api/journals/{journal.id}/trades/", trade_payload(journal, custom_fields={str(definition.id): value}), format="json")
    assert response.status_code == 400
    assert "custom_fields" in response.data


@pytest.mark.django_db
def test_custom_field_definitions_validate_duplicates_and_options(authenticated_client, journal):
    url = f"/api/journals/{journal.id}/custom-fields/"
    payload = {"section": "setup", "label": "Market state", "field_type": "select", "options": ["Trending", "Ranging"]}
    assert authenticated_client.post(url, payload, format="json").status_code == 201
    assert authenticated_client.post(url, {**payload, "label": "MARKET STATE"}, format="json").status_code == 400
    assert authenticated_client.post(url, {**payload, "section": "execution"}, format="json").status_code == 201
    for patch in [{"label":" "}, {"label":"Another", "options":[]}, {"label":"Another", "options":["A","A"]}, {"label":"Another", "section":"invalid"}]:
        assert authenticated_client.post(url, {**payload, **patch}, format="json").status_code == 400


@pytest.mark.django_db
def test_delete_custom_field_cleans_values_and_checks_ownership(authenticated_client, journal):
    from core.models import TradeCustomField
    field = TradeCustomField.objects.create(journal=journal, section="setup", label="Condition", field_type="text")
    trade = TradeFactory(journal=journal, custom_fields={str(field.pk): "Trending", "999": "Keep"})
    foreign = TradeCustomField.objects.create(journal=JournalFactory(), section="setup", label="Private", field_type="text")
    url = f"/api/journals/{journal.pk}/custom-fields/"
    assert authenticated_client.delete(f"{url}{foreign.pk}/").status_code == 404
    assert authenticated_client.delete(f"{url}{field.pk}/").status_code == 204
    trade.refresh_from_db()
    assert trade.custom_fields == {"999": "Keep"}
    assert not TradeCustomField.objects.filter(pk=field.pk).exists()
    assert TradeCustomField.objects.filter(pk=foreign.pk).exists()

@pytest.mark.django_db
def test_custom_setup_choices_round_trip(authenticated_client, journal):
    url = f"/api/journals/{journal.pk}/trades/"
    response = authenticated_client.post(url, trade_payload(journal,
        reference_timeframe="M45", opportunity_timeframe="H2", entry_timeframe="M3",
        trend_direction="Neutral", session="After hours"), format="json")
    assert response.status_code == 201
    detail = url + f"{response.data['id']}/"
    saved = authenticated_client.get(detail).data
    assert saved["reference_timeframe"] == "M45"
    assert saved["trend_direction"] == "Neutral"
    assert saved["session"] == "After hours"
    assert authenticated_client.patch(detail, {"trend_direction": "x" * 21}, format="json").status_code == 400
    assert authenticated_client.patch(detail, {"reference_timeframe": "x" * 11}, format="json").status_code == 400
    # Existing enum values remain valid alongside custom descriptions.
    assert authenticated_client.patch(detail, {"trend_direction": "BULLISH"}, format="json").status_code == 200

@pytest.mark.django_db
def test_rich_notes_and_image_width_round_trip(authenticated_client, journal):
    from core.models import TradeScreenshot
    doc = {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Plan"}]}, {"type": "paragraph", "content": [{"type": "text", "text": "Wait", "marks": [{"type": "textStyle", "attrs": {"color": "#ff0000"}}]}]}]}
    document = {"version": 1, "general": doc, "sections": [{"id": "before", "title": "Before", "content": doc}]}
    url = f"/api/journals/{journal.pk}/trades/"
    response = authenticated_client.post(url, trade_payload(journal, notes="Plan\nWait", notes_document=document), format="json")
    assert response.status_code == 201
    detail = url + f"{response.data['id']}/"
    assert authenticated_client.get(detail).data["notes_document"] == document
    screenshot = TradeScreenshot.objects.create(trade_id=response.data['id'], image_url="https://example.test/chart.png")
    image_url = detail + f"screenshots/{screenshot.pk}/"
    assert authenticated_client.patch(image_url, {"display_width": 60}, format="json").status_code == 200
    assert authenticated_client.get(detail).data["screenshots"][0]["display_width"] == 60
    assert authenticated_client.patch(image_url, {"display_width": 101}, format="json").status_code == 400
    assert authenticated_client.patch(image_url, {"display_width": 24}, format="json").status_code == 400
    other = TradeFactory()
    hidden = TradeScreenshot.objects.create(trade=other, image_url="https://example.test/private.png")
    assert authenticated_client.patch(detail + f"screenshots/{hidden.pk}/", {"display_width": 50}, format="json").status_code == 404
    for content in [{"type": "script"}, {"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "textStyle", "attrs": {"color": "url(javascript:x)"}}]}]}]:
        bad = {"version": 1, "general": {"type": "doc", "content": [content]}, "sections": []}
        assert authenticated_client.patch(detail, {"notes_document": bad}, format="json").status_code == 400
    assert authenticated_client.get(detail).data["notes_document"] == document

@pytest.mark.django_db
def test_edit_dropdown_options_preserves_history_and_scopes_access(authenticated_client, journal):
    from core.models import TradeCustomField
    field = TradeCustomField.objects.create(journal=journal, section="setup", label="Condition", field_type="select", options=["Trending", "Ranging"])
    trade = TradeFactory(journal=journal, custom_fields={str(field.pk): "Trending"})
    url = f"/api/journals/{journal.pk}/custom-fields/{field.pk}/"
    response = authenticated_client.patch(url, {"options": [" Sideways ", "Volatile"]}, format="json")
    assert response.status_code == 200
    assert response.data["options"] == ["Sideways", "Volatile"]
    trade.refresh_from_db()
    assert trade.custom_fields == {str(field.pk): "Trending"}
    trade_url = f"/api/journals/{journal.pk}/trades/{trade.pk}/"
    assert authenticated_client.patch(trade_url, {"custom_fields": trade.custom_fields}, format="json").status_code == 200
    assert authenticated_client.post(f"/api/journals/{journal.pk}/trades/", trade_payload(journal, custom_fields={str(field.pk): "Trending"}), format="json").status_code == 400
    for options in [["A", "a"], [" "], ["A" * 101], ["A"] * 101, None, "A"]:
        assert authenticated_client.patch(url, {"options": options}, format="json").status_code == 400
    assert authenticated_client.patch(url, {"options": []}, format="json").status_code == 200
    foreign = TradeCustomField.objects.create(journal=JournalFactory(), section="setup", label="Private", field_type="select", options=["A"])
    assert authenticated_client.patch(f"/api/journals/{journal.pk}/custom-fields/{foreign.pk}/", {"options": ["B"]}, format="json").status_code == 404
    field.field_type = "boolean"
    field.save()
    assert authenticated_client.patch(url, {"options": ["Yes"]}, format="json").status_code == 400

@pytest.mark.django_db
def test_text_after_images_round_trips_and_validates_documents(authenticated_client, journal):
    import copy
    from core.models import TradeScreenshot
    empty = {"type": "doc", "content": [{"type": "paragraph"}]}
    note = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Price rejected the level.", "marks": [{"type": "bold"}]}]}]}
    trade = TradeFactory(journal=journal)
    image = TradeScreenshot.objects.create(trade=trade, image_url="https://example.test/chart.png")
    document = {"version": 1, "general": empty, "sections": [{"id": "before", "title": "Before", "content": empty, "image_layout": [[str(image.pk)]], "image_notes": {str(image.pk): note}}]}
    url = f"/api/journals/{journal.pk}/trades/{trade.pk}/"
    response = authenticated_client.patch(url, {"notes_document": document}, format="json")
    assert response.status_code == 200
    assert authenticated_client.get(url).data["notes_document"] == document
    for invalid in [[], {"": note}, {"1": {"type": "script"}}, {"1": {"type": "doc", "content": [{"type": "text", "text": "bad", "marks": [{"type": "textStyle", "attrs": {"color": "url(javascript:x)"}}]}]}}]:
        bad = copy.deepcopy(document)
        bad["sections"][0]["image_notes"] = invalid
        assert authenticated_client.patch(url, {"notes_document": bad}, format="json").status_code == 400
    assert authenticated_client.get(url).data["notes_document"] == document

@pytest.mark.django_db
def test_image_annotations_validate_and_round_trip(authenticated_client, journal):
    import copy
    empty = {"type": "doc", "content": [{"type": "paragraph"}]}
    arrow = {"type": "arrow", "color": "#facc15", "x1": 10, "y1": 20, "x2": 70, "y2": 80}
    document = {"version": 1, "general": empty, "sections": [{"id": "before", "title": "Before", "content": empty, "image_details": {"1": {"caption": "Rejection", "annotations": [arrow]}}}]}
    trade = TradeFactory(journal=journal)
    url = f"/api/journals/{journal.pk}/trades/{trade.pk}/"
    assert authenticated_client.patch(url, {"notes_document": document}, format="json").status_code == 200
    assert authenticated_client.get(url).data["notes_document"] == document
    for change in [{"type": "script"}, {"color": "url(javascript:x)"}, {"x1": -1}, {"x2": 101}, {"y2": True}, {"y1": "20"}]:
        bad = copy.deepcopy(document)
        bad["sections"][0]["image_details"]["1"]["annotations"] = [{**arrow, **change}]
        assert authenticated_client.patch(url, {"notes_document": bad}, format="json").status_code == 400
    bad = copy.deepcopy(document)
    bad["sections"][0]["image_details"]["1"]["caption"] = "a" * 301
    assert authenticated_client.patch(url, {"notes_document": bad}, format="json").status_code == 400
    assert authenticated_client.get(url).data["notes_document"] == document
