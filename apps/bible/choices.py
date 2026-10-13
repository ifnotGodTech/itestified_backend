from django.db import models


class BiblePackKind(models.TextChoices):
    # One downloadable Bible version (verse text, and word links once tagged).
    VERSION = "version", "Version"
    # The shared lexicon + concordance pack every word-study version uses.
    STUDY = "study", "Study"


class BiblePackChangeAction(models.TextChoices):
    # Phase 34 Slice 8: what an admin changed on the dashboard.
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    MADE_DEFAULT = "made_default", "Made the default"
