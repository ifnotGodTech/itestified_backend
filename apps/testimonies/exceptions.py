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


class AudioDailyLimitReachedError(AudioUploadContractError):
    code = "audio_daily_limit_reached"
    http_status = 429


class VideoUploadContractError(Exception):
    code = "video_upload_invalid"
    http_status = 400


class VideoPremiumRequiredError(VideoUploadContractError):
    code = "premium_required"
    http_status = 403


class VideoDailyLimitReachedError(VideoUploadContractError):
    code = "video_daily_limit_reached"
    http_status = 429


class VideoUploadIntentNotFoundError(VideoUploadContractError):
    code = "video_upload_intent_not_found"


class VideoUploadIntentExpiredError(VideoUploadContractError):
    code = "video_upload_intent_expired"


class VideoUploadIntentConsumedError(VideoUploadContractError):
    code = "video_upload_intent_consumed"


class VideoUploadAssetVerificationError(VideoUploadContractError):
    code = "video_upload_asset_invalid"
