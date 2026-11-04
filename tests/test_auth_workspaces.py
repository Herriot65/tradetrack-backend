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
