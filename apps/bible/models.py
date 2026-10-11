from django.db import models
from django.db.models import Q

from apps.bible.choices import BiblePackKind


class BiblePack(models.Model):
    """One downloadable Bible pack (Phase 34). This is a manifest row only:
    the pack's Scripture text, word links, lexicon and concordance live in
    the SQLite file at `file_url` (object storage) and on readers' phones,
    never in Postgres. A handful of rows exist in total."""

    code = models.SlugField(max_length=32, unique=True)
    kind = models.CharField(max_length=16, choices=BiblePackKind.choices)
    name = models.CharField(max_length=120)
    abbreviation = models.CharField(max_length=16)
    description = models.CharField(max_length=160, blank=True)
    attribution = models.TextField()
    supports_word_study = models.BooleanField(default=False)
    # Reserved for licensed versions that can't be stored on a phone; none
    # exist yet, so every pack today has a file_url.
    is_online_only = models.BooleanField(default=False)
    file_url = models.URLField(max_length=500, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    # Bumped every time a rebuilt file is published; phones compare it with
    # their own copy's to offer "Update available".
    data_version = models.PositiveIntegerField(default=1)
    is_enabled = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "sort_order", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="bible_pack_single_default",
            ),
            models.CheckConstraint(
                check=Q(is_default=False) | Q(kind=BiblePackKind.VERSION, is_enabled=True),
                name="bible_pack_default_is_enabled_version",
            ),
            models.CheckConstraint(
                check=Q(is_online_only=True) | ~Q(file_url=""),
                name="bible_pack_downloadable_has_file",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.abbreviation} ({self.code}, v{self.data_version})"
