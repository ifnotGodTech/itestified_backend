from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.users.choices import AdminAssignmentStatus, UserAccountStatus

from .exceptions import AuthnError


def ensure_active_user(user) -> None:
    if user.account_status != UserAccountStatus.ACTIVE:
        raise AuthnError("This account is not active.")


def ensure_active_admin_assignment(assignment) -> None:
    if assignment is None or assignment.status != AdminAssignmentStatus.ACTIVE:
        raise AuthnError("Admin access is not active for this account.")


def validate_user_password(password: str, user=None) -> None:
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise AuthnError(" ".join(exc.messages)) from exc
