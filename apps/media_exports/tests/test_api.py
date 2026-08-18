from rest_framework.test import APIClient
from django.test import TestCase
from django.urls import reverse

from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory

from ..models import MediaExportBrandingConfig


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
