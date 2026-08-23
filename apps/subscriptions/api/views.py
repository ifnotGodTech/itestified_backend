from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q

from apps.authn.api.permissions import IsActiveAdmin
from apps.common.services.flutterwave import FlutterwaveGatewayError
from apps.subscriptions.exceptions import (
    PremiumPricingInvalidAmountError,
    PremiumPricingInvalidCurrencyError,
    SubscriptionAlreadyExistsError,
    SubscriptionGatewayNotConfiguredError,
    SubscriptionNotCancelableError,
    SubscriptionNotFoundError,
    SubscriptionUnsupportedCurrencyError,
)
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.subscriptions.selectors import get_current_subscription, list_premium_pricing
from apps.subscriptions.services.commands import (
    admin_cancel_subscription,
    cancel_subscription,
    set_premium_price,
    subscribe,
    verify_subscription,
)

from .serializers import (
    AdminSubscriptionCancelSerializer,
    AdminSubscriptionDetailSerializer,
    AdminSubscriptionListSerializer,
    PremiumPricingSerializer,
    SetPremiumPriceSerializer,
    SubscribeRequestSerializer,
    SubscriptionSerializer,
    SubscriptionVerifySerializer,
)


class SubscriptionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class SubscribeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            subscription = subscribe(user=request.user, currency=serializer.validated_data["currency"])
        except SubscriptionAlreadyExistsError:
            return Response(
                {"message": "You already have a subscription in progress or active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SubscriptionUnsupportedCurrencyError:
            return Response({"message": "Unsupported currency."}, status=status.HTTP_400_BAD_REQUEST)
        except SubscriptionGatewayNotConfiguredError:
            return Response(
                {"message": "Premium subscriptions are not configured yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except FlutterwaveGatewayError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(SubscriptionSerializer(subscription).data, status=status.HTTP_201_CREATED)


class PremiumPricingView(APIView):
    """The live price the Plans screen should display, per currency --
    subscribe() already reads PremiumPricing at charge time (see
    services/commands.py), but the Plans screen previously showed a
    hardcoded string with nothing keeping it in sync with an admin's price
    change. `{"NGN": 300000, "USD": 499}` in minor units, matching every
    other amount field in this app -- no pagination/list wrapper needed
    for a handful of currencies."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pricing = {p.currency: p.amount for p in list_premium_pricing()}
        return Response(pricing, status=status.HTTP_200_OK)


class VerifySubscriptionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscriptionVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            subscription = verify_subscription(
                user=request.user,
                payment_reference=serializer.validated_data["payment_reference"],
                transaction_id=serializer.validated_data["transaction_id"],
            )
        except SubscriptionNotFoundError:
            return Response({"message": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND)
        except SubscriptionGatewayNotConfiguredError:
            return Response(
                {"message": "Premium subscriptions are not configured yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(SubscriptionSerializer(subscription).data, status=status.HTTP_200_OK)


class MySubscriptionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        subscription = get_current_subscription(request.user)
        if subscription is None:
            return Response({"message": "No active subscription."}, status=status.HTTP_404_NOT_FOUND)
        return Response(SubscriptionSerializer(subscription).data, status=status.HTTP_200_OK)


class CancelSubscriptionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            subscription = cancel_subscription(user=request.user)
        except SubscriptionNotFoundError:
            return Response({"message": "No active subscription."}, status=status.HTTP_404_NOT_FOUND)
        except SubscriptionNotCancelableError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SubscriptionSerializer(subscription).data, status=status.HTTP_200_OK)


class AdminSubscriptionListView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminSubscriptionListSerializer
    pagination_class = SubscriptionPagination

    def get_queryset(self):
        queryset = Subscription.objects.select_related("user", "user__profile")
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        q = (self.request.query_params.get("q") or "").strip()
        if status_filter in SubscriptionStatus.values:
            queryset = queryset.filter(status=status_filter)
        if q:
            queryset = queryset.filter(
                Q(user__email__icontains=q)
                | Q(user__profile__full_name__icontains=q)
                | Q(payment_reference__icontains=q)
            )
        return queryset.order_by("-created_at")


class AdminSubscriptionDetailView(generics.RetrieveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminSubscriptionDetailSerializer
    queryset = Subscription.objects.select_related("user", "user__profile").prefetch_related(
        "status_history", "status_history__actor"
    )


class AdminSubscriptionCancelView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, subscription_id: int):
        serializer = AdminSubscriptionCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            subscription = admin_cancel_subscription(
                subscription_id=subscription_id,
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except SubscriptionNotFoundError:
            return Response({"message": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND)
        except SubscriptionNotCancelableError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AdminSubscriptionDetailSerializer(subscription).data, status=status.HTTP_200_OK)


class AdminPremiumPricingListView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = PremiumPricingSerializer
    pagination_class = None
    queryset = list_premium_pricing()


class AdminSetPremiumPriceView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request):
        serializer = SetPremiumPriceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            pricing = set_premium_price(
                currency=serializer.validated_data["currency"],
                amount=serializer.validated_data["amount"],
                actor=request.user,
            )
        except PremiumPricingInvalidCurrencyError:
            return Response(
                {"message": "Currency must be a 3-letter code, e.g. NGN or USD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PremiumPricingInvalidAmountError:
            return Response({"message": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)
        except SubscriptionGatewayNotConfiguredError:
            return Response(
                {"message": "Premium subscriptions are not configured yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except FlutterwaveGatewayError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(PremiumPricingSerializer(pricing).data, status=status.HTTP_200_OK)
