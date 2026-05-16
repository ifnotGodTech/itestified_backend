from rest_framework import serializers

from apps.donations.models import Donation, DonationStatus, DonationStatusHistory


class DonationCreateSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3)

    def validate_amount(self, value: int) -> int:
        # Amount is stored in minor currency units (kobo/cents).
        if value < 1:
            raise serializers.ValidationError("Amount must be at least 1 minor unit.")
        return value

    def validate_currency(self, value: str) -> str:
        currency = value.strip().upper()
        if currency not in {"NGN", "USD"}:
            raise serializers.ValidationError("Unsupported currency.")
        return currency


class DonationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donation
        fields = (
            "id",
            "amount",
            "currency",
            "status",
            "payment_reference",
            "provider",
            "checkout_url",
            "provider_transaction_id",
            "status_reason",
            "created_at",
            "updated_at",
        )


class DonationStatusHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True)

    class Meta:
        model = DonationStatusHistory
        fields = (
            "id",
            "from_status",
            "to_status",
            "reason",
            "actor_email",
            "created_at",
        )


class AdminDonationListSerializer(serializers.ModelSerializer):
    donor_name = serializers.SerializerMethodField()
    donor_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Donation
        fields = (
            "id",
            "donor_name",
            "donor_email",
            "amount",
            "currency",
            "status",
            "payment_reference",
            "provider",
            "provider_transaction_id",
            "created_at",
            "updated_at",
        )

    def get_donor_name(self, obj: Donation) -> str:
        full_name = getattr(obj.user, "full_name", "")
        return full_name or obj.user.email


class AdminDonationDetailSerializer(AdminDonationListSerializer):
    status_history = DonationStatusHistorySerializer(many=True, read_only=True)

    class Meta(AdminDonationListSerializer.Meta):
        fields = AdminDonationListSerializer.Meta.fields + ("checkout_url", "status_reason", "status_history")


class DonationProviderCallbackSerializer(serializers.Serializer):
    payment_reference = serializers.CharField(max_length=80, required=False)
    tx_ref = serializers.CharField(max_length=80, required=False)
    status = serializers.ChoiceField(choices=(DonationStatus.SUCCESSFUL, DonationStatus.DECLINED), required=False)
    transaction_id = serializers.CharField(max_length=80, required=False, allow_blank=True)
    provider_transaction_id = serializers.CharField(max_length=80, required=False, allow_blank=True)
    status_reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        reference = attrs.get("payment_reference") or attrs.get("tx_ref")
        if not reference:
            raise serializers.ValidationError("payment_reference or tx_ref is required.")
        attrs["payment_reference"] = reference
        return attrs


class DonationVerifySerializer(serializers.Serializer):
    payment_reference = serializers.CharField(max_length=80)
    transaction_id = serializers.CharField(max_length=80)


class DonationReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=500)
