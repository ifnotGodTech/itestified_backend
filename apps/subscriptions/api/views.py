from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.common.services.flutterwave import FlutterwaveGatewayError
from apps.subscriptions.exceptions import (
    SubscriptionAlreadyExistsError,
    SubscriptionGatewayNotConfiguredError,
    SubscriptionNotCancelableError,
    SubscriptionNotFoundError,
)
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.subscriptions.selectors import get_current_subscription
from apps.subscriptions.services.commands import cancel_subscription, subscribe

from .serializers import (
    AdminSubscriptionDetailSerializer,
    AdminSubscriptionListSerializer,
    SubscriptionSerializer,
)


class SubscriptionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class SubscribeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            subscription = subscribe(user=request.user)
        except SubscriptionAlreadyExistsError:
            return Response(
                {"message": "You already have a subscription in progress or active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SubscriptionGatewayNotConfiguredError:
            return Response(
                {"message": "Premium subscriptions are not configured yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except FlutterwaveGatewayError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(SubscriptionSerializer(subscription).data, status=status.HTTP_201_CREATED)


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
        if status_filter in SubscriptionStatus.values:
            queryset = queryset.filter(status=status_filter)
        return queryset.order_by("-created_at")


class AdminSubscriptionDetailView(generics.RetrieveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminSubscriptionDetailSerializer
    queryset = Subscription.objects.select_related("user", "user__profile").prefetch_related(
        "status_history", "status_history__actor"
    )
