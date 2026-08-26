from __future__ import annotations

from django.db.models import Count, QuerySet

from apps.playlists.exceptions import PlaylistNotFoundError
from apps.playlists.models import Playlist


def _playlist_queryset_with_item_count() -> QuerySet[Playlist]:
    return Playlist.objects.annotate(item_count=Count("items"))


def get_owned_playlist(*, owner, playlist_id: int) -> Playlist:
    """Phase 29 Slice 6 -- every mutating command resolves its target
    playlist through this first. A playlist belonging to someone else
    reads identically to a nonexistent one -- see PlaylistNotFoundError's
    own docstring."""
    playlist = _playlist_queryset_with_item_count().filter(id=playlist_id, owner=owner).first()
    if playlist is None:
        raise PlaylistNotFoundError()
    return playlist


def get_playlist(*, playlist_id: int) -> Playlist:
    """Existence-only lookup, not owner-scoped -- used by clone_playlist
    (services/commands.py), since any Premium user may clone any playlist
    they can already open by id (private is a discoverability setting,
    not an access-control one; see choices.py)."""
    playlist = _playlist_queryset_with_item_count().filter(id=playlist_id).first()
    if playlist is None:
        raise PlaylistNotFoundError()
    return playlist


def list_owned_playlists(*, owner) -> QuerySet[Playlist]:
    return _playlist_queryset_with_item_count().filter(owner=owner)


def count_playlists_for_owner(*, owner) -> int:
    return Playlist.objects.filter(owner=owner).count()
