from django.conf import settings
from django.db import models

from apps.playlists.choices import PlaylistVisibility


class Playlist(models.Model):
    """Phase 29 -- a Premium user's curated, ordered collection of
    testimonies. Hard-deleted with its `PlaylistItem` rows (Meta below);
    the testimonies it points at are never touched by any playlist
    operation (see services/commands.py)."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="playlists",
    )
    title = models.CharField(max_length=50)
    # Discoverability, not access control -- see choices.py's own docstring.
    visibility = models.CharField(
        max_length=10, choices=PlaylistVisibility.choices, default=PlaylistVisibility.PRIVATE
    )
    # Independent of `visibility`: some owners sharing with a specific
    # friend want their name attached, others sharing more broadly may
    # not -- the owner's call either way (2026-08-26 product decision).
    show_owner_name = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="playlist_owner_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Playlist<{self.id}:{self.owner_id}:{self.title}>"


class PlaylistItem(models.Model):
    """One testimony's membership + position in a Playlist. Cascades from
    both sides: deleting the playlist removes its items (never the
    testimonies); a testimony being hard-deleted (apps.testimonies) removes
    it from every playlist it was in, since there's nothing left to show.
    A testimony merely being archived/rejected does NOT touch this row --
    that's a read-time visibility concern (Phase 29 Slice 7), not a
    write-time one."""

    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="items")
    testimony = models.ForeignKey(
        "testimonies.Testimony", on_delete=models.CASCADE, related_name="playlist_items"
    )
    # Dense 0..n-1 sequence maintained by every mutation in
    # services/commands.py -- never sparse, never renumbered lazily at
    # read time.
    position = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["playlist", "testimony"], name="uniq_playlist_testimony"),
        ]
        indexes = [
            models.Index(fields=["playlist", "position"], name="playlistitem_playlist_pos_idx"),
        ]

    def __str__(self) -> str:
        return f"PlaylistItem<{self.playlist_id}:{self.testimony_id}:{self.position}>"
