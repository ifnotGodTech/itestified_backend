from django.conf import settings
from django.contrib.auth import login, logout, update_session_auth_hash
from rest_framework.authentication import SessionAuthentication
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from typing import Optional

from apps.users.selectors import get_active_admin_assignment

from ..exceptions import AuthnError, ChallengeVerificationError, EmailDeliveryError
from ..services.commands import (
    change_temporary_admin_password,
    complete_password_reset,
    complete_admin_invite,
    complete_registration,
    invite_admin_user,
    login_admin_user,
    login_mobile_user_with_google,
    login_mobile_user,
    start_password_reset,
    start_registration,
    verify_admin_invite,
    verify_password_reset,
    verify_registration,
)
from .permissions import IsActiveAdmin, IsSuperAdmin
from .serializers import (
    AdminInviteSerializer,
    AdminInviteCompleteSerializer,
    AdminInviteVerifySerializer,
    ChangeTemporaryPasswordSerializer,
    CompletePasswordResetSerializer,
    CompleteRegistrationSerializer,
    LoginSerializer,
    MobileGoogleSignInSerializer,
    PasswordResetRequestSerializer,
    StartRegistrationSerializer,
    VerifyCodeSerializer,
)


def _error_response(
    *,
    message: str,
    code: str,
    http_status: int,
    errors: Optional[dict] = None,
) -> Response:
    payload: dict = {
        "message": message,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if errors is not None:
        payload["error"]["details"] = errors
    return Response(payload, status=http_status)


class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return


class MobileRegistrationStartView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = StartRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            challenge = start_registration(**serializer.validated_data)
        except EmailDeliveryError as exc:
            return _error_response(
                message=str(exc),
                code="email_delivery_failed",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        response_data: dict = {
            "message": "Registration started successfully.",
            "email": challenge.email,
        }
        if getattr(settings, "OTP_HINT_IN_RESPONSE", False):
            response_data["otp_hint"] = challenge.code
        return Response(response_data, status=status.HTTP_201_CREATED)


class MobileRegistrationVerifyView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = VerifyCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            challenge = verify_registration(**serializer.validated_data)
        except ChallengeVerificationError as exc:
            return _error_response(
                message=str(exc),
                code="challenge_verification_failed",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"message": "Registration OTP verified.", "email": challenge.email})


class MobileRegistrationCompleteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = CompleteRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            user, token = complete_registration(**serializer.validated_data)
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Registration completed successfully.",
                "user": {
                    "email": user.email,
                    "full_name": user.profile.full_name,
                },
                "token": token.key,
            },
            status=status.HTTP_201_CREATED,
        )


class MobileLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            user, token = login_mobile_user(**serializer.validated_data)
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )

        profile = getattr(user, "profile", None)
        return Response(
            {
                "token": token.key,
                "user": {
                    "email": user.email,
                    "full_name": profile.full_name if profile else "",
                },
            }
        )


class MobileGoogleSignInView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = MobileGoogleSignInSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            user, token, is_new_user = login_mobile_user_with_google(**serializer.validated_data)
        except AuthnError as exc:
            message = str(exc)
            if "not configured" in message:
                http_status = status.HTTP_503_SERVICE_UNAVAILABLE
            elif "inactive" in message or "deactivated" in message or "suspended" in message:
                http_status = status.HTTP_403_FORBIDDEN
            else:
                http_status = status.HTTP_401_UNAUTHORIZED
            return _error_response(
                message=message,
                code="authn_error",
                http_status=http_status,
            )

        profile = getattr(user, "profile", None)
        return Response(
            {
                "token": token.key,
                "is_new_user": is_new_user,
                "user": {
                    "email": user.email,
                    "full_name": profile.full_name if profile else "",
                },
            }
        )


class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            challenge = start_password_reset(**serializer.validated_data)
        except EmailDeliveryError as exc:
            return _error_response(
                message=str(exc),
                code="email_delivery_failed",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if challenge is None:
            return Response({"message": "If the email exists, a reset code has been sent."})
        response: dict = {"message": "If the email exists, a reset code has been sent."}
        if getattr(settings, "OTP_HINT_IN_RESPONSE", False):
            response["otp_hint"] = challenge.code
            response["email"] = challenge.email
        return Response(response)


class PasswordResetVerifyView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = VerifyCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            challenge = verify_password_reset(**serializer.validated_data)
        except ChallengeVerificationError as exc:
            return _error_response(
                message=str(exc),
                code="challenge_verification_failed",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"message": "Password reset OTP verified.", "email": challenge.email})


class PasswordResetCompleteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = CompletePasswordResetSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            complete_password_reset(**serializer.validated_data)
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"message": "Password reset completed successfully."})


class AdminInviteView(APIView):
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin, IsSuperAdmin]

    def post(self, request):
        serializer = AdminInviteSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            challenge = invite_admin_user(
                inviter=request.user,
                email=serializer.validated_data["email"],
                role_code=serializer.validated_data["role_code"],
            )
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except EmailDeliveryError as exc:
            return _error_response(
                message=str(exc),
                code="email_delivery_failed",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payload: dict = {
            "message": "Admin invitation sent.",
            "email": challenge.email,
        }
        if getattr(settings, "OTP_HINT_IN_RESPONSE", False):
            payload["otp_hint"] = challenge.code
        return Response(payload, status=status.HTTP_201_CREATED)


class AdminInviteVerifyView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = AdminInviteVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            challenge = verify_admin_invite(**serializer.validated_data)
        except ChallengeVerificationError as exc:
            return _error_response(
                message=str(exc),
                code="challenge_verification_failed",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"message": "Admin invitation verified.", "email": challenge.email})


class AdminInviteCompleteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = AdminInviteCompleteSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            user = complete_admin_invite(**serializer.validated_data)
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        login(request, user)
        assignment = get_active_admin_assignment(user)
        return Response(
            {
                "message": "Admin invitation completed successfully.",
                "email": user.email,
                "role": "admin",
                "role_code": assignment.role.code if assignment else None,
            },
            status=status.HTTP_201_CREATED,
        )


class AdminLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            user, assignment = login_admin_user(**serializer.validated_data)
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        return Response(
            {
                "email": user.email,
                "role": "admin",
                "role_code": assignment.role.code,
                "must_change_password": bool(user.must_change_password),
            }
        )


class AdminLogoutView(APIView):
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"ok": True})


class AdminSessionView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        assignment = get_active_admin_assignment(request.user)
        profile = getattr(request.user, "profile", None)
        return Response(
            {
                "email": request.user.email,
                "full_name": profile.full_name if profile else "",
                "role": "admin",
                "role_code": assignment.role.code if assignment else None,
                "must_change_password": bool(request.user.must_change_password),
            }
        )


class AdminChangeTemporaryPasswordView(APIView):
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request):
        serializer = ChangeTemporaryPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return _error_response(
                message="Invalid input.",
                code="validation_error",
                http_status=status.HTTP_400_BAD_REQUEST,
                errors=serializer.errors,
            )

        try:
            user = change_temporary_admin_password(
                user=request.user,
                current_password=serializer.validated_data["current_password"],
                new_password=serializer.validated_data["new_password"],
            )
        except AuthnError as exc:
            return _error_response(
                message=str(exc),
                code="authn_error",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        update_session_auth_hash(request, user)
        assignment = get_active_admin_assignment(user)
        return Response(
            {
                "message": "Password changed successfully.",
                "email": user.email,
                "role": "admin",
                "role_code": assignment.role.code if assignment else None,
                "must_change_password": bool(user.must_change_password),
            }
        )
