"""Validate Google signatures, audience, issuer, expiry and verified email."""
import jwt
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

_jwks = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=5)


class GoogleUnavailable(Exception):
    pass


def verify_google_token(credential):
    try:
        key = _jwks.get_signing_key_from_jwt(credential)
        claims = jwt.decode(
            credential, key.key, algorithms=["RS256"], audience=settings.GOOGLE_CLIENT_ID,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["exp", "iat", "sub", "email", "email_verified"]},
        )
        if claims["email_verified"] is not True or not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ValueError("Unverified identity")
        email = claims["email"]
        if not isinstance(email, str) or len(email) > 254:
            raise ValueError("Invalid email")
        validate_email(email)
        claims["email"] = email.lower()
        return claims
    except jwt.PyJWKClientConnectionError as exc:
        raise GoogleUnavailable from exc
    except (jwt.PyJWTError, ValidationError, TypeError, KeyError) as exc:
        raise ValueError("Invalid Google credential") from exc
