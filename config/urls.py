from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.common.api.urls")),
    path("api/v1/auth/", include("apps.authn.api.urls")),
    path("api/v1/profile/", include("apps.users.api.urls")),
    path("api/v1/testimonies/", include("apps.testimonies.api.urls")),
]
