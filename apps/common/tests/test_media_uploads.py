import os
from unittest import mock

from django.test import TestCase

from apps.common.services.media_uploads import (
    CloudinaryUploadError,
    create_direct_upload_signature,
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

    def test_unsupported_resource_type_raises(self) -> None:
        with mock.patch.dict(os.environ, _cloudinary_env(), clear=True):
            with self.assertRaises(CloudinaryUploadError):
                create_direct_upload_signature(resource_type="bogus")

    def test_missing_credentials_raises(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CloudinaryUploadError):
                create_direct_upload_signature(resource_type="avatar")
