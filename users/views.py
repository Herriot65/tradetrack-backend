from django.shortcuts import render

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from .serializers import RegisterSerializer, UserSerializer
from .authentication import auth_phase, attach_auth_timings

from rest_framework.views import APIView
from django.contrib.auth import authenticate

from rest_framework_simplejwt.tokens import RefreshToken

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        user = authenticate(request, email=email, password=password)

        if user is None:
            return attach_auth_timings(request, Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            ))

        with auth_phase(request, "session"):
            refresh = RefreshToken.for_user(user)
            payload = {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        return attach_auth_timings(request, Response(payload))

class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response({"detail": "Logged out"})
        except Exception:
            return Response(
                {"detail": "Invalid token"},
                status=status.HTTP_400_BAD_REQUEST
            )


class GoogleLoginView(APIView):
    """Exchange a verified Google identity for the platform's own JWT session."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.db import transaction, IntegrityError
        from .google_auth import verify_google_token, GoogleUnavailable
        if not settings.GOOGLE_CLIENT_ID:
            return Response({"detail": "Google sign-in is not configured."}, status=503)
        credential = request.data.get("credential")
        if not isinstance(credential, str) or not credential or len(credential) > 16384:
            return Response({"detail": "A Google credential is required."}, status=400)
        try:
            claims = verify_google_token(credential)
        except GoogleUnavailable:
            return Response({"detail": "Google sign-in is temporarily unavailable. Please try again."}, status=503)
        except ValueError:
            return Response({"detail": "Invalid or expired Google credential."}, status=401)
        User = get_user_model()
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().filter(google_sub=claims["sub"]).first()
                if user is None:
                    user = User.objects.select_for_update().filter(email__iexact=claims["email"]).first()
                    if user is not None:
                        # Google is authoritative for Gmail and verified Workspace domains.
                        authoritative = claims["email"].endswith("@gmail.com") or bool(claims.get("hd"))
                        if user.google_sub or not authoritative:
                            return Response({"detail": "Please sign in with your existing account password."}, status=409)
                        user.google_sub = claims["sub"]
                        user.save(update_fields=["google_sub"])
                    else:
                        user = User.objects.create_user(
                            email=claims["email"], google_sub=claims["sub"],
                            first_name=str(claims.get("given_name", ""))[:50],
                            last_name=str(claims.get("family_name", ""))[:50],
                        )
                if not user.is_active:
                    return Response({"detail": "This account is disabled."}, status=403)
                refresh = RefreshToken.for_user(user)
        except IntegrityError:
            return Response({"detail": "Please retry Google sign-in."}, status=409)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "user": UserSerializer(user).data})
