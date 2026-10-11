"""Reading built pack files and verifying an uploaded copy (Phase 34)."""

from __future__ import annotations

import gzip
import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import NamedTuple

import requests

from apps.bible.exceptions import BiblePackInvalidError, BiblePackVerificationError
from apps.bible.services.pack_builds import PACK_FORMAT_VERSION, sha256_of_file

PUBLISHED_DOWNLOAD_TIMEOUT_SECONDS = 60
_REQUIRED_META_KEYS = ("format_version", "kind", "code", "name", "abbreviation", "attribution")


class PackFile(NamedTuple):
    path: Path
    size_bytes: int
    sha256: str
    meta: dict[str, str]


def read_pack_file(path: Path) -> PackFile:
    """Opens a built `.sqlite.gz` pack and returns its size, sha256 and
    `meta` table. Raises BiblePackInvalidError if it isn't a pack this
    format version understands."""
    if not path.is_file():
        raise BiblePackInvalidError(f"{path} is not a file.")
    with tempfile.TemporaryDirectory() as workdir:
        database_path = Path(workdir) / "pack.sqlite"
        try:
            with gzip.open(path, "rb") as compressed, database_path.open("wb") as target:
                shutil.copyfileobj(compressed, target)
            connection = sqlite3.connect(database_path)
            try:
                meta = dict(connection.execute("SELECT key, value FROM meta").fetchall())
            finally:
                connection.close()
        except (OSError, sqlite3.DatabaseError) as exc:
            raise BiblePackInvalidError(f"{path} is not a readable Bible pack: {exc}") from exc

    missing = [key for key in _REQUIRED_META_KEYS if not meta.get(key)]
    if missing:
        raise BiblePackInvalidError(f"{path} is missing pack metadata: {', '.join(missing)}.")
    if meta["format_version"] != str(PACK_FORMAT_VERSION):
        raise BiblePackInvalidError(
            f"{path} is pack format {meta['format_version']}; this backend publishes format {PACK_FORMAT_VERSION}."
        )
    return PackFile(path=path, size_bytes=path.stat().st_size, sha256=sha256_of_file(path), meta=meta)


def verify_published_copy(*, pack: PackFile, url: str) -> None:
    """Downloads `url` and checks it is byte-for-byte the built pack, so a
    failed, partial or wrong upload is never registered for readers."""
    digest = hashlib.sha256()
    size = 0
    try:
        with requests.get(url, stream=True, timeout=PUBLISHED_DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except requests.RequestException as exc:
        raise BiblePackVerificationError(f"Couldn't download {url}: {exc}") from exc

    if size != pack.size_bytes or digest.hexdigest() != pack.sha256:
        raise BiblePackVerificationError(
            f"{url} serves {size} bytes (sha256 {digest.hexdigest()}), but the built pack is "
            f"{pack.size_bytes} bytes (sha256 {pack.sha256}). Re-upload the file, then publish again."
        )


def fetch_published_pack(*, url: str, expected_sha256: str, workdir: Path) -> PackFile:
    """For publishing on a server that doesn't have the built file: downloads
    `url` into `workdir`, refuses it unless its sha256 is the one the local
    build printed, then reads its metadata from the downloaded copy itself."""
    target = workdir / "published.sqlite.gz"
    try:
        with requests.get(url, stream=True, timeout=PUBLISHED_DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    handle.write(chunk)
    except requests.RequestException as exc:
        raise BiblePackVerificationError(f"Couldn't download {url}: {exc}") from exc

    actual = sha256_of_file(target)
    if actual != expected_sha256.strip().lower():
        raise BiblePackVerificationError(
            f"{url} has sha256 {actual}, but the built pack is {expected_sha256.strip().lower()}. "
            "Re-upload the file, then publish again."
        )
    return read_pack_file(target)
