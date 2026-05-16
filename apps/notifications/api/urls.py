from django.urls import path

from .views import (
    AdminNotificationHistoryView,
    MyNotificationPreferencesView,
    MyNotificationListView,
    MyNotificationMarkAllReadView,
    MyNotificationMarkReadView,
)

urlpatterns = [
    path("", MyNotificationListView.as_view(), name="notification-mine-list"),
    path("mark-all-read/", MyNotificationMarkAllReadView.as_view(), name="notification-mark-all-read"),
    path("<int:notification_id>/read/", MyNotificationMarkReadView.as_view(), name="notification-mark-read"),
    path("preferences/me/", MyNotificationPreferencesView.as_view(), name="notification-preferences-me"),
    path("admin/history/", AdminNotificationHistoryView.as_view(), name="admin-notification-history"),
]
