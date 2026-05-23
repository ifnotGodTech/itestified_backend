import os
from dataclasses import dataclass


class CloudinaryUploadError(Exception):
    """Raised when Cloudinary upload cannot be completed."""


@dataclass
class CloudinaryUploadResult:
    video_url: str
    thumbnail_url: str


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CloudinaryUploadError(f"Missing required environment variable: {name}")
    return value


def _configure_cloudinary() -> None:
    try:
        import cloudinary
    except ImportError as exc:
        raise CloudinaryUploadError("cloudinary package is not installed.") from exc

    cloudinary.config(
        cloud_name=_require_env("CLOUDINARY_CLOUD_NAME"),
        api_key=_require_env("CLOUDINARY_API_KEY"),
        api_secret=_require_env("CLOUDINARY_API_SECRET"),
        secure=True,
    )


def upload_testimony_media(*, video_file, thumbnail_file=None) -> CloudinaryUploadResult:
    _configure_cloudinary()

    try:
        from cloudinary import uploader
    except ImportError as exc:
        raise CloudinaryUploadError("cloudinary uploader could not be imported.") from exc

    video_folder = os.environ.get("CLOUDINARY_TESTIMONY_VIDEO_FOLDER", "itestified/testimonies/videos")
    thumbnail_folder = os.environ.get("CLOUDINARY_TESTIMONY_THUMBNAIL_FOLDER", "itestified/testimonies/thumbnails")

    try:
        video_result = uploader.upload_large(
            video_file,
            resource_type="video",
            folder=video_folder,
            overwrite=False,
        )
    except Exception as exc:  # noqa: BLE001 - third-party exceptions vary.
        raise CloudinaryUploadError("Video upload failed.") from exc

    video_url = str(video_result.get("secure_url") or "").strip()
    if not video_url:
        raise CloudinaryUploadError("Cloudinary did not return a secure video URL.")

    thumbnail_url = ""
    public_id = str(video_result.get("public_id") or "").strip()
    if thumbnail_file is not None:
        try:
            thumbnail_result = uploader.upload(
                thumbnail_file,
                resource_type="image",
                folder=thumbnail_folder,
                overwrite=False,
            )
            thumbnail_url = str(thumbnail_result.get("secure_url") or "").strip()
        except Exception as exc:  # noqa: BLE001 - third-party exceptions vary.
            raise CloudinaryUploadError("Thumbnail upload failed.") from exc
    elif public_id:
        try:
            # Auto-generate a thumbnail frame from the uploaded video when no thumbnail was provided.
            from cloudinary.utils import cloudinary_url

            generated_url, _ = cloudinary_url(
                public_id,
                resource_type="video",
                type="upload",
                format="jpg",
                secure=True,
                transformation=[
                    {"start_offset": "2"},
                    {"width": 1280, "height": 720, "crop": "fill", "gravity": "auto"},
                ],
            )
            thumbnail_url = str(generated_url or "").strip()
        except Exception:
            thumbnail_url = ""

    return CloudinaryUploadResult(video_url=video_url, thumbnail_url=thumbnail_url)
