from django.urls import path

from .views import (
    AdminFeaturedHomeTestimonyDeleteView,
    AdminHomeCurationView,
    AdminInspirationalPictureCategoryActivationView,
    AdminInspirationalPictureCategoryDetailView,
    AdminInspirationalPictureCategoryListCreateView,
    AdminInspirationalPictureDetailView,
    AdminInspirationalPictureListCreateView,
    AdminInspirationalPictureUnpublishView,
    AdminInspirationalPictureUploadSignatureView,
    AdminScriptureDetailView,
    AdminScriptureListCreateView,
    mobile_home_feed_view,
    mobile_inspirational_pictures_list_view,
    mobile_scripture_today_view,
)

urlpatterns = [
    path(
        "admin/inspirational-pictures/",
        AdminInspirationalPictureListCreateView.as_view(),
        name="admin-inspirational-picture-list-create",
    ),
    path(
        "admin/inspirational-pictures/upload-signature/",
        AdminInspirationalPictureUploadSignatureView.as_view(),
        name="admin-inspirational-picture-upload-signature",
    ),
    path(
        "admin/inspirational-pictures/categories/",
        AdminInspirationalPictureCategoryListCreateView.as_view(),
        name="admin-inspirational-picture-category-list-create",
    ),
    path(
        "admin/inspirational-pictures/categories/<int:pk>/",
        AdminInspirationalPictureCategoryDetailView.as_view(),
        name="admin-inspirational-picture-category-detail",
    ),
    path(
        "admin/inspirational-pictures/categories/<int:category_id>/activation/",
        AdminInspirationalPictureCategoryActivationView.as_view(),
        name="admin-inspirational-picture-category-activation",
    ),
    path(
        "admin/inspirational-pictures/<int:pk>/",
        AdminInspirationalPictureDetailView.as_view(),
        name="admin-inspirational-picture-detail",
    ),
    path(
        "admin/inspirational-pictures/<int:picture_id>/unpublish/",
        AdminInspirationalPictureUnpublishView.as_view(),
        name="admin-inspirational-picture-unpublish",
    ),
    path(
        "admin/scriptures/",
        AdminScriptureListCreateView.as_view(),
        name="admin-scripture-list-create",
    ),
    path(
        "admin/scriptures/<int:pk>/",
        AdminScriptureDetailView.as_view(),
        name="admin-scripture-detail",
    ),
    path(
        "admin/home-curation/",
        AdminHomeCurationView.as_view(),
        name="admin-home-curation",
    ),
    path(
        "admin/home-curation/featured-testimonies/<int:testimony_id>/remove/",
        AdminFeaturedHomeTestimonyDeleteView.as_view(),
        name="admin-home-curation-featured-remove",
    ),
    path("home-feed/", mobile_home_feed_view, name="mobile-home-feed"),
    path("inspirational-pictures/", mobile_inspirational_pictures_list_view, name="mobile-inspirational-pictures"),
    path("scripture/today/", mobile_scripture_today_view, name="mobile-scripture-today"),
]
