from django.urls import path

from .views import (
    AdminAppVersionListView,
    AdminAppVersionNotifyView,
    AdminAppVersionUpdateView,
    mobile_app_version_requirement_view,
)

urlpatterns = [
    path("admin/requirements/", AdminAppVersionListView.as_view(), name="admin-app-version-list"),
    path(
        "admin/requirements/<str:platform>/",
        AdminAppVersionUpdateView.as_view(),
        name="admin-app-version-update",
    ),
    path(
        "admin/requirements/<str:platform>/notify/",
        AdminAppVersionNotifyView.as_view(),
        name="admin-app-version-notify",
    ),
    path(
        "requirements/<str:platform>/",
        mobile_app_version_requirement_view,
        name="mobile-app-version-requirement",
    ),
]
