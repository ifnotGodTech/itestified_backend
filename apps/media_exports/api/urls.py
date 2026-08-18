from django.urls import path

from .views import AdminBrandedVideoExportListView, AdminMediaExportBrandingView, MobileBrandedVideoExportView

urlpatterns = [
    path("testimonies/<int:testimony_id>/branded-export/", MobileBrandedVideoExportView.as_view(), name="mobile-branded-video-export"),
    path("admin/branding/", AdminMediaExportBrandingView.as_view(), name="admin-media-export-branding"),
    path("admin/exports/", AdminBrandedVideoExportListView.as_view(), name="admin-branded-video-export-list"),
]
