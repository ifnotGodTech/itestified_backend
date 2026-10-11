from django.db.models import QuerySet

from apps.bible.models import BiblePack


def list_available_packs() -> QuerySet[BiblePack]:
    """Packs readers can see: enabled ones only, in display order."""
    return BiblePack.objects.filter(is_enabled=True).order_by("kind", "sort_order", "code")
