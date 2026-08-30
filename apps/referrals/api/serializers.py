from decimal import Decimal

from rest_framework import serializers

from apps.referrals.models import ReferralCommission, ReferralCommissionRate
from apps.referrals.selectors import format_referred_user_label


class ReferralCommissionRateSerializer(serializers.ModelSerializer):
    updated_by_email = serializers.EmailField(source="updated_by.email", read_only=True, default="")

    class Meta:
        model = ReferralCommissionRate
        fields = ("id", "percent", "updated_by_email", "updated_at")


class SetReferralCommissionRateSerializer(serializers.Serializer):
    percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100")
    )


class AdminReferralCommissionSerializer(serializers.ModelSerializer):
    referrer_email = serializers.EmailField(source="referrer.email", read_only=True)
    referred_user_email = serializers.EmailField(source="referred_user.email", read_only=True)
    paid_by_email = serializers.EmailField(source="paid_by.email", read_only=True, default="")

    class Meta:
        model = ReferralCommission
        fields = (
            "id",
            "referrer_email",
            "referred_user_email",
            "amount",
            "currency",
            "rate_percent",
            "billing_period_end",
            "is_paid",
            "paid_at",
            "paid_by_email",
            "created_at",
        )


class MyReferralCommissionSerializer(serializers.ModelSerializer):
    referred_user_label = serializers.SerializerMethodField()

    class Meta:
        model = ReferralCommission
        fields = (
            "id",
            "referred_user_label",
            "amount",
            "currency",
            "is_paid",
            "paid_at",
            "created_at",
        )

    def get_referred_user_label(self, obj) -> str:
        referred_user = obj.referred_user
        full_name = referred_user.profile.full_name if hasattr(referred_user, "profile") else ""
        return format_referred_user_label(full_name)


class MyReferralLinkSerializer(serializers.Serializer):
    terms_accepted = serializers.BooleanField()
    code = serializers.CharField(allow_null=True)


class ReferralTermsAcceptanceSerializer(serializers.Serializer):
    terms_accepted = serializers.BooleanField()
    accepted_at = serializers.DateTimeField()
