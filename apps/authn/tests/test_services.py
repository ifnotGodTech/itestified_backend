from django.test import TestCase
from django.utils import timezone
from django.core import mail
from django.test import override_settings
from unittest.mock import patch

from apps.authn.exceptions import AuthnError
from apps.authn.models import EmailChallenge
from apps.authn.services.commands import (
    bootstrap_super_admin,
    change_temporary_admin_password,
    complete_password_reset,
    complete_admin_invite,
    complete_registration,
    invite_admin_user,
    login_mobile_user,
    login_mobile_user_with_google,
    start_password_reset,
    start_registration,
    verify_admin_invite,
    verify_password_reset,
    verify_registration,
)
from apps.authn.choices import ChallengePurpose
from apps.users.choices import AdminAssignmentStatus, AdminRoleCode
from apps.users.models import AdminAssignment, AdminRole
from apps.users.tests.factories import UserFactory


class AuthnServiceTests(TestCase):
    def test_registration_flow_creates_user_profile_and_token(self) -> None:
        challenge = start_registration(full_name="Grace User", email="grace@example.com")
        verify_registration(email=challenge.email, otp=challenge.code)
        user, token = complete_registration(email=challenge.email, password="StrongPass!1")

        self.assertEqual(user.email, "grace@example.com")
        self.assertEqual(user.profile.full_name, "Grace User")
        self.assertTrue(bool(token.key))

    def test_mobile_login_returns_existing_token(self) -> None:
        challenge = start_registration(full_name="Grace User", email="grace@example.com")
        verify_registration(email=challenge.email, otp=challenge.code)
        complete_registration(email=challenge.email, password="StrongPass!1")

        user, token = login_mobile_user(email="grace@example.com", password="StrongPass!1")
        self.assertEqual(user.email, "grace@example.com")
        self.assertTrue(bool(token.key))

    @override_settings(
        GOOGLE_OAUTH_CLIENT_IDS=["android-client-id.apps.googleusercontent.com"],
        GOOGLE_OAUTH_ALLOWED_ISSUERS=["https://accounts.google.com", "accounts.google.com"],
    )
    @patch("apps.authn.services.commands._verify_google_id_token_payload")
    def test_google_mobile_login_creates_new_user(self, mock_verify) -> None:
        mock_verify.return_value = {
            "aud": "android-client-id.apps.googleusercontent.com",
            "iss": "https://accounts.google.com",
            "email": "google-new@example.com",
            "email_verified": True,
            "name": "Google New",
        }

        user, token, is_new_user = login_mobile_user_with_google(id_token="valid-token", platform="android")
        self.assertTrue(is_new_user)
        self.assertEqual(user.email, "google-new@example.com")
        self.assertEqual(user.profile.full_name, "Google New")
        self.assertTrue(bool(token.key))

    @override_settings(
        GOOGLE_OAUTH_CLIENT_IDS=["android-client-id.apps.googleusercontent.com"],
        GOOGLE_OAUTH_ALLOWED_ISSUERS=["https://accounts.google.com", "accounts.google.com"],
    )
    @patch("apps.authn.services.commands._verify_google_id_token_payload")
    def test_google_mobile_login_uses_existing_user(self, mock_verify) -> None:
        existing = UserFactory(email="google-existing@example.com")
        mock_verify.return_value = {
            "aud": "android-client-id.apps.googleusercontent.com",
            "iss": "accounts.google.com",
            "email": existing.email,
            "email_verified": True,
            "name": "Existing User",
        }

        user, token, is_new_user = login_mobile_user_with_google(id_token="valid-token", platform="android")
        self.assertFalse(is_new_user)
        self.assertEqual(user.pk, existing.pk)
        self.assertTrue(bool(token.key))

    @override_settings(
        GOOGLE_OAUTH_CLIENT_IDS=["android-client-id.apps.googleusercontent.com"],
        GOOGLE_OAUTH_ALLOWED_ISSUERS=["https://accounts.google.com", "accounts.google.com"],
    )
    @patch("apps.authn.services.commands._verify_google_id_token_payload")
    def test_google_mobile_login_rejects_wrong_audience(self, mock_verify) -> None:
        mock_verify.return_value = {
            "aud": "other-client-id.apps.googleusercontent.com",
            "iss": "https://accounts.google.com",
            "email": "wrong-aud@example.com",
            "email_verified": True,
        }

        with self.assertRaisesMessage(AuthnError, "Google token audience is not allowed."):
            login_mobile_user_with_google(id_token="valid-token", platform="android")

    def test_bootstrap_super_admin_creates_active_assignment(self) -> None:
        user, temporary_password = bootstrap_super_admin(
            email="admin@example.com",
            full_name="Admin One",
        )

        assignment = AdminAssignment.objects.get(user=user)
        self.assertEqual(assignment.status, AdminAssignmentStatus.ACTIVE)
        self.assertEqual(assignment.role.code, AdminRoleCode.SUPER_ADMIN)
        self.assertTrue(bool(temporary_password))
        self.assertTrue(user.must_change_password)

    def test_super_admin_can_invite_role_and_receive_invite_challenge(self) -> None:
        inviter, _temp_password = bootstrap_super_admin(email="admin@example.com", full_name="Admin One")
        role, _ = AdminRole.objects.get_or_create(code=AdminRoleCode.MODERATOR, defaults={"name": "Moderator"})

        challenge = invite_admin_user(
            inviter=inviter,
            email="moderator@example.com",
            role_code=role.code,
        )

        assignment = AdminAssignment.objects.get(user__email="moderator@example.com", role=role)
        self.assertEqual(assignment.status, AdminAssignmentStatus.INVITED)
        self.assertEqual(challenge.purpose, ChallengePurpose.ADMIN_INVITE)

    def test_invited_admin_can_verify_and_complete_invitation(self) -> None:
        inviter, _temp_password = bootstrap_super_admin(email="admin@example.com", full_name="Admin One")
        role, _ = AdminRole.objects.get_or_create(code=AdminRoleCode.MODERATOR, defaults={"name": "Moderator"})
        challenge = invite_admin_user(
            inviter=inviter,
            email="moderator@example.com",
            role_code=role.code,
        )

        verify_admin_invite(email=challenge.email, otp=challenge.code)
        user = complete_admin_invite(email=challenge.email, password="StrongPass!1")
        assignment = AdminAssignment.objects.get(user=user, role=role)

        self.assertEqual(assignment.status, AdminAssignmentStatus.ACTIVE)
        self.assertFalse(user.must_change_password)

    def test_change_temporary_password_clears_force_change_flag(self) -> None:
        user, temp_password = bootstrap_super_admin(email="admin-temp@example.com", full_name="Temp Admin")
        changed_user = change_temporary_admin_password(
            user=user,
            current_password=temp_password,
            new_password="NewStrongPass!2",
        )
        self.assertFalse(changed_user.must_change_password)

    def test_login_fails_for_deactivated_user(self) -> None:
        from apps.users.choices import UserAccountStatus

        user = UserFactory(account_status=UserAccountStatus.DEACTIVATED)

        with self.assertRaises(AuthnError):
            login_mobile_user(email=user.email, password="StrongPass!1")

    def test_complete_registration_fails_when_verified_challenge_expires(self) -> None:
        challenge = start_registration(full_name="Grace User", email="grace@example.com")
        verify_registration(email=challenge.email, otp=challenge.code)
        EmailChallenge.objects.filter(pk=challenge.pk).update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

        with self.assertRaisesMessage(AuthnError, "This registration code has expired."):
            complete_registration(email=challenge.email, password="StrongPass!1")

    def test_complete_password_reset_fails_when_verified_challenge_expires(self) -> None:
        user = UserFactory(email="grace@example.com")
        challenge = start_password_reset(email=user.email)
        verify_password_reset(email=user.email, otp=challenge.code)
        EmailChallenge.objects.filter(
            email=user.email,
            purpose=ChallengePurpose.PASSWORD_RESET,
            consumed_at__isnull=True,
        ).update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

        with self.assertRaisesMessage(AuthnError, "This password reset code has expired."):
            complete_password_reset(email=user.email, password="NewStrongPass!2")

    def test_start_registration_sends_otp_email(self) -> None:
        challenge = start_registration(full_name="Grace User", email="grace-mail@example.com")
        self.assertEqual(challenge.email, "grace-mail@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("iTestified verification code", mail.outbox[0].subject)
        self.assertIn(challenge.code, mail.outbox[0].body)
        self.assertGreater(len(mail.outbox[0].alternatives), 0)
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn(challenge.code, html_body)
        self.assertIn("#6E46FF", html_body)
        self.assertIn("iTestified", html_body)

    def test_start_password_reset_sends_otp_email_for_known_user_only(self) -> None:
        user = UserFactory(email="known-reset@example.com")

        challenge = start_password_reset(email=user.email)
        self.assertIsNotNone(challenge)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("iTestified password reset code", mail.outbox[0].subject)
        self.assertIn(challenge.code, mail.outbox[0].body)

        unknown = start_password_reset(email="unknown-reset@example.com")
        self.assertIsNone(unknown)
        self.assertEqual(len(mail.outbox), 1)
