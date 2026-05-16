from rest_framework import generics
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from django.db.models import Q

from apps.authn.api.permissions import IsActiveAdmin

from apps.notifications.models import UserNotification, UserNotificationPreference

from .serializers import UserNotificationPreferenceSerializer, UserNotificationSerializer


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MyNotificationListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationSerializer
    pagination_class = NotificationPagination

    def get_queryset(self):
        return UserNotification.objects.select_related("actor").filter(recipient=self.request.user)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        unread_count = UserNotification.objects.filter(recipient=request.user, is_read=False).count()
        response.data["unread_count"] = unread_count
        return response


class MyNotificationMarkReadView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id: int):
        notification = UserNotification.objects.filter(id=notification_id, recipient=request.user).first()
        if notification is None:
            return Response({"message": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        unread_count = UserNotification.objects.filter(recipient=request.user, is_read=False).count()
        return Response(
            {
                "message": "Notification marked as read.",
                "notification": UserNotificationSerializer(notification).data,
                "unread_count": unread_count,
            },
            status=status.HTTP_200_OK,
        )


class MyNotificationMarkAllReadView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        now = timezone.now()
        UserNotification.objects.filter(recipient=request.user, is_read=False).update(is_read=True, read_at=now)
        return Response({"message": "All notifications marked as read.", "unread_count": 0}, status=status.HTTP_200_OK)


class AdminNotificationHistoryView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = UserNotificationSerializer
    pagination_class = NotificationPagination

    def get_queryset(self):
        queryset = UserNotification.objects.select_related("recipient", "actor")
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        notif_type = (self.request.query_params.get("type") or "").strip()
        search_text = (self.request.query_params.get("q") or "").strip()
        date_from = (self.request.query_params.get("from") or "").strip()
        date_to = (self.request.query_params.get("to") or "").strip()

        if status_filter == "read":
            queryset = queryset.filter(is_read=True)
        elif status_filter == "unread":
            queryset = queryset.filter(is_read=False)

        if notif_type in {"testimony_submitted", "testimony_approved", "testimony_rejected", "testimony_comment"}:
            queryset = queryset.filter(notification_type=notif_type)

        if search_text:
            queryset = queryset.filter(
                Q(recipient__email__icontains=search_text)
                | Q(title__icontains=search_text)
                | Q(message__icontains=search_text)
            )

        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset.order_by("-created_at", "-id")


class MyNotificationPreferencesView(APIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        preferences, _ = UserNotificationPreference.objects.get_or_create(user=request.user)
        serializer = UserNotificationPreferenceSerializer(preferences)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        preferences, _ = UserNotificationPreference.objects.get_or_create(user=request.user)
        serializer = UserNotificationPreferenceSerializer(preferences, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
