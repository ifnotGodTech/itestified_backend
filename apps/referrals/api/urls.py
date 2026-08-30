from django.urls import path

from .views import (
    AcceptReferralTermsView,
    AdminMarkReferralCommissionPaidView,
    AdminReferralCommissionListView,
    AdminReferralCommissionRateView,
    MyReferralCommissionsView,
    MyReferralLinkView,
)

urlpatterns = [
    path("admin/commission-rate/", AdminReferralCommissionRateView.as_view(), name="admin-referral-commission-rate"),
    path("admin/commissions/", AdminReferralCommissionListView.as_view(), name="admin-referral-commission-list"),
    path(
        "admin/commissions/<int:commission_id>/mark-paid/",
        AdminMarkReferralCommissionPaidView.as_view(),
        name="admin-referral-commission-mark-paid",
    ),
    path("me/link/", MyReferralLinkView.as_view(), name="referral-my-link"),
    path("me/commissions/", MyReferralCommissionsView.as_view(), name="referral-my-commissions"),
    path("me/accept-terms/", AcceptReferralTermsView.as_view(), name="referral-accept-terms"),
]
