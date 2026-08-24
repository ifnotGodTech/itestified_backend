from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.common.services.media_uploads import CloudinaryAudioAsset, CloudinaryUploadSignature
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.testimonies.models import (
    AudioUploadIntent,
    AudioUploadPolicy,
    Testimony,
    TestimonyCategory,
    TestimonyStatus,
    TestimonyType,
    TranscriptionJob,
    TranscriptionJobStatus,
)
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import (
    AdminAssignmentFactory,
    AdminRoleFactory,
    ProfileFactory,
    UserFactory,
)


class AudioTestimonyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = TestimonyCategory.objects.create(
            name="Healing",
            description="Healing testimonies",
        )

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def make_premium(self, user):
        Subscription.objects.create(
            user=user,
            amount=300000,
            payment_reference=f"SUB-AUDIO-{user.id}",
            status=SubscriptionStatus.ACTIVE,
        )

    def signature(self, *, public_id):
        return CloudinaryUploadSignature(
            cloud_name="itestified",
            api_key="key",
            timestamp=1770000000,
            folder="itestified/testimonies/audio",
            signature="signed",
            public_id=public_id,
        )

    def asset_for(self, intent, **overrides):
        values = {
            "public_id": intent.asset_public_id,
            "secure_url": f"https://res.cloudinary.com/itestified/video/upload/{intent.asset_public_id}.m4a",
            "resource_type": "video",
            "format": "m4a",
            "file_size_bytes": 2 * 1024 * 1024,
            "duration_ms": 120000,
            "width": 0,
            "height": 0,
        }
        values.update(overrides)
        return CloudinaryAudioAsset(**values)

    def issue_intent(self, user):
        self.authenticate(user)
        with patch(
            "apps.testimonies.services.commands.create_direct_upload_signature"
        ) as signature_mock:
            signature_mock.side_effect = lambda **kwargs: self.signature(
                public_id=kwargs["public_id"]
            )
            response = self.client.post(
                reverse("testimony-submit-audio-signature"), {}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)
        return AudioUploadIntent.objects.get(id=response.json()["upload_intent_id"]), response

    def submit(self, intent, *, extra=None):
        payload = {
            "upload_intent_id": str(intent.id),
            "title": "God restored me",
            "category_id": self.category.id,
            "body": "My testimony",
        }
        payload.update(extra or {})
        return self.client.post(reverse("testimony-submit-audio"), payload, format="json")

    def test_audio_policy_exposes_phase_28_defaults(self):
        response = self.client.get(reverse("audio-upload-policy"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["max_file_size_bytes"], 50 * 1024 * 1024)
        self.assertEqual(response.json()["max_duration_ms"], 15 * 60 * 1000)
        self.assertIn("audio/mp3", response.json()["allowed_content_types"])

    def test_free_user_gets_stable_premium_required_response(self):
        user = UserFactory()
        self.authenticate(user)

        response = self.client.post(
            reverse("testimony-submit-audio-signature"), {}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "premium_required")
        self.assertFalse(AudioUploadIntent.objects.exists())

    def test_guest_cannot_request_a_signature_or_submit_audio(self):
        signature_response = self.client.post(
            reverse("testimony-submit-audio-signature"), {}, format="json"
        )
        submission_response = self.client.post(
            reverse("testimony-submit-audio"),
            {
                "upload_intent_id": "00000000-0000-0000-0000-000000000000",
                "title": "Guest upload",
                "category_id": self.category.id,
            },
            format="json",
        )

        self.assertIn(signature_response.status_code, (401, 403))
        self.assertIn(submission_response.status_code, (401, 403))
        self.assertFalse(AudioUploadIntent.objects.exists())
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
            "apps.testimonies.services.commands.get_cloudinary_audio_asset",
            return_value=verified_asset,
        ) as asset_mock:
            response = self.submit(intent)

        self.assertEqual(response.status_code, 201, response.content)
        asset_mock.assert_called_once_with(public_id=intent.asset_public_id)
        testimony = Testimony.objects.get()
        self.assertEqual(testimony.author, user)
        self.assertEqual(testimony.testimony_type, TestimonyType.AUDIO)
        self.assertEqual(testimony.status, TestimonyStatus.PENDING_REVIEW)
        self.assertEqual(testimony.audio_url, verified_asset.secure_url)
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
            "apps.testimonies.services.commands.get_cloudinary_audio_asset"
        ) as asset_mock:
            response = self.submit(
                intent,
                extra={
                    "audio_url": "https://attacker.example/fake.mp3",
                    "duration_ms": 1,
                    "file_size_bytes": 1,
                    "content_type": "audio/mpeg",
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

    def test_broker_outage_does_not_turn_valid_audio_submission_into_500(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)

        with patch(
            "apps.testimonies.services.commands.get_cloudinary_audio_asset",
            return_value=self.asset_for(intent),
        ), patch(
            "apps.testimonies.services.commands.run_transcription_job.delay",
            side_effect=RuntimeError("redis unavailable"),
        ):
            with self.assertLogs(
                "apps.testimonies.services.commands", level="ERROR"
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.submit(intent)

        self.assertEqual(response.status_code, 201, response.content)
        testimony = Testimony.objects.get()
        self.assertTrue(
            TranscriptionJob.objects.filter(
                testimony=testimony,
                status=TranscriptionJobStatus.PENDING,
            ).exists()
        )

    def test_upload_intent_cannot_be_used_by_another_user(self):
        owner = UserFactory()
        other = UserFactory()
        self.make_premium(owner)
        self.make_premium(other)
        intent, _ = self.issue_intent(owner)
        self.authenticate(other)

        with patch("apps.testimonies.services.commands.get_cloudinary_audio_asset") as asset_mock:
            response = self.submit(intent)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "audio_upload_intent_not_found")
        asset_mock.assert_not_called()

    def test_expired_upload_intent_is_rejected_before_provider_lookup(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)
        AudioUploadIntent.objects.filter(id=intent.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        with patch("apps.testimonies.services.commands.get_cloudinary_audio_asset") as asset_mock:
            response = self.submit(intent)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "audio_upload_intent_expired")
        asset_mock.assert_not_called()

    def test_upload_intent_cannot_be_consumed_twice(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)

        with patch(
            "apps.testimonies.services.commands.get_cloudinary_audio_asset",
            return_value=self.asset_for(intent),
        ):
            first_response = self.submit(intent)
        self.assertEqual(first_response.status_code, 201, first_response.content)

        with patch("apps.testimonies.services.commands.get_cloudinary_audio_asset") as asset_mock:
            second_response = self.submit(intent)

        self.assertEqual(second_response.status_code, 400)
        self.assertEqual(second_response.json()["code"], "audio_upload_intent_consumed")
        asset_mock.assert_not_called()
        self.assertEqual(Testimony.objects.count(), 1)

    def test_provider_asset_must_match_issued_public_id(self):
        user = UserFactory()
        self.make_premium(user)
        intent, _ = self.issue_intent(user)

        with patch(
            "apps.testimonies.services.commands.get_cloudinary_audio_asset",
            return_value=self.asset_for(intent, public_id="someone-elses/audio"),
        ):
            response = self.submit(intent)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "audio_upload_asset_invalid")
        self.assertFalse(Testimony.objects.exists())

    def test_provider_asset_must_be_audio_only_and_within_snapshot_policy(self):
        user = UserFactory()
        self.make_premium(user)
        policy = AudioUploadPolicy.objects.create(
            max_file_size_bytes=1024,
            max_duration_ms=1000,
            allowed_content_types=["audio/mpeg"],
        )
        intent, _ = self.issue_intent(user)
        policy.max_file_size_bytes = 50 * 1024 * 1024
        policy.max_duration_ms = 15 * 60 * 1000
        policy.save()

        invalid_assets = (
            self.asset_for(intent, width=1920, height=1080, format="mp4"),
            self.asset_for(intent, file_size_bytes=1025, duration_ms=500, format="mp3"),
            self.asset_for(intent, file_size_bytes=500, duration_ms=1001, format="mp3"),
            self.asset_for(intent, file_size_bytes=500, duration_ms=500, format="wav"),
        )
        for asset in invalid_assets:
            with self.subTest(asset=asset):
                with patch(
                    "apps.testimonies.services.commands.get_cloudinary_audio_asset",
                    return_value=asset,
                ):
                    response = self.submit(intent)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "audio_upload_asset_invalid")
                self.assertFalse(Testimony.objects.exists())

    def test_policy_changes_apply_to_future_intents_without_mutating_existing_intents(self):
        user = UserFactory()
        self.make_premium(user)
        policy = AudioUploadPolicy.objects.create()

        original_intent, _ = self.issue_intent(user)
        policy.max_file_size_bytes = 25 * 1024 * 1024
        policy.max_duration_ms = 8 * 60 * 1000
        policy.allowed_content_types = ["audio/mpeg", "audio/mp3"]
        policy.save()
        future_intent, future_response = self.issue_intent(user)

        original_intent.refresh_from_db()
        self.assertEqual(original_intent.max_file_size_bytes, 50 * 1024 * 1024)
        self.assertEqual(original_intent.max_duration_ms, 15 * 60 * 1000)
        self.assertEqual(future_intent.max_file_size_bytes, 25 * 1024 * 1024)
        self.assertEqual(future_intent.max_duration_ms, 8 * 60 * 1000)
        self.assertEqual(
            future_response.json()["policy"]["allowed_content_types"],
            ["audio/mpeg", "audio/mp3"],
        )

    def test_approved_audio_is_available_in_browse_search_favorites_and_detail(self):
        author = UserFactory(email="audio-public-author@example.com")
        listener = UserFactory(email="audio-public-listener@example.com")
        audio = Testimony.objects.create(
            author=author,
            category=self.category,
            title="Audio breakthrough for public discovery",
            body="God answered me.",
            testimony_type=TestimonyType.AUDIO,
            status=TestimonyStatus.APPROVED,
            audio_url="https://res.cloudinary.com/itestified/video/upload/public-audio.m4a",
            duration_ms=93000,
        )

        browse_response = self.client.get(reverse("testimony-list"))
        search_response = self.client.get(
            reverse("testimony-list"), {"search": "public discovery"}
        )
        detail_response = self.client.get(
            reverse("testimony-detail", kwargs={"pk": audio.id})
        )

        self.assertEqual(browse_response.status_code, 200)
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        for payload in (
            next(row for row in browse_response.json()["results"] if row["id"] == audio.id),
            search_response.json()["results"][0],
            detail_response.json(),
        ):
            self.assertEqual(payload["testimony_type"], TestimonyType.AUDIO)
            self.assertEqual(payload["audio_url"], audio.audio_url)
            self.assertEqual(payload["duration_ms"], audio.duration_ms)

        self.authenticate(listener)
        favorite_response = self.client.post(
            reverse("testimony-favorite-toggle", kwargs={"testimony_id": audio.id}),
            {},
            format="json",
        )
        favorites_response = self.client.get(reverse("testimony-favorite-feed"))

        self.assertEqual(favorite_response.status_code, 201)
        self.assertEqual(favorites_response.status_code, 200)
        favorite = favorites_response.json()["results"][0]
        self.assertEqual(favorite["id"], audio.id)
        self.assertEqual(favorite["testimony_type"], TestimonyType.AUDIO)
        self.assertEqual(favorite["audio_url"], audio.audio_url)


class AdminAudioUploadPolicyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = UserFactory(email="audio-policy-admin@example.com")
        ProfileFactory(user=self.admin, full_name="Audio Policy Admin")
        AdminAssignmentFactory(
            user=self.admin,
            role=AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN),
        )

    def test_active_admin_can_read_defaults_and_update_human_configured_limits(self):
        self.client.force_login(self.admin)
        url = reverse("admin-audio-upload-policy")

        initial = self.client.get(url)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["max_file_size_bytes"], 50 * 1024 * 1024)
        self.assertEqual(initial.json()["max_duration_ms"], 15 * 60 * 1000)

        response = self.client.patch(
            url,
            {
                "max_file_size_bytes": 75 * 1024 * 1024,
                "max_duration_ms": 20 * 60 * 1000,
                "allowed_content_types": ["audio/mpeg", "audio/mp3", "audio/aac"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["max_file_size_bytes"], 75 * 1024 * 1024)
        self.assertEqual(response.json()["max_duration_ms"], 20 * 60 * 1000)
        self.assertEqual(response.json()["updated_by_email"], self.admin.email)
        self.assertEqual(response.json()["updated_by_name"], "Audio Policy Admin")

    def test_policy_rejects_empty_unsupported_and_out_of_range_values(self):
        self.client.force_login(self.admin)
        url = reverse("admin-audio-upload-policy")
        invalid_payloads = (
            ({"allowed_content_types": []}, "allowed_content_types"),
            ({"allowed_content_types": ["audio/wav"]}, "allowed_content_types"),
            ({"max_file_size_bytes": 1024}, "max_file_size_bytes"),
            ({"max_file_size_bytes": 501 * 1024 * 1024}, "max_file_size_bytes"),
            ({"max_duration_ms": 1000}, "max_duration_ms"),
            ({"max_duration_ms": 121 * 60 * 1000}, "max_duration_ms"),
        )
        for payload, field in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.patch(url, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())

    def test_policy_requires_an_active_admin_session(self):
        url = reverse("admin-audio-upload-policy")
        self.assertIn(self.client.get(url).status_code, (401, 403))

        regular_user = UserFactory(email="not-an-admin@example.com")
        self.client.force_login(regular_user)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_public_policy_does_not_expose_admin_identity(self):
        AudioUploadPolicy.objects.create(updated_by=self.admin)

        response = self.client.get(reverse("audio-upload-policy"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("updated_by_email", response.json())
        self.assertNotIn("updated_by_name", response.json())
