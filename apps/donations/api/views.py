from rest_framework import generics, status
from django.conf import settings
from django.db.models import Q
from rest_framework.authentication import TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.donations.exceptions import (
    DonationGatewayNotConfiguredError,
    DonationNotFoundError,
    DonationNotReversibleError,
)
from apps.donations.models import Donation, DonationStatus
from apps.donations.services.commands import (
    apply_provider_callback,
    create_donation,
    reverse_donation,
    verify_donation,
)
from apps.donations.services.flutterwave import FlutterwaveGatewayError

from .serializers import (
    AdminDonationDetailSerializer,
    AdminDonationListSerializer,
    DonationCreateSerializer,
    DonationProviderCallbackSerializer,
    DonationReverseSerializer,
    DonationSerializer,
    DonationVerifySerializer,
)


class DonationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class DonationCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DonationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            donation = create_donation(
                user=request.user,
                amount=serializer.validated_data["amount"],
                currency=serializer.validated_data["currency"],
            )
        except FlutterwaveGatewayError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(DonationSerializer(donation).data, status=status.HTTP_201_CREATED)


class DonationVerifyView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DonationVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            donation = verify_donation(
                user=request.user,
                payment_reference=serializer.validated_data["payment_reference"],
                transaction_id=serializer.validated_data["transaction_id"],
            )
        except DonationNotFoundError:
            return Response({"message": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)
        except DonationGatewayNotConfiguredError:
            return Response(
                {"message": "Flutterwave is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        return Response(DonationSerializer(donation).data, status=status.HTTP_200_OK)


class DonationMineListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = DonationSerializer
    pagination_class = DonationPagination

    def get_queryset(self):
        return Donation.objects.filter(user=self.request.user)


class DonationMineDetailView(generics.RetrieveAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = DonationSerializer

    def get_queryset(self):
        return Donation.objects.filter(user=self.request.user)


class DonationProviderCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.FLUTTERWAVE_SECRET_HASH:
            return Response(
                {"message": "Webhook secret hash is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        signature = request.headers.get("verif-hash", "")
        if signature != settings.FLUTTERWAVE_SECRET_HASH:
            return Response({"message": "Invalid webhook signature."}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data.get("data", request.data)
        serializer = DonationProviderCallbackSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        inbound_status = serializer.validated_data.get("status", "")
        if inbound_status:
            status_value = inbound_status
        else:
            status_value = str(payload.get("status", "")).lower()
            status_value = "successful" if status_value == "successful" else "declined"
        provider_txn_id = (
            serializer.validated_data.get("provider_transaction_id")
            or serializer.validated_data.get("transaction_id")
            or payload.get("id")
            or ""
        )

        donation = apply_provider_callback(
            payment_reference=serializer.validated_data["payment_reference"],
            status_value=status_value,
            provider_transaction_id=str(provider_txn_id),
            status_reason=serializer.validated_data.get("status_reason", ""),
        )
        if donation is None:
            return Response({"message": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(DonationSerializer(donation).data, status=status.HTTP_200_OK)


class AdminDonationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminDonationListSerializer
    pagination_class = DonationPagination

    def get_queryset(self):
        queryset = Donation.objects.select_related("user")
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        q = (self.request.query_params.get("q") or "").strip()
        date_from = (self.request.query_params.get("from") or "").strip()
        date_to = (self.request.query_params.get("to") or "").strip()

        if status_filter in {
            DonationStatus.PENDING,
            DonationStatus.SUCCESSFUL,
            DonationStatus.DECLINED,
            DonationStatus.REVERSED,
            DonationStatus.REFUNDED,
        }:
            queryset = queryset.filter(status=status_filter)
        if q:
            queryset = queryset.filter(
                Q(user__email__icontains=q)
                | Q(user__full_name__icontains=q)
                | Q(payment_reference__icontains=q)
            )
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset.order_by("-created_at")


class AdminDonationDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminDonationDetailSerializer
    queryset = Donation.objects.select_related("user").prefetch_related("status_history", "status_history__actor")


class AdminDonationReverseView(APIView):
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, donation_id: int):
        serializer = DonationReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            donation = reverse_donation(
                donation_id=donation_id,
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except DonationNotFoundError:
            return Response({"message": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)
        except DonationNotReversibleError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AdminDonationDetailSerializer(donation).data, status=status.HTTP_200_OK)
