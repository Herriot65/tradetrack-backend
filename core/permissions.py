from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """Allow access only to objects owned by the authenticated user."""

    def has_object_permission(self, request, view, obj) -> bool:
        owner = getattr(obj, "owner", None)
        if owner is None:
            owner = getattr(obj, "user", None)
        if owner is None and hasattr(obj, "trade"):
            owner = getattr(obj.trade, "owner", None)

        return bool(request.user and request.user.is_authenticated and owner == request.user)
