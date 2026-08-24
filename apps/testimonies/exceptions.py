class TestimonyTransitionNotAllowedError(Exception):
    pass


class TestimonyTranslationNotReadyError(Exception):
    """Raised when a translation is requested before the testimony has a
    completed transcript to translate from."""


class AIJobNotRetryableError(Exception):
    """Raised when an admin tries to retry a transcription/translation job
    that isn't in a FAILED state -- retry only makes sense for a job stuck
    on a real failure, never one that's pending/processing/already done."""


class AudioUploadContractError(Exception):
    code = "audio_upload_invalid"
    http_status = 400


class AudioPremiumRequiredError(AudioUploadContractError):
    code = "premium_required"
    http_status = 403


class AudioUploadIntentNotFoundError(AudioUploadContractError):
    code = "audio_upload_intent_not_found"


class AudioUploadIntentExpiredError(AudioUploadContractError):
    code = "audio_upload_intent_expired"


class AudioUploadIntentConsumedError(AudioUploadContractError):
    code = "audio_upload_intent_consumed"


class AudioUploadAssetVerificationError(AudioUploadContractError):
    code = "audio_upload_asset_invalid"
