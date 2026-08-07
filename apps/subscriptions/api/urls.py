from django.urls import path

from .views import (
    AdminSubscriptionCancelView,
    AdminSubscriptionDetailView,
    AdminSubscriptionListView,
    CancelSubscriptionView,
    MySubscriptionView,
    SubscribeView,
    VerifySubscriptionView,
)

urlpatterns = [
    path("", SubscribeView.as_view(), name="subscription-subscribe"),
    path("verify/", VerifySubscriptionView.as_view(), name="subscription-verify"),
    path("mine/", MySubscriptionView.as_view(), name="subscription-mine"),
    path("mine/cancel/", CancelSubscriptionView.as_view(), name="subscription-cancel"),
    path("admin/subscriptions/", AdminSubscriptionListView.as_view(), name="admin-subscription-list"),
    path("admin/subscriptions/<int:pk>/", AdminSubscriptionDetailView.as_view(), name="admin-subscription-detail"),
    path(
        "admin/subscriptions/<int:subscription_id>/cancel/",
        AdminSubscriptionCancelView.as_view(),
        name="admin-subscription-cancel",
    ),
]
