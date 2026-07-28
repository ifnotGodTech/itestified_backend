from django.urls import path

from .views import (
    AdminSocialLinkListView,
    AdminSocialLinkUpdateView,
    mobile_social_links_view,
)

urlpatterns = [
    path("admin/", AdminSocialLinkListView.as_view(), name="admin-social-link-list"),
    path("admin/<str:platform>/", AdminSocialLinkUpdateView.as_view(), name="admin-social-link-update"),
    path("", mobile_social_links_view, name="mobile-social-links"),
]
