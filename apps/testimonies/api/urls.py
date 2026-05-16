from django.urls import path

from .views import (
    AuthenticatedMyTestimonyListView,
    AuthenticatedVideoTestimonyCreateView,
    AuthenticatedWrittenTestimonyCreateView,
    FavoriteListView,
    FavoriteToggleView,
    PublicCategoryListView,
    PublicTestimonyDetailView,
    PublicTestimonyListView,
)

urlpatterns = [
    path("categories/", PublicCategoryListView.as_view(), name="testimony-category-list"),
    path("", PublicTestimonyListView.as_view(), name="testimony-list"),
    path("<int:pk>/", PublicTestimonyDetailView.as_view(), name="testimony-detail"),
    path("mine/", AuthenticatedMyTestimonyListView.as_view(), name="testimony-mine-list"),
    path("favorites/", FavoriteListView.as_view(), name="testimony-favorite-list"),
    path("<int:testimony_id>/favorite/", FavoriteToggleView.as_view(), name="testimony-favorite-toggle"),
    path("submit/written/", AuthenticatedWrittenTestimonyCreateView.as_view(), name="testimony-submit-written"),
    path("submit/video/", AuthenticatedVideoTestimonyCreateView.as_view(), name="testimony-submit-video"),
]
