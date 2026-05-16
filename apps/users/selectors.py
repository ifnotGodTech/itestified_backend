from typing import Optional

from apps.users.choices import AdminAssignmentStatus
from apps.users.models import AdminAssignment, User


def get_active_admin_assignment(user: User) -> Optional[AdminAssignment]:
    return (
        AdminAssignment.objects.select_related("role")
        .filter(user=user, status=AdminAssignmentStatus.ACTIVE)
        .first()
    )
