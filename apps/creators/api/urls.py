from django.urls import path

from .views import (
    AdminCreatorProfileListView,
    AdminCreatorProfileVerifyView,
    CreatorAnalyticsView,
    CreatorFollowToggleView,
    CreatorProfileMeView,
    PrayerInboxView,
    PrayerReactionRespondView,
    PublicCreatorProfileDetailView,
)

urlpatterns = [
    path("me/", CreatorProfileMeView.as_view(), name="creator-profile-me"),
    path("me/analytics/", CreatorAnalyticsView.as_view(), name="creator-analytics"),
    path("me/prayer-inbox/", PrayerInboxView.as_view(), name="creator-prayer-inbox"),
    path("prayer-reactions/<int:reaction_id>/respond/", PrayerReactionRespondView.as_view(), name="creator-prayer-reaction-respond"),
    path("admin/", AdminCreatorProfileListView.as_view(), name="admin-creator-profile-list"),
    path("admin/<int:user_id>/verify/", AdminCreatorProfileVerifyView.as_view(), name="admin-creator-profile-verify"),
    path("<int:user_id>/", PublicCreatorProfileDetailView.as_view(), name="creator-profile-detail"),
    path("<int:user_id>/follow/", CreatorFollowToggleView.as_view(), name="creator-follow-toggle"),
]
