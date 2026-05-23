import secrets
import base64
import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import update_last_login
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.users.choices import AdminAssignmentStatus, AdminRoleCode
from apps.users.models import AdminAssignment, AdminRole, Profile, User
from apps.users.selectors import get_active_admin_assignment

from ..choices import ChallengePurpose
from ..exceptions import AuthnError, ChallengeVerificationError, EmailDeliveryError
from ..models import EmailChallenge, UserSession
from ..validators import ensure_active_admin_assignment, ensure_active_user, validate_user_password

BRAND_PURPLE_70 = "#6E46FF"  # mobile AppColors.purple70 / brandMainColor1
BRAND_PURPLE_10 = "#F6F1FF"  # mobile AppColors.purple10
BRAND_PURPLE_30 = "#D8C8FF"  # mobile AppColors.purple30
BRAND_PURPLE_40 = "#E6D8FF"  # mobile AppColors.purple40
BRAND_ORANGE = "#FF9F4A"  # mobile AppColors.colorsOrange / brandSupportColor3
BRAND_DARK_GREY_100 = "#120F1A"  # mobile AppColors.darkGrey100
logger = logging.getLogger(__name__)


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _challenge_expiry() -> timezone.datetime:
    return timezone.now() + timedelta(minutes=15)


def _get_latest_challenge(email: str, purpose: str, for_update: bool = False) -> Optional[EmailChallenge]:
    qs = EmailChallenge.objects.filter(
        email__iexact=email, purpose=purpose, consumed_at__isnull=True
    ).order_by("-created_at")
    if for_update:
        qs = qs.select_for_update()
    return qs.first()


def _send_otp_email(*, email: str, purpose: str, code: str) -> None:
    expires_minutes = 15
    support_email = getattr(settings, "SUPPORT_EMAIL", "support@itestified.app")
    if purpose == ChallengePurpose.PASSWORD_RESET:
        subject = "iTestified password reset code"
        purpose_line = "Use this code to reset your iTestified account password."
    elif purpose == ChallengePurpose.ADMIN_INVITE:
        subject = "iTestified admin invitation code"
        purpose_line = "Use this code to activate your iTestified admin account."
    else:
        subject = "iTestified verification code"
        purpose_line = "Use this code to verify your iTestified account registration."

    start_time = time.monotonic()
    masked_email = email
    if "@" in email:
        local, domain = email.split("@", 1)
        masked_local = (local[:2] + "***") if local else "***"
        masked_email = f"{masked_local}@{domain}"
    try:
        logger.info(
            "authn.email.send_otp.start purpose=%s recipient=%s timeout=%s backend=%s",
            purpose,
            masked_email,
            getattr(settings, "EMAIL_TIMEOUT", None),
            getattr(settings, "EMAIL_BACKEND", ""),
        )
        text_message = "\n".join(
            [
                "Hello,",
                "",
                purpose_line,
                f"Your code is: {code}",
                f"This code expires in {expires_minutes} minutes.",
                "",
                "If you did not request this, you can ignore this message.",
                f"Support: {support_email}",
            ]
        )
        html_message = _build_otp_email_html(
            purpose_line=purpose_line,
            code=code,
            expires_minutes=expires_minutes,
            support_email=support_email,
        )
        connection = get_connection(
            fail_silently=False,
            timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
        )
        email_message = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
            connection=connection,
        )
        email_message.attach_alternative(html_message, "text/html")
        email_message.send(fail_silently=False)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "authn.email.send_otp.success purpose=%s recipient=%s elapsed_ms=%s",
            purpose,
            masked_email,
            elapsed_ms,
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.exception(
            "authn.email.send_otp.failure purpose=%s recipient=%s elapsed_ms=%s error_type=%s",
            purpose,
            masked_email,
            elapsed_ms,
            type(exc).__name__,
        )
        raise EmailDeliveryError("Unable to send the verification code right now. Please try again.") from exc


