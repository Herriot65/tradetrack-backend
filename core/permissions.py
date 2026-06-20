from rest_framework.permissions import BasePermission


class IsJournalOwner(BasePermission):
    """Allow access only to journals owned by the authenticated user."""

    def has_object_permission(self, request, view, obj) -> bool:
        owner = getattr(obj, "user", None)
        if owner is None:
            journal = getattr(obj, "journal", None)
            if journal is not None:
                owner = journal.user
        return bool(request.user and request.user.is_authenticated and owner == request.user)
