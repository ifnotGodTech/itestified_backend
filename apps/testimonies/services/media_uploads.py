import os
from dataclasses import dataclass
from urllib.parse import urlparse

from apps.common.services.media_uploads import (
    CloudinaryUploadError,
    CloudinaryUploadSignature,
    configure_cloudinary,
    create_direct_upload_signature,
)

__all__ = [
    "CloudinaryUploadError",
    "CloudinaryUploadSignature",
    "CloudinaryUploadResult",
    "build_cloudinary_video_thumbnail_url",
    "create_direct_upload_signature",
    "upload_testimony_media",
]


@dataclass
class CloudinaryUploadResult:
    video_url: str
    thumbnail_url: str


def build_cloudinary_video_thumbnail_url(video_url: str) -> str:
    parsed = urlparse((video_url or "").strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "res.cloudinary.com":
        return ""
    marker = "/video/upload/"
    if marker not in parsed.path:
        return ""

    prefix, delivery_path = parsed.path.split(marker, 1)
    if "." not in delivery_path.rsplit("/", 1)[-1]:
        return ""
    public_path = delivery_path.rsplit(".", 1)[0]
    return f"{parsed.scheme}://{parsed.netloc}{prefix}{marker}so_2,w_1280,h_720,c_fill,g_auto/{public_path}.jpg"


def upload_testimony_media(*, video_file, thumbnail_file=None) -> CloudinaryUploadResult:
    configure_cloudinary()

    try:
        from cloudinary import uploader
    except ImportError as exc:
        raise CloudinaryUploadError("cloudinary uploader could not be imported.") from exc

    common_upload_folder = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "").strip()
    video_folder = (
        os.environ.get("CLOUDINARY_TESTIMONY_VIDEO_FOLDER", "").strip()
        or common_upload_folder
        or "itestified/testimonies/videos"
    )
    thumbnail_folder = (
        os.environ.get("CLOUDINARY_TESTIMONY_THUMBNAIL_FOLDER", "").strip()
        or common_upload_folder
        or "itestified/testimonies/thumbnails"
    )

    try:
        video_result = uploader.upload_large(
            video_file,
            resource_type="video",
            folder=video_folder,
            overwrite=False,
        )
    except Exception as exc:  # noqa: BLE001 - third-party exceptions vary.
        reason = str(exc).strip()
        if reason:
            raise CloudinaryUploadError(f"Video upload failed: {reason}") from exc
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
            reason = str(exc).strip()
            if reason:
                raise CloudinaryUploadError(f"Thumbnail upload failed: {reason}") from exc
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