def _build_otp_email_html(
    *,
    purpose_line: str,
    code: str,
    expires_minutes: int,
    support_email: str,
) -> str:
    logo_markup = _email_logo_markup()
    return f"""
<html>
  <body style="margin:0;padding:24px;background:{BRAND_PURPLE_10};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:{BRAND_DARK_GREY_100};">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid {BRAND_PURPLE_40};border-radius:16px;overflow:hidden;">
      <tr>
        <td style="background:{BRAND_PURPLE_70};padding:20px 24px;text-align:center;">
          {logo_markup}
        </td>
      </tr>
      <tr>
        <td style="padding:24px;">
          <p style="margin:0 0 12px;font-size:16px;font-weight:600;">Hello,</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.5;">{purpose_line}</p>
          <div style="margin:20px 0;padding:14px;border-radius:12px;background:{BRAND_PURPLE_10};border:1px solid {BRAND_PURPLE_30};text-align:center;">
            <div style="font-size:12px;color:#5E6470;letter-spacing:0.08em;text-transform:uppercase;">Your verification code</div>
            <div style="font-size:36px;line-height:1.15;font-weight:800;letter-spacing:0.2em;color:{BRAND_PURPLE_70};margin-top:6px;">{code}</div>
          </div>
          <p style="margin:0 0 10px;font-size:14px;color:#312C3B;">This code expires in <strong>{expires_minutes} minutes</strong>.</p>
          <p style="margin:0 0 16px;font-size:14px;color:#5E6470;">If you did not request this, you can safely ignore this email.</p>
          <div style="margin-top:18px;padding-top:14px;border-top:1px solid #E5E7EB;font-size:13px;color:#5E6470;">
            Need help? <a href="mailto:{support_email}" style="color:{BRAND_ORANGE};text-decoration:none;font-weight:600;">{support_email}</a>
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


def _email_logo_markup() -> str:
    logo_path = Path(settings.BASE_DIR).parent / "mobile" / "assets" / "images" / "logo" / "splash_logo.png"
    if not logo_path.exists():
        return '<div style="color:#FFFFFF;font-size:22px;font-weight:800;letter-spacing:0.02em;">iTestified</div>'

    try:
        encoded = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        return (
            f'<img src="data:image/png;base64,{encoded}" alt="iTestified" '
            'style="max-height:56px;width:auto;display:inline-block;" />'
        )
    except Exception:
        return '<div style="color:#FFFFFF;font-size:22px;font-weight:800;letter-spacing:0.02em;">iTestified</div>'


def _generate_temp_password(length: int = 20) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@transaction.atomic
def start_registration(*, full_name: str, email: str) -> EmailChallenge:
    if User.objects.filter(email__iexact=email).exists():
        raise AuthnError("An account with this email already exists.")

    EmailChallenge.objects.filter(
        email__iexact=email,
        purpose=ChallengePurpose.REGISTRATION,
        consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())

    challenge = EmailChallenge.objects.create(
        email=email.lower(),
        purpose=ChallengePurpose.REGISTRATION,
        full_name=full_name.strip(),
        code=_generate_otp(),
        expires_at=_challenge_expiry(),
    )
    _send_otp_email(email=challenge.email, purpose=challenge.purpose, code=challenge.code)
    return challenge


@transaction.atomic
def verify_registration(*, email: str, otp: str) -> EmailChallenge:
    challenge = _get_latest_challenge(email, ChallengePurpose.REGISTRATION, for_update=True)
    if challenge is None:
        raise ChallengeVerificationError("No registration challenge was found for this email.")
    if challenge.is_expired:
        raise ChallengeVerificationError("This registration code has expired.")
    if challenge.code != otp:
        raise ChallengeVerificationError("Incorrect OTP.")

    if challenge.verified_at is None:
        challenge.verified_at = timezone.now()
        challenge.save(update_fields=["verified_at", "updated_at"])

    return challenge


@transaction.atomic
def complete_registration(*, email: str, password: str) -> tuple[User, Token]:
    challenge = _get_latest_challenge(email, ChallengePurpose.REGISTRATION, for_update=True)
    if challenge is None or challenge.verified_at is None:
        raise AuthnError("Registration must be verified before completion.")
    if challenge.is_expired:
        raise AuthnError("This registration code has expired.")

    validate_user_password(password)
    try:
        user = User.objects.create_user(email=email.lower(), password=password)
    except IntegrityError as exc:
        raise AuthnError("An account with this email already exists.") from exc
    Profile.objects.create(user=user, full_name=challenge.full_name)
    token, _ = Token.objects.get_or_create(user=user)
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at", "updated_at"])
    update_last_login(sender=User, user=user)
    return user, token


def login_mobile_user(*, email: str, password: str) -> tuple[User, Token]:
    user = authenticate(email=email, password=password)
    if user is None:
        raise AuthnError("Invalid email or password.")

    ensure_active_user(user)
    token, _ = Token.objects.get_or_create(user=user)
    update_last_login(sender=User, user=user)
    return user, token


def _verify_google_id_token_payload(*, id_token: str) -> dict:
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except Exception as exc:
        raise AuthnError(
            "Google sign-in server dependency is missing. Install 'google-auth' in the active backend environment."
        ) from exc

    try:
        payload = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            audience=None,
        )
    except Exception as exc:
        raise AuthnError("Invalid Google sign-in token.") from exc

    return payload


@transaction.atomic
def login_mobile_user_with_google(*, id_token: str, platform: Optional[str] = None) -> tuple[User, Token, bool]:
    if not settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise AuthnError(
            "Google sign-in is not configured: GOOGLE_OAUTH_CLIENT_IDS is empty for this running backend process."
        )

    payload = _verify_google_id_token_payload(id_token=id_token)
    audience = str(payload.get("aud", "")).strip()
    issuer = str(payload.get("iss", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    email_verified = payload.get("email_verified")
    full_name = str(payload.get("name", "")).strip()

    if audience not in settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise AuthnError("Google token audience is not allowed.")
    if issuer not in settings.GOOGLE_OAUTH_ALLOWED_ISSUERS:
        raise AuthnError("Google token issuer is not allowed.")
    if not email:
        raise AuthnError("Google account email is missing.")
    if email_verified not in (True, "true", "True", 1):
        raise AuthnError("Google account email is not verified.")

    user = User.objects.filter(email__iexact=email).first()
    is_new_user = user is None

    if user is None:
        user = User.objects.create_user(email=email, password=None)
        user.set_unusable_password()
        user.save(update_fields=["password"])
        Profile.objects.create(
            user=user,
            full_name=(full_name if full_name else email.split("@")[0].replace(".", " ").title()),
        )
    else:
        if not hasattr(user, "profile"):
            Profile.objects.create(
                user=user,
                full_name=(full_name if full_name else email.split("@")[0].replace(".", " ").title()),
            )
        elif full_name and not user.profile.full_name.strip():
            user.profile.full_name = full_name
            user.profile.save(update_fields=["full_name", "updated_at"])

    ensure_active_user(user)
    token, _ = Token.objects.get_or_create(user=user)
    update_last_login(sender=User, user=user)
    return user, token, is_new_user


@transaction.atomic
def start_password_reset(*, email: str) -> Optional[EmailChallenge]:
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        return None

    EmailChallenge.objects.filter(
        email__iexact=email,
        purpose=ChallengePurpose.PASSWORD_RESET,
        consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())

    challenge = EmailChallenge.objects.create(
        email=email.lower(),
        purpose=ChallengePurpose.PASSWORD_RESET,
        code=_generate_otp(),
        expires_at=_challenge_expiry(),
    )
    _send_otp_email(email=challenge.email, purpose=challenge.purpose, code=challenge.code)
    return challenge


@transaction.atomic
def verify_password_reset(*, email: str, otp: str) -> EmailChallenge:
    challenge = _get_latest_challenge(email, ChallengePurpose.PASSWORD_RESET, for_update=True)
    if challenge is None:
        raise ChallengeVerificationError("No password reset challenge was found for this email.")
    if challenge.is_expired:
        raise ChallengeVerificationError("This password reset code has expired.")
    if challenge.code != otp:
        raise ChallengeVerificationError("Invalid code.")

    if challenge.verified_at is None:
        challenge.verified_at = timezone.now()
        challenge.save(update_fields=["verified_at", "updated_at"])

    return challenge


@transaction.atomic
def complete_password_reset(*, email: str, password: str) -> User:
    challenge = _get_latest_challenge(email, ChallengePurpose.PASSWORD_RESET, for_update=True)
    if challenge is None or challenge.verified_at is None:
        raise AuthnError("Password reset must be verified before completion.")
    if challenge.is_expired:
        raise AuthnError("This password reset code has expired.")

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise AuthnError("Account not found.")

    validate_user_password(password, user=user)
    user.set_password(password)
    user.save(update_fields=["password"])
    Token.objects.filter(user=user).delete()
    _invalidate_user_sessions(user)
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at", "updated_at"])
    return user


def _invalidate_user_sessions(user: User) -> None:
    from django.contrib.sessions.models import Session

    session_keys = list(UserSession.objects.filter(user=user).values_list("session_key", flat=True))
    if not session_keys:
        return
    Session.objects.filter(session_key__in=session_keys).delete()
    UserSession.objects.filter(user=user).delete()


@transaction.atomic
def bootstrap_super_admin(*, email: str, full_name: str = "") -> tuple[User, str]:
    temporary_password = _generate_temp_password()
    validate_user_password(temporary_password)
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.create_user(email=email.lower(), password=temporary_password, is_staff=True)
    else:
        user.set_password(temporary_password)
        user.is_staff = True
        user.save(update_fields=["password", "is_staff"])
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])

    if not hasattr(user, "profile"):
        Profile.objects.create(
            user=user,
            full_name=(full_name.strip() if full_name.strip() else email.split("@")[0].replace(".", " ").title()),
        )
    elif full_name.strip():
        user.profile.full_name = full_name.strip()
        user.profile.save(update_fields=["full_name", "updated_at"])

    role, _ = AdminRole.objects.get_or_create(
        code=AdminRoleCode.SUPER_ADMIN,
        defaults={"name": "Super Admin"},
    )
    assignment, created = AdminAssignment.objects.get_or_create(
        user=user,
        role=role,
        defaults={"status": AdminAssignmentStatus.ACTIVE, "activated_at": timezone.now()},
    )
    if not created and assignment.status != AdminAssignmentStatus.ACTIVE:
        assignment.status = AdminAssignmentStatus.ACTIVE
        assignment.activated_at = timezone.now()
        assignment.deactivated_at = None
        assignment.save(update_fields=["status", "activated_at", "deactivated_at", "updated_at"])

    return user, temporary_password


@transaction.atomic
def invite_admin_user(*, inviter: User, email: str, role_code: str) -> EmailChallenge:
    inviter_assignment = get_active_admin_assignment(inviter)
    if inviter_assignment is None or inviter_assignment.role.code != AdminRoleCode.SUPER_ADMIN:
        raise AuthnError("Only active super admins can invite admins.")

    if role_code == AdminRoleCode.SUPER_ADMIN:
        raise AuthnError("Super admin invitations are not allowed in this flow.")

    role = AdminRole.objects.filter(code=role_code).first()
    if role is None:
        raise AuthnError("Invalid admin role.")

    target_email = email.lower().strip()
    user = User.objects.filter(email__iexact=target_email).first()
    if user is None:
        user = User.objects.create_user(email=target_email, password=None, is_staff=True)
        user.set_unusable_password()
        user.save(update_fields=["password"])
        Profile.objects.create(user=user, full_name=target_email.split("@")[0].replace(".", " ").title())
    else:
        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        if not hasattr(user, "profile"):
            Profile.objects.create(user=user, full_name=target_email.split("@")[0].replace(".", " ").title())

    assignment, created = AdminAssignment.objects.get_or_create(
        user=user,
        role=role,
        defaults={
            "status": AdminAssignmentStatus.INVITED,
            "invited_by": inviter,
            "deactivated_at": None,
        },
    )
    if not created:
        assignment.status = AdminAssignmentStatus.INVITED
        assignment.invited_by = inviter
        assignment.deactivated_at = None
        assignment.save(update_fields=["status", "invited_by", "deactivated_at", "updated_at"])

    EmailChallenge.objects.filter(
        email__iexact=target_email,
        purpose=ChallengePurpose.ADMIN_INVITE,
        consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())

    challenge = EmailChallenge.objects.create(
        email=target_email,
        purpose=ChallengePurpose.ADMIN_INVITE,
        code=_generate_otp(),
        expires_at=_challenge_expiry(),
    )
    _send_otp_email(email=challenge.email, purpose=challenge.purpose, code=challenge.code)
    return challenge


@transaction.atomic
def verify_admin_invite(*, email: str, otp: str) -> EmailChallenge:
    challenge = _get_latest_challenge(email, ChallengePurpose.ADMIN_INVITE, for_update=True)
    if challenge is None:
        raise ChallengeVerificationError("No admin invitation was found for this email.")
    if challenge.is_expired:
        raise ChallengeVerificationError("This invitation code has expired.")
    if challenge.code != otp:
        raise ChallengeVerificationError("Invalid code.")

    if challenge.verified_at is None:
        challenge.verified_at = timezone.now()
        challenge.save(update_fields=["verified_at", "updated_at"])
    return challenge


@transaction.atomic
def complete_admin_invite(*, email: str, password: str) -> User:
    challenge = _get_latest_challenge(email, ChallengePurpose.ADMIN_INVITE, for_update=True)
    if challenge is None or challenge.verified_at is None:
        raise AuthnError("Invitation must be verified before completion.")
    if challenge.is_expired:
        raise AuthnError("This invitation code has expired.")

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise AuthnError("Account not found.")

    invited_assignments = AdminAssignment.objects.filter(
        user=user,
        status=AdminAssignmentStatus.INVITED,
    ).select_for_update()
    if not invited_assignments.exists():
        raise AuthnError("No pending admin invitation was found.")

    validate_user_password(password, user=user)
    user.set_password(password)
    user.is_staff = True
    user.must_change_password = False
    user.save(update_fields=["password", "is_staff", "must_change_password"])

    now = timezone.now()
    invited_assignments.update(
        status=AdminAssignmentStatus.ACTIVE,
        activated_at=now,
        deactivated_at=None,
        updated_at=now,
    )

    challenge.consumed_at = now
    challenge.save(update_fields=["consumed_at", "updated_at"])
    return user


@transaction.atomic
def change_temporary_admin_password(*, user: User, current_password: str, new_password: str) -> User:
    if not check_password(current_password, user.password):
        raise AuthnError("Current password is incorrect.")

    validate_user_password(new_password, user=user)
    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])
    return user


def login_admin_user(*, email: str, password: str) -> tuple[User, AdminAssignment]:
    user = authenticate(email=email, password=password)
    if user is None:
        raise AuthnError("Invalid email or password.")

    ensure_active_user(user)
    assignment = get_active_admin_assignment(user)
    ensure_active_admin_assignment(assignment)
    update_last_login(sender=User, user=user)
    return user, assignment
