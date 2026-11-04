import time
from unittest.mock import patch
from types import SimpleNamespace
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings
from rest_framework.test import APIClient
from users.models import User
from users.google_auth import verify_google_token

@pytest.fixture
def identity():
    return dict(sub="google-123", email="trader@gmail.com", email_verified=True,
                aud="test-client", iss="https://accounts.google.com",
                iat=int(time.time()), exp=int(time.time()) + 300)

@pytest.mark.django_db
@override_settings(GOOGLE_CLIENT_ID="test-client")
def test_signup_signin_session_and_disabled(identity):
    client = APIClient()
    with patch("users.google_auth.verify_google_token", return_value=identity):
        response = client.post("/api/auth/google/", {"credential": "token"})
        assert response.status_code == 200
        user = User.objects.get(google_sub=identity["sub"])
        assert not user.has_usable_password()
        assert client.post("/api/auth/google/", {"credential": "token"}).data["user"]["id"] == user.id
        assert User.objects.count() == 1
        client.credentials(HTTP_AUTHORIZATION="Bearer " + response.data["access"])
        assert client.get("/api/auth/me/").status_code == 200
        user.is_active = False
        user.save()
        assert client.post("/api/auth/google/", {"credential": "token"}).status_code == 403

@pytest.mark.django_db
@override_settings(GOOGLE_CLIENT_ID="test-client")
def test_existing_account_linking(identity):
    user = User.objects.create_user(email=identity["email"], password="existing-pass")
    with patch("users.google_auth.verify_google_token", return_value=identity):
        assert APIClient().post("/api/auth/google/", {"credential": "token"}).status_code == 200
    user.refresh_from_db()
    assert user.google_sub == identity["sub"]
    assert user.check_password("existing-pass")
    identity.update(sub="other-sub", email="external@example.com")
    User.objects.create_user(email=identity["email"], password="existing-pass")
    with patch("users.google_auth.verify_google_token", return_value=identity):
        assert APIClient().post("/api/auth/google/", {"credential": "token"}).status_code == 409

@override_settings(GOOGLE_CLIENT_ID="test-client")
@pytest.mark.parametrize("change", [{}, {"aud": "wrong"}, {"iss": "attacker"}, {"exp": 1}, {"email_verified": False}, {"sub": ""}])
def test_token_verification(identity, change):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity.update(change)
    token = jwt.encode(identity, private, algorithm="RS256")
    with patch("users.google_auth._jwks.get_signing_key_from_jwt", return_value=SimpleNamespace(key=private.public_key())):
        if change:
            with pytest.raises(ValueError):
                verify_google_token(token)
        else:
            assert verify_google_token(token)["sub"] == identity["sub"]
            wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            with pytest.raises(ValueError):
                verify_google_token(jwt.encode(identity, wrong_key, algorithm="RS256"))

@override_settings(GOOGLE_CLIENT_ID="test-client")
def test_invalid_input():
    client = APIClient()
    assert client.post("/api/auth/google/", {}).status_code == 400
    with patch("users.google_auth.verify_google_token", side_effect=ValueError):
        assert client.post("/api/auth/google/", {"credential": "bad"}).status_code == 401
    with override_settings(GOOGLE_CLIENT_ID=""):
        assert client.post("/api/auth/google/", {"credential": "token"}).status_code == 503
