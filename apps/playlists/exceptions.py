class PlaylistError(Exception):
    pass


class PlaylistNotFoundError(PlaylistError):
    """Raised for a missing playlist AND for a playlist that exists but
    isn't owned by the requesting actor -- collapsed into one response by
    the owner-scoped selector lookup, same as live_broadcasts'
    `_get_owned_broadcast` -- never leaks "this exists but isn't yours."""


class TestimonyNotFoundError(PlaylistError):
    pass


class PlaylistPremiumRequiredError(PlaylistError):
    code = "premium_required"
    http_status = 403


class PlaylistLimitExceededError(PlaylistError):
    """Raised at the fixed 50-playlists-per-owner cap (2026-08-26 product
    decision) -- an abuse/DB-hygiene guard, not a cost control, so it's
    not admin-configurable."""

    code = "playlist_limit_exceeded"
    http_status = 400


class PlaylistItemLimitExceededError(PlaylistError):
    """Raised at the fixed 300-items-per-playlist cap."""

    code = "playlist_item_limit_exceeded"
    http_status = 400


class PlaylistItemAlreadyExistsError(PlaylistError):
    code = "playlist_item_already_exists"
    http_status = 400


class PlaylistReorderMismatchError(PlaylistError):
    """Raised when a reorder request's testimony ids don't exactly match
    the playlist's current items -- this can't be caught by serializer
    shape validation alone since it depends on current DB state."""

    code = "playlist_reorder_mismatch"
    http_status = 400
