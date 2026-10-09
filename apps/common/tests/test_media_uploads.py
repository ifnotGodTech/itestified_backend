import os
from unittest import mock

from django.test import TestCase

from apps.common.services.media_uploads import (
    CloudinaryUploadError,
    create_direct_upload_signature,
    get_cloudinary_audio_asset,
    upload_video_from_url,
)


def _cloudinary_env(**overrides):
    env = {
        "CLOUDINARY_CLOUD_NAME": "demo-cloud",
        "CLOUDINARY_API_KEY": "demo-key",
        "CLOUDINARY_API_SECRET": "demo-secret",
    }
    env.update(overrides)
    return env


class CreateDirectUploadSignatureTests(TestCase):
    """api_sign_request is pure local HMAC-style hashing (no network I/O),
    so these exercise the real folder-selection logic end to end rather
    than mocking the Cloudinary SDK itself."""

    def test_video_resource_type_uses_testimony_video_folder_default(self) -> None:
        with mock.patch.dict(os.environ, _cloudinary_env(), clear=True):
            result = create_direct_upload_signature(resource_type="video")
        self.assertEqual(result.folder, "itestified/testimonies/videos")
        self.assertEqual(result.cloud_name, "demo-cloud")
        self.assertEqual(result.api_key, "demo-key")

    def test_image_resource_type_uses_testimony_thumbnail_folder_default(self) -> None:
        with mock.patch.dict(os.environ, _cloudinary_env(), clear=True):
            result = create_direct_upload_signature(resource_type="image")
        self.assertEqual(result.folder, "itestified/testimonies/thumbnails")

    def test_audio_domain_type_uses_audio_folder_and_signs_fixed_public_id(self) -> None:
        with mock.patch.dict(os.environ, _cloudinary_env(), clear=True):
            result = create_direct_upload_signature(
                resource_type="audio",
                public_id="audio_fixed_id",
            )
        self.assertEqual(result.folder, "itestified/testimonies/audio")
        self.assertEqual(result.public_id, "audio_fixed_id")

    def test_avatar_resource_type_uses_profile_avatar_folder_default(self) -> None:
        with mock.patch.dict(os.environ, _cloudinary_env(), clear=True):
            result = create_direct_upload_signature(resource_type="avatar")
        self.assertEqual(result.folder, "itestified/profile/avatars")

    def test_avatar_folder_env_override_wins(self) -> None:
        env = _cloudinary_env(CLOUDINARY_PROFILE_AVATAR_FOLDER="custom/avatars")
        with mock.patch.dict(os.environ, env, clear=True):
            result = create_direct_upload_signature(resource_type="avatar")
        self.assertEqual(result.folder, "custom/avatars")

    def test_common_upload_folder_env_overrides_avatar_default_but_not_specific_override(self) -> None:
        env = _cloudinary_env(CLOUDINARY_UPLOAD_FOLDER="shared/uploads")
        with mock.patch.dict(os.environ, env, clear=True):
            result = create_direct_upload_signature(resource_type="avatar")
        self.assertEqual(result.folder, "shared/uploads")

    def test_inspirational_picture_resource_type_uses_content_folder_default(self) -> None:
        with mock.patch.dict(os.environ, _cloudinary_env(), clear=True):
            result = create_direct_upload_signature(resource_type="inspirational_picture")
        self.assertEqual(result.folder, "itestified/content/inspirational-pictures")

    def test_inspirational_picture_folder_env_override_wins(self) -> None:
        env = _cloudinary_env(CLOUDINARY_INSPIRATIONAL_PICTURE_FOLDER="custom/pictures")
        with mock.patch.dict(os.environ, env, clear=True):
            result = create_direct_upload_signature(resource_type="inspirational_picture")
        self.assertEqual(result.folder, "custom/pictures")

    def test_unsupported_resource_type_raises(self) -> None:
        with mock.patch.dict(os.environ, _cloudinary_env(), clear=True):
            with self.assertRaises(CloudinaryUploadError):
                create_direct_upload_signature(resource_type="bogus")

    def test_missing_credentials_raises(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CloudinaryUploadError):
                create_direct_upload_signature(resource_type="avatar")


