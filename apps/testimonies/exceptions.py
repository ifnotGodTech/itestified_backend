class TestimonyTransitionNotAllowedError(Exception):
    pass


class TestimonyTranslationNotReadyError(Exception):
    """Raised when a translation is requested before the testimony has a
    completed transcript to translate from."""


class AIJobNotRetryableError(Exception):
    """Raised when an admin tries to retry a transcription/translation job
    that isn't in a FAILED state -- retry only makes sense for a job stuck
    on a real failure, never one that's pending/processing/already done."""
