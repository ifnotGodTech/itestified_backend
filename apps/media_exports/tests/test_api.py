import os
from unittest.mock import patch

from rest_framework.test import APIClient
from django.test import TestCase
from django.urls import reverse

from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory

from ..models import MediaExportBrandingConfig
from ..services import CUSTOM_LOGO_PUBLIC_ID


class MediaExportApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.testimony = Testimony.objects.create(
            author=self.user,
            category=category,
            title="A testimony",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.APPROVED,
            video_url="https://res.cloudinary.com/example/video/upload/test.mp4",
        )

    def test_mobile_export_request_requires_token_auth(self):
        response = self.client.post(
            reverse("mobile-branded-video-export", kwargs={"testimony_id": self.testimony.id})
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_can_read_and_update_branding(self):
        admin = UserFactory()
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=admin, role=role)
        self.client.force_login(admin)

        response = self.client.put(
            reverse("admin-media-export-branding"),
            {"watermark_text": "From iTestified", "call_to_action": "Get the app"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["call_to_action"], "Get the app")
        self.assertEqual(MediaExportBrandingConfig.objects.get(pk=1).version, 2)
        # Always present regardless of whether logo_url is set, so the
        # dashboard can offer it as a real option rather than hardcoding it.
        self.assertTrue(response.data["default_logo_url"].startswith("https://"))

    def test_logo_upload_signature_requires_admin(self):
        response = self.client.post(reverse("admin-media-export-logo-upload-signature"))
        self.assertEqual(response.status_code, 403)

    def test_logo_upload_signature_targets_a_fixed_overwritable_public_id(self):
        admin = UserFactory()
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=admin, role=role)
        self.client.force_login(admin)

        env = {
            "CLOUDINARY_CLOUD_NAME": "demo-cloud",
            "CLOUDINARY_API_KEY": "demo-key",
            "CLOUDINARY_API_SECRET": "demo-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            response = self.client.post(reverse("admin-media-export-logo-upload-signature"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["public_id"], CUSTOM_LOGO_PUBLIC_ID)
        self.assertTrue(response.data["overwrite"])
        self.assertEqual(response.data["cloud_name"], "demo-cloud")
