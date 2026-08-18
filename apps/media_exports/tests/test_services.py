from unittest.mock import patch

from django.test import TestCase

from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.tests.factories import UserFactory

from ..models import BrandedVideoExportStatus, MediaExportBrandingConfig
from ..services import MediaExportError, request_branded_video_export


class BrandedExportServiceTests(TestCase):
    def setUp(self):
        self.author = UserFactory()
        self.category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.testimony = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="A testimony",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.APPROVED,
            video_url="https://res.cloudinary.com/example/video/upload/test.mp4",
        )

    @patch("apps.media_exports.tasks.run_branded_video_export.delay")
    def test_request_is_idempotent_and_enqueues_once(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            first = request_branded_video_export(testimony_id=self.testimony.id, requested_by=self.author)
        second = request_branded_video_export(testimony_id=self.testimony.id, requested_by=self.author)

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.status, BrandedVideoExportStatus.PENDING)
        delay.assert_called_once_with(first.id)

    def test_unapproved_or_non_video_testimony_is_rejected(self):
        self.testimony.status = TestimonyStatus.PENDING_REVIEW
        self.testimony.save(update_fields=["status"])

        with self.assertRaises(MediaExportError):
            request_branded_video_export(testimony_id=self.testimony.id)

    @patch("apps.media_exports.tasks.run_branded_video_export.delay", side_effect=RuntimeError("redis unavailable"))
    def test_broker_failure_returns_a_retryable_domain_error(self, _delay):
        with self.assertRaisesMessage(MediaExportError, "export queue is temporarily unavailable"):
            with self.captureOnCommitCallbacks(execute=True):
                request_branded_video_export(testimony_id=self.testimony.id)

    def test_branding_update_increments_version(self):
        config = MediaExportBrandingConfig.objects.create()
        original_version = config.version
        config.call_to_action = "Open iTestified"
        config.save()

        config.refresh_from_db()
        self.assertEqual(config.version, original_version + 1)
