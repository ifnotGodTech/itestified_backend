from django.urls import path

from .views import AdminAppVersionListView, AdminAppVersionUpdateView

urlpatterns = [
    path("admin/requirements/", AdminAppVersionListView.as_view(), name="admin-app-version-list"),
    path(
        "admin/requirements/<str:platform>/",
        AdminAppVersionUpdateView.as_view(),
        name="admin-app-version-update",
    ),
]
