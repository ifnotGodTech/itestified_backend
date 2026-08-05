from rest_framework import serializers

from apps.subscriptions.models import Subscription, SubscriptionStatusHistory


class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = (
            "id",
            "status",
            "amount",
            "currency",
            "checkout_url",
            "current_period_end",
            "status_reason",
            "created_at",
            "updated_at",
        )


class SubscriptionStatusHistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True)

    class Meta:
        model = SubscriptionStatusHistory
        fields = (
            "id",
            "from_status",
            "to_status",
            "reason",
            "actor_email",
            "created_at",
        )


class AdminSubscriptionListSerializer(serializers.ModelSerializer):
    subscriber_name = serializers.SerializerMethodField()
    subscriber_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Subscription
        fields = (
            "id",
            "subscriber_name",
            "subscriber_email",
            "amount",
            "currency",
            "status",
            "current_period_end",
            "created_at",
            "updated_at",
        )

    def get_subscriber_name(self, obj: Subscription) -> str:
        profile = getattr(obj.user, "profile", None)
        full_name = profile.full_name if profile else ""
        return full_name or obj.user.email


class AdminSubscriptionDetailSerializer(AdminSubscriptionListSerializer):
    status_history = SubscriptionStatusHistorySerializer(many=True, read_only=True)

    class Meta(AdminSubscriptionListSerializer.Meta):
        fields = AdminSubscriptionListSerializer.Meta.fields + (
            "payment_reference",
            "provider_subscription_id",
            "status_reason",
            "status_history",
        )
