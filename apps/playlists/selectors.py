from __future__ import annotations

from django.db.models import Count, QuerySet

from apps.playlists.choices import PlaylistVisibility
from apps.playlists.exceptions import PlaylistNotFoundError
from apps.playlists.models import Playlist
from apps.testimonies.models import TestimonyStatus


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


def get_owner_display_name(owner) -> str:
    """Mirrors the ministry_name fallback chain already used for
    PublicLiveBroadcastSerializer (Phase 27) -- creator display name,
    then personal profile name, then email -- kept duplicated per this
    app's own use rather than a new cross-app shared helper, matching
    established convention."""
    creator_profile = getattr(owner, "creator_profile", None)
    if creator_profile and creator_profile.display_name.strip():
        return creator_profile.display_name
    profile = getattr(owner, "profile", None)
    if profile and profile.full_name.strip():
        return profile.full_name
    return owner.email


def get_owner_avatar(owner) -> str:
    creator_profile = getattr(owner, "creator_profile", None)
    if creator_profile and creator_profile.avatar_url:
        return creator_profile.avatar_url
    profile = getattr(owner, "profile", None)
    return profile.avatar if profile else ""


def _is_item_available(item) -> bool:
    """Phase 29 Slice 7 -- the only filter a playlist's read path needs
    today (moderation/publish status). Nothing Phase-30-specific yet,
    since `is_premium_exclusive` doesn't exist -- see the cross-reference
    left in Phase 30's own Background note for when it does."""
    testimony = item.testimony
    return testimony.status == TestimonyStatus.APPROVED and testimony.category.is_active


def _item_view(item) -> dict:
    return {
        "testimony_id": item.testimony_id,
        "position": item.position,
        "title": item.testimony.title,
        "testimony_type": item.testimony.testimony_type,
    }


def _ordered_items_with_testimony(playlist: Playlist):
    return playlist.items.select_related("testimony", "testimony__category").order_by("position", "id")


def build_owner_playlist_view(playlist: Playlist) -> list[dict]:
    """The owner sees every item, with a distinct marker for one whose
    testimony has since become unavailable (2026-08-26 product decision)
    -- they added it deliberately and should understand why their own
    count changed, unlike any other viewer."""
    views = []
    for item in _ordered_items_with_testimony(playlist):
        view = _item_view(item)
        view["is_available"] = _is_item_available(item)
        views.append(view)
    return views


def build_visitor_playlist_view(playlist: Playlist) -> list[dict]:
    """A non-owner (Premium, holding a valid id) never sees an
    unavailable item at all -- silently absent, not marked broken or
    locked."""
    return [_item_view(item) for item in _ordered_items_with_testimony(playlist) if _is_item_available(item)]


def list_shared_playlists_for_user(*, target_user) -> QuerySet[Playlist]:
    """What a Premium visitor sees on someone else's profile Playlists
    section -- shared only, private ones are genuinely absent from this
    query, not filtered out after the fact."""
    return _playlist_queryset_with_item_count().filter(owner=target_user, visibility=PlaylistVisibility.SHARED)


def count_shared_playlists_for_user(*, target_user) -> int:
    """What a free/guest visitor sees instead of the list above -- a
    count only, contents locked (2026-08-26 product decision)."""
    return Playlist.objects.filter(owner=target_user, visibility=PlaylistVisibility.SHARED).count()
