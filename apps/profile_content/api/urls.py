from django.urls import path

from .views import (
    AdminProfileContentBlockListView,
    AdminProfileContentBlockUpdateView,
    mobile_profile_content_blocks_view,
)

urlpatterns = [
    path("admin/blocks/", AdminProfileContentBlockListView.as_view(), name="admin-profile-content-block-list"),
    path(
        "admin/blocks/<str:key>/",
        AdminProfileContentBlockUpdateView.as_view(),
        name="admin-profile-content-block-update",
    ),
    path("blocks/", mobile_profile_content_blocks_view, name="mobile-profile-content-blocks"),
]
