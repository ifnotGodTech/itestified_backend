from django.urls import path

from .views import (
    AdminDonationDetailView,
    AdminDonationListView,
    AdminDonationReverseView,
    DonationCreateView,
    DonationMineDetailView,
    DonationMineListView,
    DonationProviderCallbackView,
    DonationVerifyView,
)

urlpatterns = [
    path("", DonationCreateView.as_view(), name="donation-create"),
    path("verify/", DonationVerifyView.as_view(), name="donation-verify"),
    path("mine/", DonationMineListView.as_view(), name="donation-mine-list"),
    path("mine/<int:pk>/", DonationMineDetailView.as_view(), name="donation-mine-detail"),
    path("admin/donations/", AdminDonationListView.as_view(), name="admin-donation-list"),
    path("admin/donations/<int:pk>/", AdminDonationDetailView.as_view(), name="admin-donation-detail"),
    path("admin/donations/<int:donation_id>/reverse/", AdminDonationReverseView.as_view(), name="admin-donation-reverse"),
    path("provider/callback/", DonationProviderCallbackView.as_view(), name="donation-provider-callback"),
]
