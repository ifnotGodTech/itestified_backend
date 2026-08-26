from __future__ import annotations

from django.db import transaction

from apps.playlists import selectors
from apps.playlists.exceptions import (
    PlaylistItemAlreadyExistsError,
    PlaylistItemLimitExceededError,
    PlaylistLimitExceededError,
    PlaylistPremiumRequiredError,
    PlaylistReorderMismatchError,
    TestimonyNotFoundError,
)
from apps.playlists.models import Playlist, PlaylistItem
from apps.subscriptions.selectors import is_user_premium
from apps.testimonies.models import Testimony

# Phase 29 2026-08-26 product decision -- fixed, non-admin-configurable
# abuse/DB-hygiene guards. Unlike Phase 27's Agora-cost-driven caps,
# there's no vendor cost here to tune against, so these are plain
# constants, not a policy model.
MAX_PLAYLISTS_PER_OWNER = 50
MAX_ITEMS_PER_PLAYLIST = 300


def _require_premium(user) -> None:
    """Every playlist-mutating action re-checks this live, never cached
    from an earlier request -- matching Phase 21's and Phase 30's own
    "never trust a stale entitlement check" principle exactly."""
    if not is_user_premium(user):
        raise PlaylistPremiumRequiredError("Premium is required for this action.")


def _get_testimony(testimony_id: int) -> Testimony:
    testimony = Testimony.objects.filter(id=testimony_id).first()
    if testimony is None:
        raise TestimonyNotFoundError()
    return testimony


def _resequence_positions(playlist: Playlist) -> None:
    """Keeps `PlaylistItem.position` a dense 0..n-1 sequence after a
    removal -- called with the playlist's item-row lock already held by
    the caller's transaction."""
    for index, item in enumerate(playlist.items.order_by("position", "id")):
        if item.position != index:
            item.position = index
            item.save(update_fields=["position"])


@transaction.atomic
def create_playlist(*, owner, title: str, testimony_id: int) -> Playlist:
    """Phase 29 Slice 1/6 -- a playlist always starts with exactly one
    testimony (2026-08-26 product decision: no empty, title-only
    playlist) and defaults to private."""
    _require_premium(owner)
    if selectors.count_playlists_for_owner(owner=owner) >= MAX_PLAYLISTS_PER_OWNER:
        raise PlaylistLimitExceededError(f"You can have at most {MAX_PLAYLISTS_PER_OWNER} playlists.")
    testimony = _get_testimony(testimony_id)

    playlist = Playlist.objects.create(owner=owner, title=title.strip())
    PlaylistItem.objects.create(playlist=playlist, testimony=testimony, position=0)
    playlist.item_count = 1
    return playlist


@transaction.atomic
def rename_playlist(*, playlist: Playlist, actor, title: str) -> Playlist:
    _require_premium(actor)
    playlist.title = title.strip()
    playlist.save(update_fields=["title", "updated_at"])
    return playlist


@transaction.atomic
def add_item(*, playlist: Playlist, actor, testimony_id: int) -> Playlist:
    """Phase 29 Slice 6 -- the same command whether triggered from a
    testimony's own "Add to Playlist" action or from inside someone
    else's playlist view (Slice 4's "add individual items" action) --
    both are just "add this one testimony to one of my own playlists,"
    with no distinction the backend needs to make."""
    _require_premium(actor)
    locked_playlist = Playlist.objects.select_for_update().get(pk=playlist.pk)
    current_count = locked_playlist.items.count()
    if current_count >= MAX_ITEMS_PER_PLAYLIST:
        raise PlaylistItemLimitExceededError(f"A playlist can hold at most {MAX_ITEMS_PER_PLAYLIST} testimonies.")
    testimony = _get_testimony(testimony_id)
    if PlaylistItem.objects.filter(playlist=locked_playlist, testimony=testimony).exists():
        raise PlaylistItemAlreadyExistsError("This testimony is already in the playlist.")

    PlaylistItem.objects.create(playlist=locked_playlist, testimony=testimony, position=current_count)
    playlist.item_count = current_count + 1
    return playlist


