from rest_framework.permissions import BasePermission

from apps.users.choices import AdminRoleCode
from apps.users.selectors import get_active_admin_assignment


class IsActiveAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        return get_active_admin_assignment(request.user) is not None


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        assignment = get_active_admin_assignment(request.user)
        return assignment is not None and assignment.role.code == AdminRoleCode.SUPER_ADMIN
