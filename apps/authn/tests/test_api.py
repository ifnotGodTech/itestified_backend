from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.test.client import Client
from rest_framework.authtoken.models import Token

from apps.users.choices import AdminRoleCode
from apps.users.models import AdminRole, Profile
from apps.authn.exceptions import AuthnError
from apps.authn.models import UserSession
from apps.users.tests.factories import UserFactory
from apps.authn.services.commands import bootstrap_super_admin


class AuthnApiTests(TestCase):
    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_mobile_registration_and_login_flow(self) -> None:
        start_response = self.client.post(
            reverse("auth-mobile-register-start"),
            {"full_name": "Grace User", "email": "grace@example.com"},
            content_type="application/json",
        )
        self.assertEqual(start_response.status_code, 201)
        otp = start_response.json()["otp_hint"]

        verify_response = self.client.post(
            reverse("auth-mobile-register-verify"),
            {"email": "grace@example.com", "otp": otp},
            content_type="application/json",
        )
        self.assertEqual(verify_response.status_code, 200)

        complete_response = self.client.post(
            reverse("auth-mobile-register-complete"),
            {"email": "grace@example.com", "password": "StrongPass!1"},
            content_type="application/json",
        )
        self.assertEqual(complete_response.status_code, 201)
        self.assertIn("token", complete_response.json())

        login_response = self.client.post(
            reverse("auth-mobile-login"),
            {"email": "grace@example.com", "password": "StrongPass!1"},
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("token", login_response.json())

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_mobile_registration_normalizes_full_name_casing(self) -> None:
        start_response = self.client.post(
            reverse("auth-mobile-register-start"),
            {"full_name": "AIGUOSATILE AISOSA", "email": "aiguosatile@example.com"},
            content_type="application/json",
        )
        otp = start_response.json()["otp_hint"]

        self.client.post(
            reverse("auth-mobile-register-verify"),
            {"email": "aiguosatile@example.com", "otp": otp},
            content_type="application/json",
        )
        self.client.post(
            reverse("auth-mobile-register-complete"),
            {"email": "aiguosatile@example.com", "password": "StrongPass!1"},
            content_type="application/json",
        )

        profile = Profile.objects.get(user__email="aiguosatile@example.com")
        self.assertEqual(profile.full_name, "Aiguosatile Aisosa")

    def test_super_admin_login_and_session_flow(self) -> None:
        _user, temporary_password = bootstrap_super_admin(email="admin@example.com", full_name="Admin One")

        login_response = self.client.post(
            reverse("auth-admin-login"),
            {"email": "admin@example.com", "password": temporary_password},
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["role"], "admin")
        self.assertTrue(login_response.json()["must_change_password"])

        session_response = self.client.get(reverse("auth-admin-session"))
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["email"], "admin@example.com")
        self.assertEqual(session_response.json()["role_code"], AdminRoleCode.SUPER_ADMIN)
        self.assertEqual(session_response.json()["role_label"], "Super Admin")
        self.assertTrue(session_response.json()["must_change_password"])
        self.assertTrue(UserSession.objects.filter(user__email="admin@example.com").exists())

    @override_settings(
        GOOGLE_OAUTH_CLIENT_IDS=["android-client-id.apps.googleusercontent.com"],
        GOOGLE_OAUTH_ALLOWED_ISSUERS=["https://accounts.google.com", "accounts.google.com"],
    )
    @patch("apps.authn.services.commands._verify_google_id_token_payload")
    def test_mobile_google_sign_in_returns_token(self, mock_verify) -> None:
        mock_verify.return_value = {
            "aud": "android-client-id.apps.googleusercontent.com",
            "iss": "https://accounts.google.com",
            "email": "mobile-google@example.com",
            "email_verified": True,
            "name": "Mobile Google",
        }

        response = self.client.post(
            reverse("auth-mobile-google"),
            {"id_token": "valid-token", "platform": "android"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("token", body)
        self.assertEqual(body["user"]["email"], "mobile-google@example.com")
        self.assertIn("phone_number", body["user"])
        self.assertIn("avatar_url", body["user"])
        self.assertTrue(body["is_new_user"])

    @override_settings(
        GOOGLE_OAUTH_CLIENT_IDS=["android-client-id.apps.googleusercontent.com"],
        GOOGLE_OAUTH_ALLOWED_ISSUERS=["https://accounts.google.com", "accounts.google.com"],
    )
    @patch("apps.authn.services.commands._verify_google_id_token_payload")
    def test_mobile_google_sign_in_normalizes_full_name_casing(self, mock_verify) -> None:
        mock_verify.return_value = {
            "aud": "android-client-id.apps.googleusercontent.com",
            "iss": "https://accounts.google.com",
            "email": "google-caps@example.com",
            "email_verified": True,
            "name": "JOHN DOE",
        }

        response = self.client.post(
            reverse("auth-mobile-google"),
            {"id_token": "valid-token", "platform": "android"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        profile = Profile.objects.get(user__email="google-caps@example.com")
        self.assertEqual(profile.full_name, "John Doe")

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_admin_invitation_requires_csrf_token(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        inviter, temporary_password = bootstrap_super_admin(email="csrf-super@example.com", full_name="CSRF Super")
        login_response = csrf_client.post(
            reverse("auth-admin-login"),
            {"email": inviter.email, "password": temporary_password},
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)
        AdminRole.objects.get_or_create(code=AdminRoleCode.MODERATOR, defaults={"name": "Moderator"})

        no_csrf_response = csrf_client.post(
            reverse("auth-admin-invitations"),
            {"email": "csrfmod@example.com", "role_code": AdminRoleCode.MODERATOR},
            content_type="application/json",
        )
        self.assertEqual(no_csrf_response.status_code, 403)

        csrf_token = csrf_client.cookies.get("csrftoken")
        self.assertIsNotNone(csrf_token)
        with_csrf_response = csrf_client.post(
            reverse("auth-admin-invitations"),
            {"email": "csrfmod@example.com", "role_code": AdminRoleCode.MODERATOR},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token.value,
        )
        self.assertEqual(with_csrf_response.status_code, 201)

    @override_settings(GOOGLE_OAUTH_CLIENT_IDS=[])
    def test_mobile_google_sign_in_returns_503_when_not_configured(self) -> None:
        response = self.client.post(
            reverse("auth-mobile-google"),
            {"id_token": "valid-token", "platform": "android"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)

    @override_settings(
        GOOGLE_OAUTH_CLIENT_IDS=["android-client-id.apps.googleusercontent.com"],
        GOOGLE_OAUTH_ALLOWED_ISSUERS=["https://accounts.google.com", "accounts.google.com"],
    )
    @patch(
        "apps.authn.services.commands._verify_google_id_token_payload",
        side_effect=AuthnError("Invalid Google sign-in token."),
    )
    def test_mobile_google_sign_in_rejects_invalid_token(self, _mock_verify) -> None:
        response = self.client.post(
            reverse("auth-mobile-google"),
            {"id_token": "invalid-token", "platform": "android"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_super_admin_can_change_temporary_password(self) -> None:
        _user, temporary_password = bootstrap_super_admin(email="admin-change@example.com", full_name="Admin Change")
        self.client.post(
            reverse("auth-admin-login"),
            {"email": "admin-change@example.com", "password": temporary_password},
            content_type="application/json",
        )

        response = self.client.post(
            reverse("auth-admin-change-temporary-password"),
            {
                "current_password": temporary_password,
                "new_password": "NewStrongPass!2",
                "confirm_new_password": "NewStrongPass!2",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["must_change_password"])

    def test_change_password_requires_authentication(self) -> None:
        response = self.client.post(
            reverse("auth-mobile-change-password"),
            {
                "current_password": "StrongPass!1",
                "new_password": "NewStrongPass!2",
                "confirm_new_password": "NewStrongPass!2",
            },
            content_type="application/json",
        )
        # SessionAuthentication is listed before TokenAuthentication in
        # DEFAULT_AUTHENTICATION_CLASSES, and DRF only consults the first
        # authenticator's authenticate_header() (which SessionAuthentication
        # doesn't provide) when deciding between 401 and 403 -- so a denied
        # request comes back 403 here, not 401, matching this project's
        # existing behavior on every other IsAuthenticated-only endpoint.
        self.assertEqual(response.status_code, 403)

    def test_change_password_succeeds_and_rotates_the_token(self) -> None:
        user = UserFactory(email="change-password@example.com")
        old_token = Token.objects.create(user=user)

        response = self.client.post(
            reverse("auth-mobile-change-password"),
            {
                "current_password": "StrongPass!1",
                "new_password": "NewStrongPass!2",
                "confirm_new_password": "NewStrongPass!2",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {old_token.key}",
        )

        self.assertEqual(response.status_code, 200)
        new_token_key = response.json()["token"]
        self.assertNotEqual(new_token_key, old_token.key)

        user.refresh_from_db()
        self.assertTrue(user.check_password("NewStrongPass!2"))

        # The old token must no longer authenticate anything (403 here for
        # the same reason as test_change_password_requires_authentication).
        stale_response = self.client.get(
            reverse("profile-me"),
            HTTP_AUTHORIZATION=f"Token {old_token.key}",
        )
        self.assertEqual(stale_response.status_code, 403)

        # The new token, returned in the response, must work.
        fresh_response = self.client.get(
            reverse("profile-me"),
            HTTP_AUTHORIZATION=f"Token {new_token_key}",
        )
        self.assertEqual(fresh_response.status_code, 200)

    def test_change_password_rejects_an_incorrect_current_password(self) -> None:
        user = UserFactory(email="change-password-wrong@example.com")
        token = Token.objects.create(user=user)

        response = self.client.post(
            reverse("auth-mobile-change-password"),
            {
                "current_password": "NotTheRealPassword",
                "new_password": "NewStrongPass!2",
                "confirm_new_password": "NewStrongPass!2",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password("StrongPass!1"))

    def test_change_password_rejects_a_mismatched_confirmation(self) -> None:
        user = UserFactory(email="change-password-mismatch@example.com")
        token = Token.objects.create(user=user)

        response = self.client.post(
            reverse("auth-mobile-change-password"),
            {
                "current_password": "StrongPass!1",
                "new_password": "NewStrongPass!2",
                "confirm_new_password": "SomethingElse!3",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 400)

    def test_change_password_rejects_a_password_that_fails_validators(self) -> None:
        user = UserFactory(email="change-password-weak@example.com")
        token = Token.objects.create(user=user)

        response = self.client.post(
            reverse("auth-mobile-change-password"),
            {
                "current_password": "StrongPass!1",
                "new_password": "short",
                "confirm_new_password": "short",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password("StrongPass!1"))

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_super_admin_can_invite_admin_role(self) -> None:
        inviter, temporary_password = bootstrap_super_admin(email="super@example.com", full_name="Super One")
        self.client.post(
            reverse("auth-admin-login"),
            {"email": inviter.email, "password": temporary_password},
            content_type="application/json",
        )
        AdminRole.objects.get_or_create(code=AdminRoleCode.MODERATOR, defaults={"name": "Moderator"})

        response = self.client.post(
            reverse("auth-admin-invitations"),
            {"email": "mod@example.com", "role_code": AdminRoleCode.MODERATOR},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["email"], "mod@example.com")
        self.assertIn("otp_hint", response.json())

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_invited_admin_can_verify_and_complete_invitation(self) -> None:
        inviter, temporary_password = bootstrap_super_admin(email="super2@example.com", full_name="Super Two")
        self.client.post(
            reverse("auth-admin-login"),
            {"email": inviter.email, "password": temporary_password},
            content_type="application/json",
        )
        AdminRole.objects.get_or_create(code=AdminRoleCode.MODERATOR, defaults={"name": "Moderator"})
        invite_response = self.client.post(
            reverse("auth-admin-invitations"),
            {"email": "invitee@example.com", "role_code": AdminRoleCode.MODERATOR},
            content_type="application/json",
        )
        otp = invite_response.json()["otp_hint"]
        self.client.post(reverse("auth-admin-logout"))

        verify_response = self.client.post(
            reverse("auth-admin-invite-verify"),
            {"email": "invitee@example.com", "otp": otp},
            content_type="application/json",
        )
        self.assertEqual(verify_response.status_code, 200)

        complete_response = self.client.post(
            reverse("auth-admin-invite-complete"),
            {"email": "invitee@example.com", "password": "StrongPass!1"},
            content_type="application/json",
        )
        self.assertEqual(complete_response.status_code, 201)
        self.assertEqual(complete_response.json()["role"], "admin")

        session_response = self.client.get(reverse("auth-admin-session"))
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["email"], "invitee@example.com")

    @override_settings(OTP_HINT_IN_RESPONSE=False)
    def test_registration_start_does_not_expose_otp_hint_when_disabled(self) -> None:
        response = self.client.post(
            reverse("auth-mobile-register-start"),
            {"full_name": "Grace User", "email": "grace-no-hint@example.com"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("otp_hint", response.json())

    @override_settings(OTP_HINT_IN_RESPONSE=False)
    def test_password_reset_request_does_not_expose_otp_hint_when_disabled(self) -> None:
        UserFactory(email="grace-existing-no-hint@example.com")

        response = self.client.post(
            reverse("auth-mobile-password-reset-request"),
            {"email": "grace-existing-no-hint@example.com"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("otp_hint", response.json())

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_password_reset_request_unknown_email_keeps_generic_response_and_no_hint(self) -> None:
        response = self.client.post(
            reverse("auth-mobile-password-reset-request"),
            {"email": "unknown-reset@example.com"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["message"], "If the email exists, a reset code has been sent.")
        self.assertNotIn("otp_hint", body)
        self.assertNotIn("email", body)

    @patch("apps.common.services.email.EmailMultiAlternatives.send", side_effect=Exception("smtp down"))
    def test_registration_start_returns_503_when_email_delivery_fails(self, _mock_send_mail) -> None:
        response = self.client.post(
            reverse("auth-mobile-register-start"),
            {"full_name": "Grace User", "email": "grace-mail-fail@example.com"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("Unable to send the verification code right now.", response.json()["message"])
        self.assertEqual(response.json()["error"]["code"], "email_delivery_failed")

    def test_login_validation_error_uses_unified_error_envelope(self) -> None:
        response = self.client.post(
            reverse("auth-mobile-login"),
            {},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["message"], "Invalid input.")
        self.assertEqual(body["error"]["code"], "validation_error")
        self.assertIn("email", body["error"]["details"])

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_mobile_password_reset_verify_succeeds_for_valid_code(self) -> None:
        user = UserFactory(email="mobile-verify-ok@example.com")
        request_response = self.client.post(
            reverse("auth-mobile-password-reset-request"),
            {"email": user.email},
            content_type="application/json",
        )
        self.assertEqual(request_response.status_code, 200)
        otp = request_response.json()["otp_hint"]

        verify_response = self.client.post(
            reverse("auth-mobile-password-reset-verify"),
            {"email": user.email, "otp": otp},
            content_type="application/json",
        )
        self.assertEqual(verify_response.status_code, 200)
        self.assertEqual(verify_response.json()["message"], "Password reset OTP verified.")
        self.assertEqual(verify_response.json()["email"], user.email)

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_mobile_password_reset_verify_rejects_wrong_code(self) -> None:
        user = UserFactory(email="mobile-verify-wrong@example.com")
        self.client.post(
            reverse("auth-mobile-password-reset-request"),
            {"email": user.email},
            content_type="application/json",
        )

        response = self.client.post(
            reverse("auth-mobile-password-reset-verify"),
            {"email": user.email, "otp": "000000"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "challenge_verification_failed")
        self.assertIn("Invalid code.", body["message"])

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_mobile_password_reset_verify_rejects_expired_code(self) -> None:
        user = UserFactory(email="mobile-verify-expired@example.com")
        request_response = self.client.post(
            reverse("auth-mobile-password-reset-request"),
            {"email": user.email},
            content_type="application/json",
        )
        self.assertEqual(request_response.status_code, 200)
        otp = request_response.json()["otp_hint"]

        from apps.authn.choices import ChallengePurpose
        from apps.authn.models import EmailChallenge
        from django.utils import timezone

        EmailChallenge.objects.filter(
            email=user.email,
            purpose=ChallengePurpose.PASSWORD_RESET,
            consumed_at__isnull=True,
        ).update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

        response = self.client.post(
            reverse("auth-mobile-password-reset-verify"),
            {"email": user.email, "otp": otp},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "challenge_verification_failed")
        self.assertIn("expired", body["message"].lower())

    def test_mobile_password_reset_verify_rejects_when_no_challenge_exists(self) -> None:
        response = self.client.post(
            reverse("auth-mobile-password-reset-verify"),
            {"email": "no-challenge@example.com", "otp": "123456"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "challenge_verification_failed")
        self.assertIn("No password reset challenge was found", body["message"])

    @patch("apps.authn.services.commands._build_otp_email_html")
    def test_mobile_password_reset_request_returns_503_when_email_template_build_fails(self, mock_build_html) -> None:
        user = UserFactory(email="mobile-reset-template-fail@example.com")
        mock_build_html.side_effect = RuntimeError("template failure")

        response = self.client.post(
            reverse("auth-mobile-password-reset-request"),
            {"email": user.email},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["code"], "email_delivery_failed")
        self.assertIn("Unable to send the verification code right now", body["message"])

    @patch("apps.authn.api.views.start_password_reset")
    def test_mobile_password_reset_request_handles_unexpected_service_failure(self, mock_start_password_reset) -> None:
        mock_start_password_reset.side_effect = RuntimeError("unexpected failure")

        response = self.client.post(
            reverse("auth-mobile-password-reset-request"),
            {"email": "mobile-reset-unexpected@example.com"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["code"], "password_reset_unavailable")

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_admin_password_reset_verify_and_complete_flow(self) -> None:
        user = UserFactory(email="admin-reset@example.com")
        request_response = self.client.post(
            reverse("auth-admin-forgot-password"),
            {"email": user.email},
            content_type="application/json",
        )
        self.assertEqual(request_response.status_code, 200)
        otp = request_response.json()["otp_hint"]

        verify_response = self.client.post(
            reverse("auth-admin-password-reset-verify"),
            {"email": user.email, "otp": otp},
            content_type="application/json",
        )
        self.assertEqual(verify_response.status_code, 200)

        complete_response = self.client.post(
            reverse("auth-admin-password-reset-complete"),
            {"email": user.email, "password": "NewStrongPass!2"},
            content_type="application/json",
        )
        self.assertEqual(complete_response.status_code, 200)

    @override_settings(OTP_HINT_IN_RESPONSE=True)
    def test_admin_invite_requires_csrf_token_for_session_post(self) -> None:
        client = Client(enforce_csrf_checks=True)
        inviter, temporary_password = bootstrap_super_admin(email="csrf-super@example.com", full_name="Csrf Super")
        login_response = client.post(
            reverse("auth-admin-login"),
            {"email": inviter.email, "password": temporary_password},
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)
        AdminRole.objects.get_or_create(code=AdminRoleCode.MODERATOR, defaults={"name": "Moderator"})

        invite_response = client.post(
            reverse("auth-admin-invitations"),
            {"email": "csrf-invitee@example.com", "role_code": AdminRoleCode.MODERATOR},
            content_type="application/json",
        )
        self.assertEqual(invite_response.status_code, 403)

        csrf_token = client.cookies.get("csrftoken")
        self.assertIsNotNone(csrf_token)
        invite_with_csrf_response = client.post(
            reverse("auth-admin-invitations"),
            {"email": "csrf-invitee@example.com", "role_code": AdminRoleCode.MODERATOR},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token.value,
        )
        self.assertEqual(invite_with_csrf_response.status_code, 201)

    def test_change_temporary_password_requires_csrf_token_for_session_post(self) -> None:
        client = Client(enforce_csrf_checks=True)
        _user, temporary_password = bootstrap_super_admin(email="csrf-change@example.com", full_name="Csrf Change")
        login_response = client.post(
            reverse("auth-admin-login"),
            {"email": "csrf-change@example.com", "password": temporary_password},
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)

        response = client.post(
            reverse("auth-admin-change-temporary-password"),
            {
                "current_password": temporary_password,
                "new_password": "NewStrongPass!2",
                "confirm_new_password": "NewStrongPass!2",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        csrf_token = client.cookies.get("csrftoken")
        self.assertIsNotNone(csrf_token)
        response_with_csrf = client.post(
            reverse("auth-admin-change-temporary-password"),
            {
                "current_password": temporary_password,
                "new_password": "NewStrongPass!2",
                "confirm_new_password": "NewStrongPass!2",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token.value,
        )
        self.assertEqual(response_with_csrf.status_code, 200)