@transaction.atomic
def remove_item(*, playlist: Playlist, actor, testimony_id: int) -> Playlist:
    """Removing the last item leaves an empty playlist shell rather than
    deleting it (2026-08-26 product decision) -- deletion is always its
    own explicit action (delete_playlist)."""
    _require_premium(actor)
    locked_playlist = Playlist.objects.select_for_update().get(pk=playlist.pk)
    deleted_count, _ = PlaylistItem.objects.filter(playlist=locked_playlist, testimony_id=testimony_id).delete()
    if not deleted_count:
        raise TestimonyNotFoundError()
    _resequence_positions(locked_playlist)
    playlist.item_count = locked_playlist.items.count()
    return playlist


@transaction.atomic
def reorder_items(*, playlist: Playlist, actor, ordered_testimony_ids: list[int]) -> Playlist:
    _require_premium(actor)
    locked_playlist = Playlist.objects.select_for_update().get(pk=playlist.pk)
    items = list(locked_playlist.items.all())
    current_ids = {item.testimony_id for item in items}
    if set(ordered_testimony_ids) != current_ids or len(ordered_testimony_ids) != len(items):
        raise PlaylistReorderMismatchError(
            "The reordered list must contain exactly the playlist's current items, no more and no fewer."
        )

    items_by_testimony = {item.testimony_id: item for item in items}
    for index, testimony_id in enumerate(ordered_testimony_ids):
        item = items_by_testimony[testimony_id]
        if item.position != index:
            item.position = index
            item.save(update_fields=["position"])
    return playlist


@transaction.atomic
def set_visibility(*, playlist: Playlist, actor, visibility: str) -> Playlist:
    """The confirmation step required when switching to "shared"
    (2026-08-26 product decision) is a client-side concern -- by the
    time this command runs, that's already been shown and accepted."""
    _require_premium(actor)
    playlist.visibility = visibility
    playlist.save(update_fields=["visibility", "updated_at"])
    return playlist


@transaction.atomic
def set_show_owner_name(*, playlist: Playlist, actor, show_owner_name: bool) -> Playlist:
    _require_premium(actor)
    playlist.show_owner_name = show_owner_name
    playlist.save(update_fields=["show_owner_name", "updated_at"])
    return playlist


@transaction.atomic
def delete_playlist(*, playlist: Playlist, actor) -> None:
    """Hard delete, no trash/undo (2026-08-26 product decision) -- cascades
    to the playlist's own PlaylistItem rows only; the testimonies
    themselves, and any other user's clone of this playlist, are
    completely untouched."""
    _require_premium(actor)
    playlist.delete()


@transaction.atomic
def clone_playlist(*, source_playlist_id: int, actor, title: str | None = None) -> Playlist:
    """Phase 29 Slice 4/6 -- a Premium viewer's "clone this playlist"
    action. Copies every current PlaylistItem row as-is; there is no
    per-item availability filtering here (that's Slice 7's read-time
    concern, applied uniformly to the clone same as to the original) --
    cloning is purely a bulk copy of playlist membership."""
    _require_premium(actor)
    if selectors.count_playlists_for_owner(owner=actor) >= MAX_PLAYLISTS_PER_OWNER:
        raise PlaylistLimitExceededError(f"You can have at most {MAX_PLAYLISTS_PER_OWNER} playlists.")
    source = selectors.get_playlist(playlist_id=source_playlist_id)

    clone_title = (title or source.title).strip()[:50] or source.title
    clone = Playlist.objects.create(owner=actor, title=clone_title)
    source_items = list(source.items.all()[:MAX_ITEMS_PER_PLAYLIST])
    PlaylistItem.objects.bulk_create(
        [
            PlaylistItem(playlist=clone, testimony_id=source_item.testimony_id, position=index)
            for index, source_item in enumerate(source_items)
        ]
    )
    clone.item_count = len(source_items)
    return clone
