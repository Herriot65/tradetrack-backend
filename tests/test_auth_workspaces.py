import pytest
from rest_framework.test import APIClient

from core.models import Journal
from users.models import User


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
