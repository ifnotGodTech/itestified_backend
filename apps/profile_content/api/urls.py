from django.urls import path

from .views import (
    AdminHelpFaqDetailView,
    AdminHelpFaqListCreateView,
    AdminHelpFaqReorderView,
    AdminProfileContentBlockListView,
    AdminProfileContentBlockUpdateView,
    mobile_help_faqs_view,
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
    path("admin/faqs/", AdminHelpFaqListCreateView.as_view(), name="admin-help-faq-list-create"),
    path("admin/faqs/reorder/", AdminHelpFaqReorderView.as_view(), name="admin-help-faq-reorder"),
    path("admin/faqs/<int:pk>/", AdminHelpFaqDetailView.as_view(), name="admin-help-faq-detail"),
    path("faqs/", mobile_help_faqs_view, name="mobile-help-faqs"),
]
