from django.db import models


class BiblePackKind(models.TextChoices):
    # One downloadable Bible version (verse text, and word links once tagged).
    VERSION = "version", "Version"
    # The shared lexicon + concordance pack every word-study version uses.
    STUDY = "study", "Study"
