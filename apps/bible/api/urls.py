from django.urls import path

from .views import (
    AdminBiblePackChangeListView,
    AdminBiblePackDisableView,
    AdminBiblePackEnableView,
    AdminBiblePackListView,
    AdminBiblePackMakeDefaultView,
    BiblePackListView,
)

urlpatterns = [
    path("packs/", BiblePackListView.as_view(), name="bible-pack-list"),
    # Phase 34 Slice 8: the admin's Bible settings (dashboard session auth).
    path("admin/packs/", AdminBiblePackListView.as_view(), name="bible-admin-pack-list"),
    path("admin/packs/changes/", AdminBiblePackChangeListView.as_view(), name="bible-admin-pack-changes"),
    path("admin/packs/<slug:code>/enable/", AdminBiblePackEnableView.as_view(), name="bible-admin-pack-enable"),
    path("admin/packs/<slug:code>/disable/", AdminBiblePackDisableView.as_view(), name="bible-admin-pack-disable"),
    path(
        "admin/packs/<slug:code>/make-default/",
        AdminBiblePackMakeDefaultView.as_view(),
        name="bible-admin-pack-make-default",
    ),
]
