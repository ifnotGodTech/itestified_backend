from django.urls import path

from .views import (
    AdminLiveBroadcastApprovalDecideView,
    AdminLiveBroadcastApprovalRequestListView,
    LiveBroadcastGoLiveView,
    LiveBroadcastListCreateView,
    LiveBroadcastRequestApprovalView,
    LiveMinutePurchaseInitiateView,
    LiveMinutePurchaseVerifyView,
    LiveStreamingAllowanceView,
)

urlpatterns = [
    path("", LiveBroadcastListCreateView.as_view(), name="live-broadcast-list-create"),
    path("allowance/", LiveStreamingAllowanceView.as_view(), name="live-broadcast-allowance"),
    path("<int:broadcast_id>/go-live/", LiveBroadcastGoLiveView.as_view(), name="live-broadcast-go-live"),
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
