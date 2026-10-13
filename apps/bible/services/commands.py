from __future__ import annotations

import logging
from typing import NamedTuple

from django.db import transaction

from apps.bible.choices import BiblePackChangeAction, BiblePackKind
from apps.bible.exceptions import BiblePackChangeRefused, BiblePackInvalidError
from apps.bible.models import BiblePack, BiblePackChange
from apps.bible.services.pack_files import PackFile

logger = logging.getLogger(__name__)


class RegisterResult(NamedTuple):
    pack: BiblePack
    created: bool
    file_changed: bool


@transaction.atomic
def register_bible_pack(
    *,
    pack_file: PackFile,
    file_url: str,
    enable: bool = False,
    make_default: bool = False,
    supports_word_study: bool | None = None,
) -> RegisterResult:
    """Creates or updates the manifest row for a built, already-verified
    pack. Its metadata comes from the pack's own `meta` table, so the file
    is the single source of truth. `data_version` only moves when the file
    itself changed, which is what makes phones offer "Update available".

    `enable` / `make_default` only ever switch things on: turning a pack
    off or moving the default is the admin's call (Slice 8), never a side
    effect of publishing a new file."""
    meta = pack_file.meta
    kind = meta["kind"]
    if kind not in BiblePackKind.values:
        raise BiblePackInvalidError(f"Unknown pack kind {kind!r}.")
    if make_default and kind != BiblePackKind.VERSION:
        raise BiblePackInvalidError("Only a Bible version can be the default.")

    pack = BiblePack.objects.select_for_update().filter(code=meta["code"]).first()
    created = pack is None
    if created:
        pack = BiblePack(code=meta["code"], kind=kind, data_version=1)
        file_changed = True
    else:
        if pack.kind != kind:
            raise BiblePackInvalidError(f"Pack {pack.code!r} is a {pack.kind} pack; this file is a {kind} pack.")
        file_changed = pack.sha256 != pack_file.sha256
        if file_changed:
            pack.data_version += 1

    pack.name = meta["name"]
    pack.abbreviation = meta["abbreviation"]
    pack.description = meta.get("description", "")
    pack.attribution = meta["attribution"]
    if supports_word_study is not None:
        pack.supports_word_study = supports_word_study
    else:
        pack.supports_word_study = meta.get("has_word_links") == "1"
    if meta.get("sort_order", "").isdigit():
        pack.sort_order = int(meta["sort_order"])
    pack.file_url = file_url
    pack.size_bytes = pack_file.size_bytes
    pack.sha256 = pack_file.sha256
    if enable or make_default:
        pack.is_enabled = True

    if make_default and not pack.is_default:
        # Clear the old default first so the single-default constraint
        # holds at every write, not just at commit.
        BiblePack.objects.select_for_update().filter(is_default=True).exclude(code=pack.code).update(is_default=False)
        pack.is_default = True

    pack.save()
    logger.info(
        "bible.register_bible_pack: %s code=%s data_version=%s file_changed=%s",
        "created" if created else "updated",
        pack.code,
        pack.data_version,
        file_changed,
    )
    return RegisterResult(pack=pack, created=created, file_changed=file_changed)


# --- Phase 34 Slice 8: the admin's Bible settings ---------------------------


def _lock_all_packs() -> dict[str, BiblePack]:
    """Every pack, locked in one fixed order: the guards below look across
    rows (the last enabled Bible, the single default), so two admins acting
    at once must queue rather than both pass a check on stale data."""
    return {pack.code: pack for pack in BiblePack.objects.select_for_update().order_by("id")}


def _pack_or_refuse(packs: dict[str, BiblePack], code: str) -> BiblePack:
    pack = packs.get(code)
    if pack is None:
        raise BiblePackChangeRefused("not_found", f"There's no Bible pack {code!r}.")
    return pack


@transaction.atomic
def set_bible_pack_enabled(*, actor, code: str, enabled: bool) -> BiblePack:
    """Shows (enabled) or hides a pack from readers' download list. Readers
    who already downloaded a hidden Bible keep it; they just can't get it
    anew. Refused when it would leave readers without a Bible, hide the
    default, or strand word-study Bibles without the word-study pack."""
    packs = _lock_all_packs()
    pack = _pack_or_refuse(packs, code)
    if pack.is_enabled == enabled:
        return pack

    if not enabled:
        if pack.is_default:
            raise BiblePackChangeRefused(
                "is_default",
                f"{pack.name} is the Bible new readers download first. Make another version the default before hiding it.",
            )
        other_versions = [
            other
            for other in packs.values()
            if other.kind == BiblePackKind.VERSION and other.is_enabled and other.code != pack.code
        ]
        if pack.kind == BiblePackKind.VERSION and not other_versions:
            raise BiblePackChangeRefused(
                "last_version", f"{pack.name} is the only Bible readers can download, so it has to stay."
            )
        if pack.kind == BiblePackKind.STUDY:
            needing = sorted(other.abbreviation for other in other_versions if other.supports_word_study)
            if needing:
                raise BiblePackChangeRefused(
                    "study_in_use",
                    f"Word study is used by {', '.join(needing)}. Readers couldn't look words up without it.",
                )

    pack.is_enabled = enabled
    pack.save(update_fields=["is_enabled", "updated_at"])
    action = BiblePackChangeAction.ENABLED if enabled else BiblePackChangeAction.DISABLED
    BiblePackChange.objects.create(pack=pack, action=action, actor=actor)
    logger.info("bible.set_bible_pack_enabled: code=%s enabled=%s actor=%s", pack.code, enabled, getattr(actor, "pk", None))
    return pack


@transaction.atomic
def make_bible_pack_default(*, actor, code: str) -> BiblePack:
    """Makes [code] the version new readers are offered first. It must be an
    enabled Bible version; the previous default stays enabled."""
    packs = _lock_all_packs()
    pack = _pack_or_refuse(packs, code)
    if pack.is_default:
        return pack
    if pack.kind != BiblePackKind.VERSION:
        raise BiblePackChangeRefused("not_a_version", "Only a Bible version can be the default.")
    if not pack.is_enabled:
        raise BiblePackChangeRefused("disabled", f"Show {pack.name} to readers before making it the default.")

    # Clear the old default first so the single-default constraint holds at
    # every write, not just at commit.
    BiblePack.objects.filter(is_default=True).exclude(pk=pack.pk).update(is_default=False)
    pack.is_default = True
    pack.save(update_fields=["is_default", "updated_at"])
    BiblePackChange.objects.create(pack=pack, action=BiblePackChangeAction.MADE_DEFAULT, actor=actor)
    logger.info("bible.make_bible_pack_default: code=%s actor=%s", pack.code, getattr(actor, "pk", None))
    return pack