class GetCloudinaryAudioAssetTests(TestCase):
    @mock.patch("apps.common.services.media_uploads.configure_cloudinary")
    @mock.patch("cloudinary.api.resource")
    def test_reads_audio_from_cloudinary_video_resource_type(
        self, resource_mock, configure_mock
    ) -> None:
        resource_mock.return_value = {
            "public_id": "itestified/testimonies/audio/audio_123",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/audio_123.m4a",
            "resource_type": "video",
            "format": "m4a",
            "bytes": 2048,
            "duration": 12.345,
        }

        result = get_cloudinary_audio_asset(
            public_id="itestified/testimonies/audio/audio_123"
        )

        configure_mock.assert_called_once_with()
        resource_mock.assert_called_once_with(
            "itestified/testimonies/audio/audio_123",
            resource_type="video",
            type="upload",
            media_metadata=True,
        )
        self.assertEqual(result.file_size_bytes, 2048)
        self.assertEqual(result.duration_ms, 12345)
        self.assertTrue(result.is_audio_only)

    @mock.patch("apps.common.services.media_uploads.configure_cloudinary")
    @mock.patch("cloudinary.api.resource")
    def test_incomplete_provider_metadata_is_rejected(
        self, resource_mock, configure_mock
    ) -> None:
        resource_mock.return_value = {"public_id": "audio_123"}

        with self.assertRaisesRegex(
            CloudinaryUploadError, "incomplete audio asset metadata"
        ):
            get_cloudinary_audio_asset(public_id="audio_123")

        configure_mock.assert_called_once_with()


class UploadVideoFromUrlTests(TestCase):
    """Phase 27's live-broadcast recording relay: Agora Cloud Recording can
    only write to S3-class storage, so the finished file is re-hosted into
    Cloudinary by URL rather than served straight from S3."""

    @mock.patch("apps.common.services.media_uploads.configure_cloudinary")
    @mock.patch("cloudinary.uploader.upload")
    def test_uploads_by_url_with_deterministic_public_id_and_default_folder(
        self, upload_mock, configure_mock
    ) -> None:
        upload_mock.return_value = {
            "public_id": "itestified/live-broadcasts/recordings/live-broadcast-42",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/live-broadcast-42.mp4",
            "resource_type": "video",
            "format": "mp4",
            "bytes": 40_000_000,
            "duration": 1800.0,
            "width": 1280,
            "height": 720,
        }

        with mock.patch.dict(os.environ, {}, clear=True):
            result = upload_video_from_url(
                source_url="https://bucket.example.com/recordings/broadcast-42.mp4",
                public_id="live-broadcast-42",
            )

        configure_mock.assert_called_once_with()
        upload_mock.assert_called_once_with(
            "https://bucket.example.com/recordings/broadcast-42.mp4",
            resource_type="video",
            type="upload",
            folder="itestified/live-broadcasts/recordings",
            public_id="live-broadcast-42",
            overwrite=True,
        )
        self.assertEqual(
            result.secure_url, "https://res.cloudinary.com/demo/video/upload/live-broadcast-42.mp4"
        )
        self.assertEqual(result.duration_ms, 1_800_000)
        self.assertTrue(result.has_visual_track)

    @mock.patch("apps.common.services.media_uploads.configure_cloudinary")
    @mock.patch("cloudinary.uploader.upload")
    def test_folder_env_override_wins(self, upload_mock, configure_mock) -> None:
        upload_mock.return_value = {
            "public_id": "custom/live-recordings/live-broadcast-1",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/live-broadcast-1.mp4",
            "resource_type": "video",
            "format": "mp4",
            "bytes": 1,
            "duration": 1,
        }
        env = {"CLOUDINARY_LIVE_BROADCAST_RECORDING_FOLDER": "custom/live-recordings"}

        with mock.patch.dict(os.environ, env, clear=True):
            upload_video_from_url(source_url="https://bucket.example.com/x.mp4", public_id="live-broadcast-1")

        upload_mock.assert_called_once_with(
            "https://bucket.example.com/x.mp4",
            resource_type="video",
            type="upload",
            folder="custom/live-recordings",
            public_id="live-broadcast-1",
            overwrite=True,
        )

    @mock.patch("apps.common.services.media_uploads.configure_cloudinary")
    @mock.patch("cloudinary.uploader.upload")
    def test_provider_failure_is_wrapped(self, upload_mock, configure_mock) -> None:
        upload_mock.side_effect = Exception("timeout")

        with self.assertRaisesRegex(CloudinaryUploadError, "Recording relay upload failed: timeout"):
            upload_video_from_url(source_url="https://bucket.example.com/x.mp4", public_id="live-broadcast-1")
