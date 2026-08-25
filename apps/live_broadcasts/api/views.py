from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.live_broadcasts import selectors
from apps.live_broadcasts.exceptions import (
    AgoraNotConfiguredError,
    InsufficientAllowanceError,
    LiveBroadcastApprovalAlreadyDecidedError,
    LiveBroadcastingDisabledError,
    LiveBroadcastNotFoundError,
    LiveBroadcastWrongStatusError,
    LiveMinutePricingNotConfiguredError,
    LiveMinutePurchaseNotFoundError,
    NotAVerifiedMinistryError,
)
from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalRequest,
    LiveBroadcastApprovalStatus,
    LiveBroadcastEndedReason,
)
from apps.live_broadcasts.services import commands

from .serializers import (
    AllowanceSerializer,
    CreateLiveBroadcastSerializer,
    DecideBroadcastApprovalSerializer,
    InitiateMinutePurchaseSerializer,
    LiveBroadcastApprovalRequestSerializer,
    LiveBroadcastSerializer,
    LiveMinutePurchaseSerializer,
    PublicLiveBroadcastSerializer,
    PublisherCredentialSerializer,
    RequestBroadcastApprovalSerializer,
    VerifyMinutePurchaseSerializer,
    ViewerJoinCredentialSerializer,
)


def _get_owned_broadcast(*, user, broadcast_id: int) -> LiveBroadcast:
    broadcast = LiveBroadcast.objects.filter(id=broadcast_id, creator=user).first()
    if broadcast is None:
        raise LiveBroadcastNotFoundError()
    return broadcast


class LiveNowBroadcastListView(generics.ListAPIView):
    """Phase 27 Slice 2 -- viewer discovery, live-now. Public, guests
    included, matching PublicTestimonyListView's own permissioning."""

    permission_classes = [AllowAny]
    serializer_class = PublicLiveBroadcastSerializer
    pagination_class = None

    def get_queryset(self):
        return selectors.list_live_broadcasts()


class UpcomingBroadcastListView(generics.ListAPIView):
    """Phase 27 Slice 2 -- viewer discovery, scheduled-upcoming."""

    permission_classes = [AllowAny]
    serializer_class = PublicLiveBroadcastSerializer
    pagination_class = None

    def get_queryset(self):
        return selectors.list_upcoming_broadcasts()


class LiveBroadcastJoinView(APIView):
    """Phase 27 Slice 2 -- a viewer (including a guest) requests a
    subscribe-only Agora credential to watch a live broadcast."""

    permission_classes = [AllowAny]

    def post(self, request, broadcast_id: int):
        broadcast = LiveBroadcast.objects.select_related(
            "creator", "creator__creator_profile", "creator__profile"
        ).filter(id=broadcast_id).first()
        if broadcast is None:
            return Response({"message": "Broadcast not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            credential = commands.join_broadcast_as_viewer(broadcast=broadcast)
        except LiveBroadcastWrongStatusError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except AgoraNotConfiguredError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        display = PublicLiveBroadcastSerializer(broadcast).data
        payload = {
            **credential.__dict__,
            "ministry_name": display["ministry_name"],
            "ministry_avatar": display["ministry_avatar"],
            "title": broadcast.title,
        }
        return Response(ViewerJoinCredentialSerializer(payload).data, status=status.HTTP_200_OK)


class LiveBroadcastListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateLiveBroadcastSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            broadcast = commands.create_live_broadcast(creator=request.user, **serializer.validated_data)
        except NotAVerifiedMinistryError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(LiveBroadcastSerializer(broadcast).data, status=status.HTTP_201_CREATED)


class LiveBroadcastGoLiveView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, broadcast_id: int):
        try:
            broadcast = _get_owned_broadcast(user=request.user, broadcast_id=broadcast_id)
            credential = commands.go_live(broadcast=broadcast, actor=request.user)
        except LiveBroadcastNotFoundError:
            return Response({"message": "Broadcast not found."}, status=status.HTTP_404_NOT_FOUND)
        except NotAVerifiedMinistryError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except LiveBroadcastWrongStatusError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except LiveBroadcastingDisabledError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except InsufficientAllowanceError as exc:
            return Response(
                {
                    "message": str(exc),
                    "code": "insufficient_allowance",
                    "shortfall_minutes": exc.shortfall_minutes,
                    "remaining_minutes": exc.remaining_minutes,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        except AgoraNotConfiguredError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(PublisherCredentialSerializer(credential.__dict__).data, status=status.HTTP_200_OK)


class LiveBroadcastEndView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, broadcast_id: int):
        try:
            broadcast = _get_owned_broadcast(user=request.user, broadcast_id=broadcast_id)
            broadcast = commands.end_broadcast(
                broadcast=broadcast, reason=LiveBroadcastEndedReason.CREATOR_ENDED, actor=request.user
            )
        except LiveBroadcastNotFoundError:
            return Response({"message": "Broadcast not found."}, status=status.HTTP_404_NOT_FOUND)
        except LiveBroadcastWrongStatusError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LiveBroadcastSerializer(broadcast).data, status=status.HTTP_200_OK)


class LiveStreamingAllowanceView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            selectors.require_verified_ministry(request.user)
        except NotAVerifiedMinistryError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        summary = selectors.compute_allowance_summary(creator=request.user)
        return Response(AllowanceSerializer(summary).data, status=status.HTTP_200_OK)


class LiveMinutePurchaseInitiateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InitiateMinutePurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            purchase = commands.initiate_minute_purchase(creator=request.user, **serializer.validated_data)
        except NotAVerifiedMinistryError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except LiveMinutePricingNotConfiguredError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LiveMinutePurchaseSerializer(purchase).data, status=status.HTTP_201_CREATED)


class LiveMinutePurchaseVerifyView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, payment_reference: str):
        serializer = VerifyMinutePurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            purchase = commands.verify_minute_purchase(
                creator=request.user, payment_reference=payment_reference, **serializer.validated_data
            )
        except LiveMinutePurchaseNotFoundError:
            return Response({"message": "Purchase not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(LiveMinutePurchaseSerializer(purchase).data, status=status.HTTP_200_OK)


class LiveBroadcastRequestApprovalView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, broadcast_id: int):
        serializer = RequestBroadcastApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            broadcast = _get_owned_broadcast(user=request.user, broadcast_id=broadcast_id)
        except LiveBroadcastNotFoundError:
            return Response({"message": "Broadcast not found."}, status=status.HTTP_404_NOT_FOUND)
        approval_request = commands.request_broadcast_approval(broadcast=broadcast, **serializer.validated_data)
        return Response(
            LiveBroadcastApprovalRequestSerializer(approval_request).data, status=status.HTTP_201_CREATED
        )


class AdminLiveBroadcastApprovalRequestListView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def get(self, request):
        requests_qs = LiveBroadcastApprovalRequest.objects.filter(
            status=LiveBroadcastApprovalStatus.PENDING
        ).select_related("creator")
        return Response(LiveBroadcastApprovalRequestSerializer(requests_qs, many=True).data)


class AdminLiveBroadcastApprovalDecideView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, approval_request_id: int):
        serializer = DecideBroadcastApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval_request = LiveBroadcastApprovalRequest.objects.filter(id=approval_request_id).first()
        if approval_request is None:
            return Response({"message": "Approval request not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            approval_request = commands.decide_broadcast_approval(
                approval_request=approval_request, actor=request.user, **serializer.validated_data
            )
        except LiveBroadcastApprovalAlreadyDecidedError:
            return Response({"message": "This request was already decided."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LiveBroadcastApprovalRequestSerializer(approval_request).data, status=status.HTTP_200_OK)
