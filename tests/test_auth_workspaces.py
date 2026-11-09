import pytest
from rest_framework.test import APIClient

from core.models import Journal
from users.models import User


@pytest.mark.django_db
def test_user_preferences_persist_and_reject_invalid_timezone():
    user = User.objects.create_user(email="preferences@example.com", password="testpass123")
    other = User.objects.create_user(email="other@example.com", password="testpass123")
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.patch("/api/auth/me/", {"timezone":"Africa/Tunis", "rating_style":"stars"}, format="json")
    assert response.status_code == 200
    user.refresh_from_db()
    other.refresh_from_db()
    assert user.timezone == "Africa/Tunis"
    assert user.rating_style == "stars"
    assert other.timezone == ""
    assert client.get("/api/auth/me/").data["timezone"] == "Africa/Tunis"
    assert client.patch("/api/auth/me/", {"timezone":"Invalid/Zone"}, format="json").status_code == 400
    assert client.patch("/api/auth/me/", {"rating_style":"invalid"}, format="json").status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("theme", ["light", "dark", "system"])
def test_theme_preference_persists_for_current_user(theme):
    user = User.objects.create_user(email="theme@example.com", password="testpass123")
    other = User.objects.create_user(email="other@example.com", password="testpass123")
    assert user.theme == "system"
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.patch("/api/auth/me/", {"theme": theme}, format="json")
    assert response.status_code == 200
    assert response.data["theme"] == theme
    user.refresh_from_db()
    other.refresh_from_db()
    assert user.theme == theme
    assert other.theme == "system"
    assert client.get("/api/auth/me/").data["theme"] == theme
    login = APIClient().post("/api/auth/login/", {"email": user.email, "password": "testpass123"}, format="json")
    assert login.status_code == 200
    assert login.data["user"]["theme"] == theme


@pytest.mark.django_db
@pytest.mark.parametrize("theme", ["invalid", "", None, "LIGHT"])
def test_invalid_theme_does_not_change_preferences(theme):
    user = User.objects.create_user(email="theme@example.com", password="testpass123", theme="dark")
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.patch("/api/auth/me/", {"theme": theme, "timezone": "Africa/Tunis"}, format="json")
    assert response.status_code == 400
    assert "theme" in response.data
    user.refresh_from_db()
    assert user.theme == "dark"
    assert user.timezone == ""


def test_theme_preference_requires_authentication():
    response = APIClient().patch("/api/auth/me/", {"theme": "light"}, format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_register_does_not_create_default_journal():
    APIClient().post(
        "/api/auth/register/",
        {
            "email": "newuser@example.com",
            "password": "testpass123",
            "first_name": "New",
            "last_name": "User",
        },
        format="json",
    )

    user = User.objects.get(email="newuser@example.com")
    assert Journal.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_register_succeeds_and_user_has_no_journals():
    response = APIClient().post(
        "/api/auth/register/",
        {"email": "j@example.com", "password": "testpass123"},
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(email="j@example.com")
    assert not user.journals.exists()


@pytest.mark.django_db
def test_entry_configuration_scopes_persist_and_isolate_users():
    user = User.objects.create_user(email="entry@example.com", password="testpass123")
    other = User.objects.create_user(email="entry-other@example.com", password="testpass123")
    current = Journal.objects.create(user=user, name="Current")
    existing = Journal.objects.create(user=user, name="Existing")
    foreign = Journal.objects.create(user=other, name="Foreign")
    client = APIClient()
    client.force_authenticate(user=user)

    def save(journal, scope, fields):
        response = client.patch("/api/auth/me/", {"entry_configuration_update": {
            "journal_id": journal.id, "scope": scope, "fields": fields,
        }}, format="json")
        user.refresh_from_db()
        return response

    layout = {"risk_percent": {"label": "Position risk"}, "commission": {"visible": False}}
    assert save(current, "journal", layout).status_code == 200
    config = client.get("/api/auth/me/").data["entry_configuration"]
    assert config["journals"][str(current.id)] == layout
    assert "defaults" not in config
    assert save(current, "future", layout).status_code == 200
    config = client.get("/api/auth/me/").data["entry_configuration"]
    assert config["defaults"] == layout
    assert config["journals"][str(existing.id)] == {}
    future = Journal.objects.create(user=user, name="Future")
    assert config["journals"].get(str(future.id), config["defaults"]) == layout
    assert save(current, "future", {"swap": {"visible": False}}).status_code == 200
    config = client.get("/api/auth/me/").data["entry_configuration"]
    assert config["journals"][str(future.id)] == layout
    assert config["journals"][str(existing.id)] == {}
    assert save(foreign, "journal", {}).status_code == 400
    assert save(current, "journal", {"pnl_r": {"visible": False}}).status_code == 400
    assert save(current, "journal", {"risk_percent": {"label": ""}}).status_code == 400
    assert save(current, "journal", {"unknown": {"label": "Bad"}}).status_code == 400
    other.refresh_from_db()
    assert other.entry_configuration == {}
