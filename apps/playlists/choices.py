from django.db import models


class PlaylistVisibility(models.TextChoices):
    """Phase 29 -- a discoverability setting, not an access-control one.
    Any Premium user holding a playlist's id can open it either way; PRIVATE
    just means it's never listed on the owner's profile Playlists section
    for anyone else to find without a link. See selectors.py/services/
    commands.py for where that distinction is actually enforced."""

    PRIVATE = "private", "Private"
    SHARED = "shared", "Shared"
