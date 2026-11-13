from io import StringIO
import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import get_hasher, make_password
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

User = get_user_model()
PASSWORD = "Synthetic-login-password!"


def timings(response):
    return {item.split(";dur=")[0]: float(item.split(";dur=")[1])
            for item in response["Server-Timing"].split(", ")}


def test_argon2_parameters_and_cpu_benchmark():
    hasher = get_hasher()
    assert hasher.algorithm == "argon2"
    assert hasher.memory_cost == 32768
    assert hasher.time_cost == 2
    assert hasher.parallelism == 1
    encoded = make_password(PASSWORD)
    assert encoded.startswith("argon2$argon2id$")
    assert hasher.verify(PASSWORD, encoded)
    assert not hasher.verify("wrong", encoded)
    output = StringIO()
    call_command("benchmark_password_hashers", samples=1, stdout=output)
    report = json.loads(output.getvalue())
    assert {row["algorithm"] for row in report} == {"argon2", "pbkdf2_sha256"}
    assert all(row["median_wall_ms"] > 0 and row["median_thread_cpu_ms"] > 0 for row in report)


@pytest.mark.django_db
@pytest.mark.parametrize("legacy", ["pbkdf2_sha256", "pbkdf2_sha1"])
def test_legacy_login_upgrades_once_and_retains_a_valid_session(legacy):
    user = User.objects.create(email="legacy@example.invalid", password=make_password(PASSWORD, hasher=legacy))
    client = APIClient()
    with CaptureQueriesContext(connection) as queries:
        first = client.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert first.status_code == 200
    user.refresh_from_db()
    assert user.password.startswith("argon2$argon2id$")
    assert any('UPDATE "users_user"' in row["sql"] for row in queries)
    saved = user.password
    with CaptureQueriesContext(connection) as queries:
        second = client.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert second.status_code == 200
    assert not any('UPDATE "users_user"' in row["sql"] for row in queries)
    user.refresh_from_db()
    assert user.password == saved
    phase = timings(second)
    assert set(phase) == {"db_connect", "user_lookup", "password", "password_cpu", "session", "app"}
    assert all(value >= 0 for value in phase.values())
    assert PASSWORD not in second["Server-Timing"] and user.email not in second["Server-Timing"]
    assert second["Cache-Control"] == "no-store"
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {second.data['access']}")
    assert client.get("/api/auth/me/").data["id"] == user.id
    assert client.post("/api/auth/logout/", {"refresh": second.data["refresh"]}, format="json").status_code == 200
    assert APIClient().post("/api/auth/refresh/", {"refresh": second.data["refresh"]}, format="json").status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["wrong", "inactive", "missing", "unusable"])
def test_rejected_accounts_never_receive_a_session(kind):
    user = User.objects.create_user(email="reject@example.invalid", password=PASSWORD)
    if kind == "inactive":
        user.is_active = False
        user.save(update_fields=["is_active"])
    if kind == "unusable":
        user.set_unusable_password()
        user.save(update_fields=["password"])
    response = APIClient().post("/api/auth/login/", {
        "email": "missing@example.invalid" if kind == "missing" else user.email,
        "password": "wrong-password" if kind == "wrong" else PASSWORD,
    }, format="json")
    assert response.status_code == 401
    assert "access" not in response.data and "refresh" not in response.data
    assert "session" not in timings(response)
    assert User.objects.count() == 1
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
    assert OutstandingToken.objects.count() == 0


@pytest.mark.django_db
def test_failed_legacy_password_is_not_rewritten():
    encoded = make_password(PASSWORD, hasher="pbkdf2_sha256")
    user = User.objects.create(email="legacy@example.invalid", password=encoded)
    assert APIClient().post("/api/auth/login/", {"email": user.email, "password": "wrong"}, format="json").status_code == 401
    user.refresh_from_db()
    assert user.password == encoded


@pytest.mark.django_db
def test_browser_can_read_timing_header():
    response = APIClient().post("/api/auth/login/", {"email": "missing@example.invalid", "password": PASSWORD},
                                format="json", HTTP_ORIGIN="https://tradetrack-frontend-psi.vercel.app")
    assert response.status_code == 401
    assert response["Access-Control-Allow-Origin"] == "https://tradetrack-frontend-psi.vercel.app"
    assert "server-timing" in response["Access-Control-Expose-Headers"].lower()
    assert "password_cpu" in timings(response)
