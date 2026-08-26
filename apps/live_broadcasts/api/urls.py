from django.urls import path

from .views import (
    AdminBroadcastEndView,
    AdminBroadcastMonitorView,
    AdminLiveBroadcastApprovalDecideView,
    AdminLiveBroadcastApprovalRequestListView,
    LiveBroadcastEndView,
    LiveBroadcastGoLiveView,
    LiveBroadcastJoinView,
    LiveBroadcastListCreateView,
    LiveBroadcastRequestApprovalView,
    LiveMinutePurchaseInitiateView,
    LiveMinutePurchaseVerifyView,
    LiveNowBroadcastListView,
    LiveStreamingAllowanceView,
    UpcomingBroadcastListView,
)

urlpatterns = [
    path("", LiveBroadcastListCreateView.as_view(), name="live-broadcast-list-create"),
    path("live-now/", LiveNowBroadcastListView.as_view(), name="live-broadcast-live-now"),
    path("upcoming/", UpcomingBroadcastListView.as_view(), name="live-broadcast-upcoming"),
    path("allowance/", LiveStreamingAllowanceView.as_view(), name="live-broadcast-allowance"),
    path("<int:broadcast_id>/go-live/", LiveBroadcastGoLiveView.as_view(), name="live-broadcast-go-live"),
    path("<int:broadcast_id>/end/", LiveBroadcastEndView.as_view(), name="live-broadcast-end"),
    path("<int:broadcast_id>/join/", LiveBroadcastJoinView.as_view(), name="live-broadcast-join"),
    path(
        "<int:broadcast_id>/request-approval/",
        LiveBroadcastRequestApprovalView.as_view(),
        name="live-broadcast-request-approval",
    ),
    path("minute-purchases/", LiveMinutePurchaseInitiateView.as_view(), name="live-minute-purchase-initiate"),
    path(
        "minute-purchases/<str:payment_reference>/verify/",
        LiveMinutePurchaseVerifyView.as_view(),
        name="live-minute-purchase-verify",
    ),
    path("admin/monitor/", AdminBroadcastMonitorView.as_view(), name="admin-live-broadcast-monitor"),
    path("admin/<int:broadcast_id>/end/", AdminBroadcastEndView.as_view(), name="admin-live-broadcast-end"),
    path(
        "admin/approval-requests/",
        AdminLiveBroadcastApprovalRequestListView.as_view(),
        name="admin-live-broadcast-approval-request-list",
    ),
    path(
        "admin/approval-requests/<int:approval_request_id>/decide/",
        AdminLiveBroadcastApprovalDecideView.as_view(),
        name="admin-live-broadcast-approval-decide",
    ),
]
