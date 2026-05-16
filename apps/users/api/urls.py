from django.urls import path

from .views import (
    AdminUserDeactivateView,
    AdminUserDetailView,
    AdminUserListView,
    AdminUserReactivateView,
    CurrentProfileView,
)

urlpatterns = [
    path("me/", CurrentProfileView.as_view(), name="profile-me"),
    path("admin/users/", AdminUserListView.as_view(), name="admin-user-list"),
    path("admin/users/<int:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("admin/users/<int:user_id>/deactivate/", AdminUserDeactivateView.as_view(), name="admin-user-deactivate"),
    path("admin/users/<int:user_id>/reactivate/", AdminUserReactivateView.as_view(), name="admin-user-reactivate"),
]
