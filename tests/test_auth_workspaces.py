import pytest
from rest_framework.test import APIClient

from core.models import Workspace
from users.models import User


@pytest.mark.django_db
def test_register_creates_default_workspace():
    response = APIClient().post(
        "/api/auth/register/",
        {
            "email": "newuser@example.com",
            "password": "testpass123",
            "first_name": "New",
            "last_name": "User",
        },
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(email="newuser@example.com")
    assert Workspace.objects.filter(user=user, name="Main").exists()
