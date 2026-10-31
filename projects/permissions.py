from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsProjectOwnerOrReadOnly(BasePermission):
    """Members may read a project; only the owner may change or delete it."""

    message = "Only the project owner can do this."

    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.owner_id == request.user.id
