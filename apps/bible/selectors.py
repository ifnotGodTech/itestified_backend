from django.db.models import QuerySet

from apps.bible.models import BiblePack, BiblePackChange


def list_available_packs() -> QuerySet[BiblePack]:
    """Packs readers can see: enabled ones only, in display order."""
    return BiblePack.objects.filter(is_enabled=True).order_by("kind", "sort_order", "code")


def list_all_packs() -> QuerySet[BiblePack]:
    """Every pack, hidden ones included, for the admin's Bible settings:
    the Bible versions first ("version" > "study"), then word study."""
    return BiblePack.objects.order_by("-kind", "sort_order", "code")


def list_pack_changes() -> QuerySet[BiblePackChange]:
    """The dashboard's change history, newest first."""
    return BiblePackChange.objects.select_related("pack", "actor", "actor__profile").order_by("-created_at", "-id")
