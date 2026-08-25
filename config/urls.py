from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.common.api.urls")),
    path("api/v1/auth/", include("apps.authn.api.urls")),
    path("api/v1/profile/", include("apps.users.api.urls")),
    path("api/v1/users/", include("apps.users.api.urls")),
    path("api/v1/testimonies/", include("apps.testimonies.api.urls")),
    path("api/v1/donations/", include("apps.donations.api.urls")),
    path("api/v1/subscriptions/", include("apps.subscriptions.api.urls")),
    path("api/v1/creators/", include("apps.creators.api.urls")),
    path("api/v1/notifications/", include("apps.notifications.api.urls")),
    path("api/v1/content/", include("apps.content.api.urls")),
    path("api/v1/app-versions/", include("apps.app_versions.api.urls")),
    path("api/v1/social-links/", include("apps.social_links.api.urls")),
    path("api/v1/profile-content/", include("apps.profile_content.api.urls")),
    path("api/v1/media-exports/", include("apps.media_exports.api.urls")),
    path("api/v1/referrals/", include("apps.referrals.api.urls")),
    path("api/v1/live-broadcasts/", include("apps.live_broadcasts.api.urls")),
]
