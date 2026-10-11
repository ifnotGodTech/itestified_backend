from __future__ import annotations

import logging
from typing import NamedTuple

from django.db import transaction

from apps.bible.choices import BiblePackKind
from apps.bible.exceptions import BiblePackInvalidError
from apps.bible.models import BiblePack
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
