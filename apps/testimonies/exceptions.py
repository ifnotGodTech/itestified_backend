class TestimonyTransitionNotAllowedError(Exception):
    pass


class TestimonyTranslationNotReadyError(Exception):
    """Raised when a translation is requested before the testimony has a
    completed transcript to translate from."""
