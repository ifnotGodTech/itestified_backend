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


def create_direct_upload_signature(*, resource_type: str) -> CloudinaryUploadSignature:
    configure_cloudinary()

    try:
        import cloudinary
        from cloudinary.utils import api_sign_request
    except ImportError as exc:
        raise CloudinaryUploadError("cloudinary package is not installed.") from exc

    common_upload_folder = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "").strip()
    if resource_type == "video":
        folder = (
            os.environ.get("CLOUDINARY_TESTIMONY_VIDEO_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/testimonies/videos"
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
    elif resource_type == "inspirational_picture":
        folder = (
            os.environ.get("CLOUDINARY_INSPIRATIONAL_PICTURE_FOLDER", "").strip()
            or common_upload_folder
            or "itestified/content/inspirational-pictures"
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
    params_to_sign = {
        "folder": folder,
        "timestamp": timestamp,
    }
    signature = api_sign_request(params_to_sign, api_secret)
    return CloudinaryUploadSignature(
        cloud_name=cloud_name,
        api_key=api_key,
        timestamp=timestamp,
        folder=folder,
        signature=signature,
    )
