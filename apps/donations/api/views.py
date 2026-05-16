from rest_framework import generics, status
from django.conf import settings
from django.db.models import Q
from rest_framework.authentication import TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.donations.models import Donation, DonationStatus, DonationStatusHistory
from apps.donations.services.flutterwave import FlutterwaveGateway, FlutterwaveGatewayError

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


def log_status_history(*, donation: Donation, from_status: str, to_status: str, reason: str = "", actor=None) -> None:
    if from_status == to_status:
        return
    DonationStatusHistory.objects.create(
        donation=donation,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        actor=actor,
    )


class DonationCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DonationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reference = Donation.generate_reference()
        donation = Donation.objects.create(
            user=request.user,
            amount=serializer.validated_data["amount"],
            currency=serializer.validated_data["currency"],
            payment_reference=reference,
        )
        if not settings.FLUTTERWAVE_SECRET_KEY:
            donation.checkout_url = f"https://checkout.flutterwave.com/pay/{reference.lower()}"
            donation.status_reason = "Flutterwave secret key not configured."
            donation.save(update_fields=["checkout_url", "status_reason", "updated_at"])
            payload = DonationSerializer(donation).data
            return Response(payload, status=status.HTTP_201_CREATED)

        gateway = FlutterwaveGateway(
            secret_key=settings.FLUTTERWAVE_SECRET_KEY,
            base_url=settings.FLUTTERWAVE_BASE_URL,
        )
        redirect_url = settings.FLUTTERWAVE_REDIRECT_URL or "https://www.itestified.app/giving/return"
        try:
            init_result = gateway.initialize(
                amount=donation.amount,
                currency=donation.currency,
                tx_ref=donation.payment_reference,
                customer_email=request.user.email,
                customer_name=getattr(request.user, "full_name", "") or request.user.email,
                redirect_url=redirect_url,
            )
        except FlutterwaveGatewayError as exc:
            from_status = donation.status
            donation.status = "declined"
            donation.status_reason = str(exc)
            donation.save(update_fields=["status", "status_reason", "updated_at"])
            log_status_history(
                donation=donation,
                from_status=from_status,
                to_status=donation.status,
                reason=donation.status_reason,
                actor=request.user,
            )
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        donation.checkout_url = init_result.checkout_url
        donation.provider_transaction_id = init_result.provider_transaction_id
        donation.save(update_fields=["checkout_url", "provider_transaction_id", "updated_at"])
        payload = DonationSerializer(donation).data
        return Response(payload, status=status.HTTP_201_CREATED)


class DonationVerifyView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DonationVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donation = Donation.objects.filter(
            payment_reference=serializer.validated_data["payment_reference"],
            user=request.user,
        ).first()
        if donation is None:
            return Response({"message": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)

        if not settings.FLUTTERWAVE_SECRET_KEY:
            return Response({"message": "Flutterwave is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        gateway = FlutterwaveGateway(
            secret_key=settings.FLUTTERWAVE_SECRET_KEY,
            base_url=settings.FLUTTERWAVE_BASE_URL,
        )
        verify_result = gateway.verify(serializer.validated_data["transaction_id"])
        from_status = donation.status
        donation.status = verify_result.status
        donation.provider_transaction_id = verify_result.provider_transaction_id
        donation.status_reason = verify_result.status_reason
        donation.save(update_fields=["status", "provider_transaction_id", "status_reason", "updated_at"])
        log_status_history(
            donation=donation,
            from_status=from_status,
            to_status=donation.status,
            reason=donation.status_reason,
            actor=request.user,
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
        if settings.FLUTTERWAVE_SECRET_HASH:
            signature = request.headers.get("verif-hash", "")
            if signature != settings.FLUTTERWAVE_SECRET_HASH:
                return Response({"message": "Invalid webhook signature."}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data.get("data", request.data)
        serializer = DonationProviderCallbackSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        donation = Donation.objects.filter(
            payment_reference=serializer.validated_data["payment_reference"],
        ).first()
        if donation is None:
            return Response({"message": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)

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
        from_status = donation.status
        donation.status = status_value
        donation.provider_transaction_id = str(provider_txn_id)
        donation.status_reason = serializer.validated_data.get("status_reason", "")
        donation.save(update_fields=["status", "provider_transaction_id", "status_reason", "updated_at"])
        log_status_history(
            donation=donation,
            from_status=from_status,
            to_status=donation.status,
            reason=donation.status_reason,
        )
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
            queryset = queryset.filter(Q(user__email__icontains=q) | Q(payment_reference__icontains=q))
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
        donation = Donation.objects.filter(pk=donation_id).first()
        if donation is None:
            return Response({"message": "Donation not found."}, status=status.HTTP_404_NOT_FOUND)
        if donation.status != DonationStatus.SUCCESSFUL:
            return Response(
                {"message": "Only successful donations can be reversed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_status = donation.status
        donation.status = DonationStatus.REVERSED
        donation.status_reason = serializer.validated_data["reason"]
        donation.save(update_fields=["status", "status_reason", "updated_at"])
        log_status_history(
            donation=donation,
            from_status=from_status,
            to_status=donation.status,
            reason=donation.status_reason,
            actor=request.user,
        )
        return Response(AdminDonationDetailSerializer(donation).data, status=status.HTTP_200_OK)
