from django.db.models import Q
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.referrals.exceptions import (
    ReferralCommissionAlreadyPaidError,
    ReferralCommissionNotFoundError,
    ReferralCommissionRateInvalidPercentError,
)
from apps.referrals.models import ReferralCommission
from apps.referrals.selectors import (
    get_current_commission_rate,
    get_referral_commission_totals_by_currency,
    has_accepted_referral_terms,
)
from apps.referrals.services.commands import (
    accept_referral_terms,
    get_or_create_referral_code,
    mark_referral_commission_paid,
    set_referral_commission_rate,
)
from apps.subscriptions.selectors import is_user_premium

from .serializers import (
    AdminReferralCommissionSerializer,
    MyReferralLinkSerializer,
    ReferralCommissionRateSerializer,
    ReferralTermsAcceptanceSerializer,
    SetReferralCommissionRateSerializer,
)


class AdminReferralCommissionRateView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        rate = get_current_commission_rate()
        if rate is None:
            return Response(
                {"id": None, "percent": "0.00", "updated_by_email": "", "updated_at": None},
                status=status.HTTP_200_OK,
            )
        return Response(ReferralCommissionRateSerializer(rate).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = SetReferralCommissionRateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            rate = set_referral_commission_rate(
                percent=serializer.validated_data["percent"],
                actor=request.user,
            )
        except ReferralCommissionRateInvalidPercentError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ReferralCommissionRateSerializer(rate).data, status=status.HTTP_200_OK)


class ReferralCommissionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminReferralCommissionListView(generics.ListAPIView):
    """Phase 24 Slice 3: the month-end payout ledger, mirroring
    AdminDonationListView's filter/totals shape exactly."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminReferralCommissionSerializer
    pagination_class = ReferralCommissionPagination

    def get_queryset(self):
        queryset = ReferralCommission.objects.select_related("referrer", "referred_user", "paid_by")
        paid_filter = (self.request.query_params.get("is_paid") or "").strip().lower()
        q = (self.request.query_params.get("q") or "").strip()
        date_from = (self.request.query_params.get("from") or "").strip()
        date_to = (self.request.query_params.get("to") or "").strip()

        if paid_filter in {"true", "false"}:
            queryset = queryset.filter(is_paid=(paid_filter == "true"))
        if q:
            queryset = queryset.filter(
                Q(referrer__email__icontains=q) | Q(referred_user__email__icontains=q)
            )
        if date_from:
            queryset = queryset.filter(billing_period_end__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(billing_period_end__date__lte=date_to)
        return queryset.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        totals = get_referral_commission_totals_by_currency(queryset)
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        response.data["totals"] = [
            {"currency": row["currency"], "amount": row["total_amount"]} for row in totals
        ]
        return response


class AdminMarkReferralCommissionPaidView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, commission_id: int):
        try:
            commission = mark_referral_commission_paid(commission_id=commission_id, actor=request.user)
        except ReferralCommissionNotFoundError:
            return Response({"message": "Commission not found."}, status=status.HTTP_404_NOT_FOUND)
        except ReferralCommissionAlreadyPaidError:
            return Response({"message": "This commission has already been marked paid."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AdminReferralCommissionSerializer(commission).data, status=status.HTTP_200_OK)


class MyReferralLinkView(APIView):
    """Phase 24 Slice 4. Premium-gated, and additionally gated behind
    Slice 5's terms acceptance -- returns terms_accepted=False with no
    code rather than an error when the subscriber is Premium but hasn't
    accepted yet, so mobile can route to the terms screen instead of
    treating this as a failure. The code itself is lazily generated only
    once terms are accepted."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_user_premium(request.user):
            return Response(
                {"message": "An active Premium subscription is required to get a referral link."},
                status=status.HTTP_403_FORBIDDEN,
            )

        terms_accepted = has_accepted_referral_terms(request.user)
        code = None
        if terms_accepted:
            code = get_or_create_referral_code(user=request.user).code

        return Response(
            MyReferralLinkSerializer({"terms_accepted": terms_accepted, "code": code}).data,
            status=status.HTTP_200_OK,
        )


class AcceptReferralTermsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        acceptance = accept_referral_terms(user=request.user)
        return Response(
            ReferralTermsAcceptanceSerializer(
                {"terms_accepted": True, "accepted_at": acceptance.accepted_at}
            ).data,
            status=status.HTTP_200_OK,
        )
