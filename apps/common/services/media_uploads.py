import os
import time
from dataclasses import dataclass


class CloudinaryUploadError(Exception):
    """Raised when Cloudinary upload cannot be completed."""


@dataclass
class CloudinaryUploadSignature:
    cloud_name: str
    api_key: str
    timestamp: int
    folder: str
    signature: str
    public_id: str = ""
    overwrite: bool = False


@dataclass(frozen=True)
class CloudinaryAudioAsset:
    public_id: str
    secure_url: str
    resource_type: str
    format: str
    file_size_bytes: int
    duration_ms: int
    width: int
    height: int

    @property
    def is_audio_only(self) -> bool:
        return self.width <= 0 and self.height <= 0


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CloudinaryUploadError(f"Missing required environment variable: {name}")
    return value


def configure_cloudinary() -> None:
    try:
        import cloudinary
    except ImportError as exc:
        raise CloudinaryUploadError("cloudinary package is not installed.") from exc

    # Support both explicit vars and Cloudinary URL-style config so Render env setup is flexible.
    cloudinary_url = os.environ.get("CLOUDINARY_URL", "").strip()
    if cloudinary_url:
        cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
        return

    cloudinary.config(
        cloud_name=require_env("CLOUDINARY_CLOUD_NAME"),
        api_key=require_env("CLOUDINARY_API_KEY"),
        api_secret=require_env("CLOUDINARY_API_SECRET"),
        secure=True,
    )


def create_direct_upload_signature(
    *, resource_type: str, public_id: str = "", overwrite: bool = False
) -> CloudinaryUploadSignature:
    configure_cloudinary()

    try:
        import cloudinary
        from cloudinary.utils import api_sign_request
    except ImportError as exc:
        raise CloudinaryUploadError("cloudinary package is not installed.") from exc

    common_upload_folder = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "").strip()
    folder = ""
    if resource_type == "media_export_logo":
        # public_id fully determines the destination path for this one --
        # no separate folder, since it's always overwritten in place rather
        # than filed alongside other uploads of the same kind.
        pass
    elif resource_type == "video":
        folder = (
            os.environ.get("CLOUDINARY_TESTIMONY_VIDEO_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/testimonies/videos"
        )
    elif resource_type == "audio":
        folder = (
            os.environ.get("CLOUDINARY_TESTIMONY_AUDIO_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/testimonies/audio"
        )
    elif resource_type == "image":
        folder = (
            os.environ.get("CLOUDINARY_TESTIMONY_THUMBNAIL_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/testimonies/thumbnails"
        )
    elif resource_type == "avatar":
        folder = (
            os.environ.get("CLOUDINARY_PROFILE_AVATAR_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/profile/avatars"
        )
    elif resource_type == "creator_avatar":
        folder = (
            os.environ.get("CLOUDINARY_CREATOR_AVATAR_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/creators/avatars"
        )
    elif resource_type == "inspirational_picture":
        folder = (
            os.environ.get("CLOUDINARY_INSPIRATIONAL_PICTURE_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/content/inspirational-pictures"
        )
    elif resource_type == "home_promo_card":
        folder = (
            os.environ.get("CLOUDINARY_HOME_PROMO_CARD_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/content/home-promo-cards"
        )
    else:
        raise CloudinaryUploadError("Unsupported upload resource type.")

    config = cloudinary.config()
    cloud_name = str(config.cloud_name or "").strip()
    api_key = str(config.api_key or "").strip()
    api_secret = str(config.api_secret or "").strip()
    if not cloud_name or not api_key or not api_secret:
        raise CloudinaryUploadError("Cloudinary direct upload credentials are incomplete.")

    timestamp = int(time.time())
    params_to_sign: dict[str, object] = {"timestamp": timestamp}
    if folder:
        params_to_sign["folder"] = folder
    if public_id:
        params_to_sign["public_id"] = public_id
    if overwrite:
        params_to_sign["overwrite"] = "true"
    signature = api_sign_request(params_to_sign, api_secret)
    return CloudinaryUploadSignature(
        cloud_name=cloud_name,
        api_key=api_key,
        timestamp=timestamp,
        folder=folder,
        signature=signature,
        public_id=public_id,
        overwrite=overwrite,
    )


def get_cloudinary_audio_asset(*, public_id: str) -> CloudinaryAudioAsset:
    """Read authoritative metadata for a Cloudinary audio asset.

    Cloudinary stores audio under the ``video`` resource type. The Admin API
    lookup is intentionally kept at this external-service boundary so domain
    services and tests do not depend directly on the provider SDK.
    """

    configure_cloudinary()
    try:
        from cloudinary import api
    except ImportError as exc:
        raise CloudinaryUploadError("cloudinary API could not be imported.") from exc

    try:
        # Cloudinary's Admin API omits duration for audio assets from the
        # compact resource response. Requesting media metadata makes the
        # provider return authoritative duration/codec fields as well as the
        # standard size and dimensions used below.
        payload = api.resource(
            public_id,
            resource_type="video",
            type="upload",
            media_metadata=True,
        )
    except Exception as exc:  # noqa: BLE001 - Cloudinary exception types vary by SDK version.
        reason = str(exc).strip()
        if reason:
            raise CloudinaryUploadError(f"Audio asset verification failed: {reason}") from exc
        raise CloudinaryUploadError("Audio asset verification failed.") from exc

    secure_url = str(payload.get("secure_url") or "").strip()
    returned_public_id = str(payload.get("public_id") or "").strip()
    if not secure_url or not returned_public_id:
        raise CloudinaryUploadError("Cloudinary returned incomplete audio asset metadata.")

    try:
        file_size_bytes = int(payload.get("bytes") or 0)
        duration_ms = round(float(payload.get("duration") or 0) * 1000)
        width = int(payload.get("width") or 0)
        height = int(payload.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise CloudinaryUploadError("Cloudinary returned invalid audio asset metadata.") from exc

    return CloudinaryAudioAsset(
        public_id=returned_public_id,
        secure_url=secure_url,
        resource_type=str(payload.get("resource_type") or "").strip().lower(),
        format=str(payload.get("format") or "").strip().lower(),
        file_size_bytes=file_size_bytes,
        duration_ms=duration_ms,
        width=width,
        height=height,
    )
