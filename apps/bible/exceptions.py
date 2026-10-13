class BiblePackError(Exception):
    pass


class BibleSourceChecksumError(BiblePackError):
    """A downloaded source dataset doesn't match its pinned sha256 -- the
    upstream file changed, so the pin must be reviewed before rebuilding."""


class BibleSourceFormatError(BiblePackError):
    """A source dataset couldn't be parsed into a complete, canonical Bible."""


class BiblePackVerificationError(BiblePackError):
    """The file served at a pack's public URL isn't byte-for-byte the pack
    that was built, so it must not be registered for readers to download."""


class BiblePackInvalidError(BiblePackError):
    """A file passed to publish isn't a readable iTestified Bible pack."""


class BiblePackChangeRefused(Exception):
    """An admin change that would leave readers worse off (Phase 34 Slice
    8): no Bible to download, no default, or word-study Bibles without the
    word-study pack. `code` is stable for clients; the message is for people."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
