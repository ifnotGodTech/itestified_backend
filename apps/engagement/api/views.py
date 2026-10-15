from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.engagement.api.serializers import HomeEventBatchSerializer
from apps.engagement.services.commands import record_home_events
from apps.engagement.services.queries import SUMMARY_PERIODS, home_engagement_summary


class HomeEventBatchView(APIView):
    """Phase 35 Slice 5 -- the app sends what viewers do on the Home feed in
    small batches. Guests too (default auth classes, AllowAny: a valid token
    attaches the user, no token stays anonymous with a device id)."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = HomeEventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        accepted = record_home_events(
            user=request.user,
            device_id=data["device_id"],
            session_id=data["session_id"],
            events=data["events"],
        )
        return Response({"accepted": accepted}, status=status.HTTP_202_ACCEPTED)


class AdminHomeEngagementView(APIView):
    """Phase 35 Slice 5 -- the dashboard's "Home engagement" card."""

    permission_classes = [IsActiveAdmin]

    def get(self, request):
        try:
            days = int(request.query_params.get("days", "7"))
        except (TypeError, ValueError):
            days = 7
        if days not in SUMMARY_PERIODS:
            days = 7
        return Response(home_engagement_summary(days=days))
