from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.common.services.media_uploads import CloudinaryUploadSignature, CloudinaryVideoAsset
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyStatus,
    TestimonyType,
    TranscriptionJob,
    TranscriptionJobStatus,
    VideoUploadIntent,
    VideoUploadPolicy,
    VideoUploadPolicyHistory,
)
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import (
    AdminAssignmentFactory,
    AdminRoleFactory,
    ProfileFactory,
    UserFactory,
)


class VideoTestimonyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = TestimonyCategory.objects.create(
            name="Deliverance",
            description="Deliverance testimonies",
        )

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def make_premium(self, user):
        Subscription.objects.create(
            user=user,
            amount=300000,
            payment_reference=f"SUB-VIDEO-{user.id}",
            status=SubscriptionStatus.ACTIVE,
        )

    def signature(self, *, public_id):
        return CloudinaryUploadSignature(
            cloud_name="itestified",
            api_key="key",
            timestamp=1770000000,
            folder="itestified/testimonies/videos",
            signature="signed",
            public_id=public_id,
        )

    def asset_for(self, intent, **overrides):
        values = {
            "public_id": intent.asset_public_id,
            "secure_url": f"https://res.cloudinary.com/itestified/video/upload/{intent.asset_public_id}.mp4",
            "resource_type": "video",
            "format": "mp4",
            "file_size_bytes": 80 * 1024 * 1024,
            "duration_ms": 180000,
            "width": 1080,
            "height": 1920,
        }
        values.update(overrides)
        return CloudinaryVideoAsset(**values)

    def issue_intent(self, user):
        self.authenticate(user)
        with patch(
            "apps.testimonies.services.commands.create_direct_upload_signature"
        ) as signature_mock:
            signature_mock.side_effect = lambda **kwargs: self.signature(
                public_id=kwargs["public_id"]
            )
            response = self.client.post(
                reverse("testimony-submit-video-signature"), {}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)
        return VideoUploadIntent.objects.get(id=response.json()["upload_intent_id"]), response

    def submit(self, intent, *, extra=None):
        payload = {
            "upload_intent_id": str(intent.id),
            "title": "God set me free",
            "category_id": self.category.id,
            "body": "My testimony",
        }
        payload.update(extra or {})
        return self.client.post(reverse("testimony-submit-video"), payload, format="json")

    def test_video_policy_exposes_phase_32_defaults(self):
        response = self.client.get(reverse("video-upload-policy"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["max_file_size_bytes"], 200 * 1024 * 1024)
        self.assertEqual(response.json()["max_duration_ms"], 5 * 60 * 1000)
        self.assertEqual(response.json()["daily_limit"], 3)
        self.assertIn("video/mp4", response.json()["allowed_content_types"])

    def test_free_user_gets_stable_premium_required_response(self):
        user = UserFactory()
        self.authenticate(user)

        response = self.client.post(
            reverse("testimony-submit-video-signature"), {}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "premium_required")
        self.assertFalse(VideoUploadIntent.objects.exists())

    def test_guest_cannot_request_a_signature_or_submit_video(self):
        signature_response = self.client.post(
            reverse("testimony-submit-video-signature"), {}, format="json"
        )
        submission_response = self.client.post(
            reverse("testimony-submit-video"),
            {
                "upload_intent_id": "00000000-0000-0000-0000-000000000000",
                "title": "Guest upload",
                "category_id": self.category.id,
            },
            format="json",
        )

        self.assertIn(signature_response.status_code, (401, 403))
        self.assertIn(submission_response.status_code, (401, 403))
        self.assertFalse(VideoUploadIntent.objects.exists())
        self.assertFalse(Testimony.objects.exists())

    def test_signature_creates_single_use_intent_and_uses_cloudinary_video_endpoint(self):
        user = UserFactory()
        self.make_premium(user)

        intent, response = self.issue_intent(user)

        payload = response.json()
        self.assertEqual(payload["resource_type"], "video")
        self.assertEqual(payload["upload_resource_type"], "video")
        self.assertEqual(payload["public_id"], intent.public_id)
        self.assertEqual(payload["folder"], intent.folder)
        self.assertEqual(payload["policy"]["max_file_size_bytes"], intent.max_file_size_bytes)
        self.assertGreater(intent.expires_at, timezone.now())
        self.assertIsNone(intent.consumed_at)

    def test_final_submission_uses_verified_provider_metadata(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)
        verified_asset = self.asset_for(intent)

        with patch(
            "apps.testimonies.services.commands.get_cloudinary_video_asset",
            return_value=verified_asset,
        ) as asset_mock:
            response = self.submit(intent)

        self.assertEqual(response.status_code, 201, response.content)
        asset_mock.assert_called_once_with(public_id=intent.asset_public_id)
        testimony = Testimony.objects.get()
        self.assertEqual(testimony.author, user)
        self.assertEqual(testimony.testimony_type, TestimonyType.VIDEO)
        self.assertEqual(testimony.status, TestimonyStatus.PENDING_REVIEW)
        self.assertEqual(testimony.video_url, verified_asset.secure_url)
        self.assertEqual(testimony.duration_ms, verified_asset.duration_ms)
        self.assertTrue(
            TranscriptionJob.objects.filter(
                testimony=testimony,
                status=TranscriptionJobStatus.PENDING,
            ).exists()
        )
        intent.refresh_from_db()
        self.assertEqual(intent.testimony, testimony)
        self.assertIsNotNone(intent.consumed_at)

    def test_client_supplied_url_and_media_metadata_are_rejected(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)

        with patch(
            "apps.testimonies.services.commands.get_cloudinary_video_asset"
        ) as asset_mock:
            response = self.submit(
                intent,
                extra={
                    "video_url": "https://attacker.example/fake.mp4",
                    "duration_ms": 1,
                    "file_size_bytes": 1,
                    "content_type": "video/mp4",
                },
            )

        self.assertEqual(response.status_code, 400)
        asset_mock.assert_not_called()
        self.assertFalse(Testimony.objects.exists())

    def test_final_submission_rechecks_premium_entitlement(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)
        Subscription.objects.filter(user=user).update(status=SubscriptionStatus.EXPIRED)

        response = self.submit(intent)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "premium_required")
        self.assertFalse(Testimony.objects.exists())

    def test_upload_intent_cannot_be_used_by_another_user(self):
        owner = UserFactory()
        other = UserFactory()
        self.make_premium(owner)
        self.make_premium(other)
        intent, _ = self.issue_intent(owner)
        self.authenticate(other)

        with patch("apps.testimonies.services.commands.get_cloudinary_video_asset") as asset_mock:
            response = self.submit(intent)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "video_upload_intent_not_found")
        asset_mock.assert_not_called()

    def test_expired_upload_intent_is_rejected_before_provider_lookup(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)
        VideoUploadIntent.objects.filter(id=intent.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        with patch("apps.testimonies.services.commands.get_cloudinary_video_asset") as asset_mock:
            response = self.submit(intent)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "video_upload_intent_expired")
        asset_mock.assert_not_called()

    def test_upload_intent_cannot_be_consumed_twice(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)

        with patch(
            "apps.testimonies.services.commands.get_cloudinary_video_asset",
            return_value=self.asset_for(intent),
        ):
            first_response = self.submit(intent)
        self.assertEqual(first_response.status_code, 201, first_response.content)

        with patch("apps.testimonies.services.commands.get_cloudinary_video_asset") as asset_mock:
            second_response = self.submit(intent)

        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(second_response.json()["code"], "video_upload_intent_consumed")
        asset_mock.assert_not_called()
        self.assertEqual(Testimony.objects.count(), 1)

    def test_provider_asset_must_match_issued_public_id(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)

        with patch(
            "apps.testimonies.services.commands.get_cloudinary_video_asset",
            return_value=self.asset_for(intent, public_id="someone-elses/video"),
        ):
            response = self.submit(intent)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "video_upload_asset_invalid")
        self.assertFalse(Testimony.objects.exists())

    def test_oversized_or_invalid_asset_is_rejected_and_deleted_from_cloudinary(self):
        user = UserFactory()
        self.make_premium(user)
        policy = VideoUploadPolicy.objects.create(
            max_file_size_bytes=1024,
            max_duration_ms=1000,
            allowed_content_types=["video/mp4"],
        )
        intent, _ = self.issue_intent(user)
        policy.max_file_size_bytes = 200 * 1024 * 1024
        policy.max_duration_ms = 5 * 60 * 1000
        policy.save()

        invalid_assets = (
            self.asset_for(intent, width=0, height=0),
            self.asset_for(intent, file_size_bytes=1025, duration_ms=500),
            self.asset_for(intent, file_size_bytes=500, duration_ms=1001),
            self.asset_for(intent, file_size_bytes=500, duration_ms=500, format="avi"),
        )
        for asset in invalid_assets:
            with self.subTest(asset=asset):
                intent.consumed_at = None
                intent.testimony = None
                intent.save(update_fields=("consumed_at", "testimony"))
                with patch(
                    "apps.testimonies.services.commands.get_cloudinary_video_asset",
                    return_value=asset,
                ), patch(
                    "apps.testimonies.services.commands.delete_cloudinary_asset"
                ) as delete_mock:
                    response = self.submit(intent)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "video_upload_asset_invalid")
                self.assertFalse(Testimony.objects.exists())
                delete_mock.assert_called_once_with(public_id=intent.asset_public_id)

    def test_daily_limit_blocks_further_signatures_and_resets_are_isolated_from_audio(self):
        user = UserFactory()
        self.make_premium(user)
        VideoUploadPolicy.objects.create(daily_limit=2)

        for _ in range(2):
            intent, _ = self.issue_intent(user)
            with patch(
                "apps.testimonies.services.commands.get_cloudinary_video_asset",
                return_value=self.asset_for(intent),
            ):
                response = self.submit(intent)
            self.assertEqual(response.status_code, 201, response.content)

        blocked_response = self.client.post(
            reverse("testimony-submit-video-signature"), {}, format="json"
        )

        self.assertEqual(blocked_response.status_code, 429)
        self.assertEqual(blocked_response.json()["code"], "video_daily_limit_reached")
        self.assertEqual(Testimony.objects.filter(testimony_type=TestimonyType.VIDEO).count(), 2)

    def test_policy_changes_apply_to_future_intents_without_mutating_existing_intents(self):
        user = UserFactory()
        self.make_premium(user)
        policy = VideoUploadPolicy.objects.create()

        original_intent, _ = self.issue_intent(user)
        policy.max_file_size_bytes = 100 * 1024 * 1024
        policy.max_duration_ms = 3 * 60 * 1000
        policy.allowed_content_types = ["video/mp4"]
        policy.save()
        future_intent, future_response = self.issue_intent(user)

        original_intent.refresh_from_db()
        self.assertEqual(original_intent.max_file_size_bytes, 200 * 1024 * 1024)
        self.assertEqual(original_intent.max_duration_ms, 5 * 60 * 1000)
        self.assertEqual(future_intent.max_file_size_bytes, 100 * 1024 * 1024)
        self.assertEqual(future_intent.max_duration_ms, 3 * 60 * 1000)
        self.assertEqual(
            future_response.json()["policy"]["allowed_content_types"],
            ["video/mp4"],
        )

    def test_approved_video_is_watchable_by_everyone_including_guests(self):
        author = UserFactory(email="video-public-author@example.com")
        video = Testimony.objects.create(
            author=author,
            category=self.category,
            title="Video breakthrough for public discovery",
            body="God answered me.",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.APPROVED,
            video_url="https://res.cloudinary.com/itestified/video/upload/public-video.mp4",
            duration_ms=93000,
        )

        browse_response = self.client.get(reverse("testimony-list"))
        detail_response = self.client.get(
            reverse("testimony-detail", kwargs={"pk": video.id})
        )

        self.assertEqual(browse_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["testimony_type"], TestimonyType.VIDEO)
        self.assertEqual(detail_response.json()["video_url"], video.video_url)


class AdminVideoUploadPolicyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = UserFactory(email="video-policy-admin@example.com")
        ProfileFactory(user=self.admin, full_name="Video Policy Admin")
        AdminAssignmentFactory(
            user=self.admin,
            role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN),
        )

    def test_active_admin_can_read_defaults_and_update_human_configured_limits(self):
        self.client.force_login(self.admin)
        url = reverse("admin-video-upload-policy")

        initial = self.client.get(url)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["max_file_size_bytes"], 200 * 1024 * 1024)
        self.assertEqual(initial.json()["max_duration_ms"], 5 * 60 * 1000)
        self.assertEqual(initial.json()["daily_limit"], 3)

        response = self.client.patch(
            url,
            {
                "max_file_size_bytes": 150 * 1024 * 1024,
                "max_duration_ms": 4 * 60 * 1000,
                "allowed_content_types": ["video/mp4"],
                "daily_limit": 5,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["max_file_size_bytes"], 150 * 1024 * 1024)
        self.assertEqual(response.json()["daily_limit"], 5)
        self.assertEqual(response.json()["updated_by_email"], self.admin.email)
        self.assertEqual(response.json()["updated_by_name"], "Video Policy Admin")

    def test_update_records_one_history_row_per_changed_field(self):
        self.client.force_login(self.admin)
        url = reverse("admin-video-upload-policy")

        response = self.client.patch(
            url,
            {"max_file_size_bytes": 150 * 1024 * 1024, "daily_limit": 3},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        history = list(VideoUploadPolicyHistory.objects.all())
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].field_name, "max_file_size_bytes")
        self.assertEqual(history[0].to_value, str(150 * 1024 * 1024))
        self.assertEqual(history[0].actor, self.admin)

    def test_policy_rejects_empty_unsupported_and_out_of_range_values(self):
        self.client.force_login(self.admin)
        url = reverse("admin-video-upload-policy")
        invalid_payloads = (
            ({"allowed_content_types": []}, "allowed_content_types"),
            ({"allowed_content_types": ["video/avi"]}, "allowed_content_types"),
            ({"max_file_size_bytes": 1024}, "max_file_size_bytes"),
            ({"max_file_size_bytes": 3 * 1024 * 1024 * 1024}, "max_file_size_bytes"),
            ({"max_duration_ms": 1000}, "max_duration_ms"),
            ({"max_duration_ms": 61 * 60 * 1000}, "max_duration_ms"),
            ({"daily_limit": 0}, "daily_limit"),
            ({"daily_limit": 51}, "daily_limit"),
        )
        for payload, field in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.patch(url, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())

    def test_policy_requires_an_active_admin_session(self):
        url = reverse("admin-video-upload-policy")
        self.assertIn(self.client.get(url).status_code, (401, 403))

        regular_user = UserFactory(email="not-an-admin@example.com")
        self.client.force_login(regular_user)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_public_policy_does_not_expose_admin_identity(self):
        VideoUploadPolicy.objects.create(updated_by=self.admin)

        response = self.client.get(reverse("video-upload-policy"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("updated_by_email", response.json())
        self.assertNotIn("updated_by_name", response.json())
