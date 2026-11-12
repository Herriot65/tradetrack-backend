"""Django ModelBackend semantics with credential-free sign-in phase timings."""
from contextlib import contextmanager
from time import perf_counter, thread_time

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import connections


@contextmanager
def auth_phase(request, name, *, cpu=False):
    started = perf_counter()
    cpu_started = thread_time() if cpu else None
    try:
        yield
    finally:
        if request is not None:
            timings = getattr(request, "_auth_timings", None)
            if timings is None:
                timings = request._auth_timings = {}
            timings[name] = (perf_counter() - started) * 1000
            if cpu:
                timings[f"{name}_cpu"] = (thread_time() - cpu_started) * 1000


class TimedModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        # Keep Django's lookup, dummy hashing, password upgrade, and inactive-user
        # behavior. Inherit permission handling and get_user from ModelBackend.
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        manager = User._default_manager
        with auth_phase(request, "db_connect"):
            connections[manager.db].ensure_connection()
        try:
            with auth_phase(request, "user_lookup"):
                user = manager.get_by_natural_key(username)
        except User.DoesNotExist:
            with auth_phase(request, "password", cpu=True):
                User().set_password(password)
        else:
            with auth_phase(request, "password", cpu=True):
                # check_password also upgrades a legacy hash after verification.
                valid = user.check_password(password)
            if valid and self.user_can_authenticate(user):
                return user
        return None


def attach_auth_timings(request, response):
    timings = getattr(request, "_auth_timings", {})
    if timings:
        response["Server-Timing"] = ", ".join(
            f"{name};dur={elapsed:.1f}" for name, elapsed in timings.items()
        )
    response["Cache-Control"] = "no-store"
    return response
