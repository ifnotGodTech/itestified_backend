from django.urls import path

from .views import (
    PlaylistCloneView,
    PlaylistCreateView,
    PlaylistDetailView,
    PlaylistItemDetailView,
    PlaylistItemListView,
    PlaylistMineListView,
    PlaylistPublicDetailView,
    PlaylistRenameView,
    PlaylistReorderView,
    PlaylistShowOwnerNameView,
    PlaylistVisibilityView,
    UserSharedPlaylistsView,
)

urlpatterns = [
    path("", PlaylistCreateView.as_view(), name="playlist-create"),
    path("mine/", PlaylistMineListView.as_view(), name="playlist-mine-list"),
    path("mine/<int:playlist_id>/", PlaylistDetailView.as_view(), name="playlist-mine-detail"),
    path("mine/<int:playlist_id>/rename/", PlaylistRenameView.as_view(), name="playlist-rename"),
    path("mine/<int:playlist_id>/items/", PlaylistItemListView.as_view(), name="playlist-item-add"),
    path(
        "mine/<int:playlist_id>/items/<int:testimony_id>/",
        PlaylistItemDetailView.as_view(),
        name="playlist-item-remove",
    ),
    path("mine/<int:playlist_id>/reorder/", PlaylistReorderView.as_view(), name="playlist-reorder"),
    path("mine/<int:playlist_id>/visibility/", PlaylistVisibilityView.as_view(), name="playlist-visibility"),
    path(
        "mine/<int:playlist_id>/show-owner-name/",
        PlaylistShowOwnerNameView.as_view(),
        name="playlist-show-owner-name",
    ),
    path("<int:playlist_id>/clone/", PlaylistCloneView.as_view(), name="playlist-clone"),
    path("<int:playlist_id>/", PlaylistPublicDetailView.as_view(), name="playlist-public-detail"),
    path("by-user/<int:user_id>/", UserSharedPlaylistsView.as_view(), name="playlist-user-shared-list"),
]
