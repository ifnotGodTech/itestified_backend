from importlib import import_module

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from django.core import mail
from django.test import override_settings
from django.contrib.sessions.models import Session
from unittest.mock import Mock, patch
from django.db import IntegrityError

from apps.authn.exceptions import AuthnError, EmailDeliveryError
from apps.authn.models import EmailChallenge, UserSession
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
    def test_google_mobile_login_uses_existing_username_identity(self, mock_verify) -> None:
        existing = UserFactory(email="legacy@example.com", username="google-legacy@example.com")
        mock_verify.return_value = {
            "aud": "android-client-id.apps.googleusercontent.com",
            "iss": "accounts.google.com",
            "email": "google-legacy@example.com",
            "email_verified": True,
            "name": "Legacy User",
        }

        user, _token, is_new_user = login_mobile_user_with_google(id_token="valid-token", platform="android")

        self.assertFalse(is_new_user)
        self.assertEqual(user.pk, existing.pk)
        user.refresh_from_db()
        self.assertEqual(user.email, "google-legacy@example.com")
        self.assertEqual(user.username, "google-legacy@example.com")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_IDS=["android-client-id.apps.googleusercontent.com"],
        GOOGLE_OAUTH_ALLOWED_ISSUERS=["https://accounts.google.com", "accounts.google.com"],
    )
    @patch("apps.authn.services.commands._find_user_by_email_identity")
    @patch("apps.authn.services.commands.User.objects.create_user")
    @patch("apps.authn.services.commands._verify_google_id_token_payload")
    def test_google_mobile_login_recovers_from_duplicate_create_race(
        self,
        mock_verify,
        mock_create_user,
        mock_find_user_by_email_identity,
    ) -> None:
        existing = UserFactory(email="google-race@example.com")
        mock_find_user_by_email_identity.side_effect = [None, existing]
        mock_verify.return_value = {
            "aud": "android-client-id.apps.googleusercontent.com",
            "iss": "accounts.google.com",
            "email": "google-race@example.com",
            "email_verified": True,
            "name": "Race User",
        }
        mock_create_user.side_effect = IntegrityError("duplicate key value violates unique constraint")

        user, _token, is_new_user = login_mobile_user_with_google(id_token="valid-token", platform="android")

        self.assertFalse(is_new_user)
        self.assertEqual(user.pk, existing.pk)

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

    def test_complete_password_reset_invalidates_tracked_sessions_without_full_scan(self) -> None:
        user = UserFactory(email="reset-sessions@example.com")
        challenge = start_password_reset(email=user.email)
        verify_password_reset(email=user.email, otp=challenge.code)

        session_store = import_module(settings.SESSION_ENGINE).SessionStore()
        session_store["_auth_user_id"] = str(user.pk)
        session_store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        session_store.save()
        self.assertTrue(Session.objects.filter(session_key=session_store.session_key).exists())
        UserSession.objects.create(user=user, session_key=session_store.session_key)

        complete_password_reset(email=user.email, password="NewStrongPass!2")

        self.assertFalse(Session.objects.filter(session_key=session_store.session_key).exists())
        self.assertFalse(UserSession.objects.filter(user=user).exists())

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

    @override_settings(
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test",
        RESEND_FROM_EMAIL="iTestified <onboarding@example.com>",
        DEFAULT_FROM_EMAIL="iTestified <no-reply@example.com>",
    )
    @patch("apps.authn.services.commands.requests.post")
    def test_start_password_reset_can_send_email_with_resend_provider(self, mock_post) -> None:
        user = UserFactory(email="resend-reset@example.com")
        response = Mock()
        response.raise_for_status.return_value = None
        mock_post.return_value = response

        challenge = start_password_reset(email=user.email)

        self.assertIsNotNone(challenge)
        mock_post.assert_called_once()
        _url, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer re_test")
        self.assertEqual(kwargs["json"]["from"], "iTestified <onboarding@example.com>")
        self.assertEqual(kwargs["json"]["to"], [user.email])
        self.assertIn(challenge.code, kwargs["json"]["text"])

    @override_settings(
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test",
        RESEND_FROM_EMAIL="iTestified <onboarding@example.com>",
    )
    @patch("apps.authn.services.commands.requests.post")
    def test_start_password_reset_raises_delivery_error_when_resend_fails(self, mock_post) -> None:
        user = UserFactory(email="resend-failure@example.com")
        response = Mock()
        response.raise_for_status.side_effect = RuntimeError("resend failed")
        mock_post.return_value = response

        with self.assertRaises(EmailDeliveryError):
            start_password_reset(email=user.email)
