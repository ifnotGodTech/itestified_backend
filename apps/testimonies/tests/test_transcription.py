"""Phase 22 Slice 1 (transcription) and Slice 2 (translation) -- backend
only. Mobile wiring is Slice 3/4, not built yet. Mocks apps.common.services
.ai_text's boundary functions (the only place OpenAI is ever called), never
Celery itself -- CELERY_TASK_ALWAYS_EAGER (config/settings/test.py) runs
.delay() synchronously in-process, so captureOnCommitCallbacks(execute=True)
exercises the real service -> Celery -> task -> AI-boundary -> DB pipeline
end-to-end without needing a live worker or a real API key."""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.testimonies.exceptions import TestimonyTranslationNotReadyError
from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyStatus,
    TestimonyType,
    TranscriptionJob,
    TranscriptionJobStatus,
    TranslationJob,
    TranslationJobStatus,
)
from apps.testimonies.services.commands import (
    enqueue_transcription_job,
    request_testimony_translation,
)
from apps.common.services.ai_text import AITextServiceError
from apps.users.tests.factories import ProfileFactory, UserFactory


def _make_video_testimony(**overrides):
    category = overrides.pop("category", None) or TestimonyCategory.objects.create(
        name="Healing", slug="healing"
    )
    author = overrides.pop("author", None)
    if author is None:
        author = UserFactory(email=f"author-{TestimonyCategory.objects.count()}@example.com")
        ProfileFactory(user=author, full_name="Author")
    defaults = dict(
        author=author,
        category=category,
        title="God healed me",
        body="",
        testimony_type=TestimonyType.VIDEO,
        status=TestimonyStatus.APPROVED,
        video_url="https://example.com/testimony.mp4",
    )
    defaults.update(overrides)
    return Testimony.objects.create(**defaults)


class EnqueueTranscriptionJobTests(TestCase):
    def test_creates_a_pending_job_and_runs_it_via_celery_on_commit(self):
        testimony = _make_video_testimony()
        with patch(
            "apps.testimonies.tasks.transcribe_video", return_value="Transcribed text."
        ) as transcribe_mock:
            with self.captureOnCommitCallbacks(execute=True):
                job = enqueue_transcription_job(testimony=testimony)

        transcribe_mock.assert_called_once_with(video_url=testimony.video_url)
        job.refresh_from_db()
        self.assertEqual(job.status, TranscriptionJobStatus.DONE)
        self.assertEqual(job.transcript, "Transcribed text.")

    def test_a_failed_ai_call_marks_the_job_failed_not_stuck_processing(self):
        testimony = _make_video_testimony()
        with patch(
            "apps.testimonies.tasks.transcribe_video",
            side_effect=AITextServiceError("Missing required environment variable: OPENAI_API_KEY"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                job = enqueue_transcription_job(testimony=testimony)

        job.refresh_from_db()
        self.assertEqual(job.status, TranscriptionJobStatus.FAILED)
        self.assertIn("OPENAI_API_KEY", job.error_message)
        self.assertEqual(job.retry_count, 1)

    def test_written_testimonies_never_get_a_job(self):
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        author = UserFactory(email="written-author@example.com")
        ProfileFactory(user=author, full_name="Written Author")
        testimony = Testimony.objects.create(
            author=author,
            category=category,
            title="A written testimony",
            body="Body text.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        with self.captureOnCommitCallbacks(execute=True):
            job = enqueue_transcription_job(testimony=testimony)

        self.assertIsNone(job)
        self.assertFalse(TranscriptionJob.objects.filter(testimony=testimony).exists())

    def test_calling_twice_does_not_duplicate_or_re_enqueue(self):
        testimony = _make_video_testimony()
        with patch("apps.testimonies.tasks.transcribe_video", return_value="Text.") as transcribe_mock:
            with self.captureOnCommitCallbacks(execute=True):
                enqueue_transcription_job(testimony=testimony)
            with self.captureOnCommitCallbacks(execute=True):
                enqueue_transcription_job(testimony=testimony)

        transcribe_mock.assert_called_once()
        self.assertEqual(TranscriptionJob.objects.filter(testimony=testimony).count(), 1)


class RequestTestimonyTranslationTests(TestCase):
    def _testimony_with_done_transcript(self, transcript="Original transcript text."):
        testimony = _make_video_testimony()
        TranscriptionJob.objects.create(
            testimony=testimony,
            status=TranscriptionJobStatus.DONE,
            transcript=transcript,
        )
        testimony.refresh_from_db()
        return testimony

    def test_raises_when_no_completed_transcript_exists(self):
        testimony = _make_video_testimony()
        with self.assertRaises(TestimonyTranslationNotReadyError):
            request_testimony_translation(testimony=testimony, language="fr")
        self.assertFalse(TranslationJob.objects.filter(testimony=testimony).exists())

    def test_raises_while_transcript_is_still_processing(self):
        testimony = _make_video_testimony()
        TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.PROCESSING)
        testimony.refresh_from_db()
        with self.assertRaises(TestimonyTranslationNotReadyError):
            request_testimony_translation(testimony=testimony, language="fr")

    def test_translates_the_transcript_and_caches_the_result(self):
        testimony = self._testimony_with_done_transcript()
        with patch(
            "apps.testimonies.tasks.translate_text", return_value="Texte traduit."
        ) as translate_mock:
            with self.captureOnCommitCallbacks(execute=True):
                job = request_testimony_translation(testimony=testimony, language="fr")

        translate_mock.assert_called_once_with(text="Original transcript text.", target_language="fr")
        job.refresh_from_db()
        self.assertEqual(job.status, TranslationJobStatus.DONE)
        self.assertEqual(job.translated_text, "Texte traduit.")

    def test_a_repeat_request_for_a_done_language_reuses_it_without_calling_the_api_again(self):
        testimony = self._testimony_with_done_transcript()
        with patch("apps.testimonies.tasks.translate_text", return_value="Texte traduit.") as translate_mock:
            with self.captureOnCommitCallbacks(execute=True):
                request_testimony_translation(testimony=testimony, language="fr")
            with self.captureOnCommitCallbacks(execute=True):
                second = request_testimony_translation(testimony=testimony, language="fr")

        translate_mock.assert_called_once()
        self.assertEqual(second.status, TranslationJobStatus.DONE)
        self.assertEqual(TranslationJob.objects.filter(testimony=testimony, language="fr").count(), 1)

    def test_a_failed_language_is_retried_on_the_next_request(self):
        testimony = self._testimony_with_done_transcript()
        with patch(
            "apps.testimonies.tasks.translate_text", side_effect=AITextServiceError("boom")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                first = request_testimony_translation(testimony=testimony, language="fr")
        # request_testimony_translation returns the job as it was at
        # enqueue time (PENDING) -- the task that flips it to FAILED only
        # actually runs once the on_commit callback fires, which happens
        # when the captureOnCommitCallbacks block above exits.
        first.refresh_from_db()
        self.assertEqual(first.status, TranslationJobStatus.FAILED)

        with patch("apps.testimonies.tasks.translate_text", return_value="Texte traduit.") as translate_mock:
            with self.captureOnCommitCallbacks(execute=True):
                second = request_testimony_translation(testimony=testimony, language="fr")

        translate_mock.assert_called_once()
        second.refresh_from_db()
        self.assertEqual(second.status, TranslationJobStatus.DONE)
        self.assertEqual(TranslationJob.objects.filter(testimony=testimony, language="fr").count(), 1)

    def test_different_languages_get_independent_jobs(self):
        testimony = self._testimony_with_done_transcript()
        with patch("apps.testimonies.tasks.translate_text", side_effect=["Texte.", "Nkwupụta."]):
            with self.captureOnCommitCallbacks(execute=True):
                request_testimony_translation(testimony=testimony, language="fr")
            with self.captureOnCommitCallbacks(execute=True):
                request_testimony_translation(testimony=testimony, language="ig")

        self.assertEqual(TranslationJob.objects.filter(testimony=testimony).count(), 2)


class RunTranscriptionJobTaskTests(TestCase):
    def test_missing_job_id_does_not_raise(self):
        from apps.testimonies.tasks import run_transcription_job

        run_transcription_job(999999)  # should just log and return


class TestimonyDetailTranscriptFieldsApiTests(TestCase):
    def setUp(self) -> None:
        self.category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.author = UserFactory(email="detail-author@example.com")
        ProfileFactory(user=self.author, full_name="Detail Author")

    def _get(self, testimony_id, user=None):
        headers = {}
        if user is not None:
            token = Token.objects.create(user=user)
            headers["HTTP_AUTHORIZATION"] = f"Token {token.key}"
        return self.client.get(reverse("testimony-detail", kwargs={"pk": testimony_id}), **headers)

    def test_written_testimony_reports_not_available(self):
        testimony = Testimony.objects.create(
            author=self.author,
            category=self.category,
            title="Written",
            body="Body.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        response = self._get(testimony.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript_status"], "not_available")
        self.assertIsNone(response.json()["transcript"])

    def test_pending_job_reports_status_with_no_content(self):
        testimony = _make_video_testimony(author=self.author, category=self.category)
        TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.PENDING)
        response = self._get(testimony.id)
        self.assertEqual(response.json()["transcript_status"], "pending")
        self.assertIsNone(response.json()["transcript"])

    def test_done_transcript_hidden_from_a_non_premium_viewer(self):
        testimony = _make_video_testimony(author=self.author, category=self.category)
        TranscriptionJob.objects.create(
            testimony=testimony, status=TranscriptionJobStatus.DONE, transcript="Secret text."
        )
        viewer = UserFactory(email="free-viewer@example.com")
        ProfileFactory(user=viewer, full_name="Free Viewer")
        response = self._get(testimony.id, user=viewer)
        self.assertEqual(response.json()["transcript_status"], "done")
        self.assertIsNone(response.json()["transcript"])

    def test_done_transcript_visible_to_a_premium_viewer(self):
        testimony = _make_video_testimony(author=self.author, category=self.category)
        TranscriptionJob.objects.create(
            testimony=testimony, status=TranscriptionJobStatus.DONE, transcript="Visible text."
        )
        viewer = UserFactory(email="premium-viewer@example.com")
        ProfileFactory(user=viewer, full_name="Premium Viewer")
        Subscription.objects.create(
            user=viewer,
            amount=300000,
            payment_reference="SUB-TRANSCRIPT-1",
            status=SubscriptionStatus.ACTIVE,
        )
        response = self._get(testimony.id, user=viewer)
        self.assertEqual(response.json()["transcript_status"], "done")
        self.assertEqual(response.json()["transcript"], "Visible text.")

    def test_done_transcript_hidden_from_a_guest(self):
        testimony = _make_video_testimony(author=self.author, category=self.category)
        TranscriptionJob.objects.create(
            testimony=testimony, status=TranscriptionJobStatus.DONE, transcript="Secret text."
        )
        response = self._get(testimony.id)
        self.assertIsNone(response.json()["transcript"])


class TestimonyTranslationApiTests(TestCase):
    def setUp(self) -> None:
        self.category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.author = UserFactory(email="translation-author@example.com")
        ProfileFactory(user=self.author, full_name="Translation Author")
        self.testimony = _make_video_testimony(author=self.author, category=self.category)

    def _auth_headers(self, user):
        token = Token.objects.create(user=user)
        return {"HTTP_AUTHORIZATION": f"Token {token.key}"}

    def _premium_user(self, email="premium@example.com"):
        user = UserFactory(email=email)
        ProfileFactory(user=user, full_name="Premium User")
        Subscription.objects.create(
            user=user, amount=300000, payment_reference=f"SUB-{email}", status=SubscriptionStatus.ACTIVE
        )
        return user

    def test_requires_authentication(self):
        response = self.client.post(
            reverse("testimony-translations", kwargs={"testimony_id": self.testimony.id}),
            {"language": "fr"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_a_non_premium_user(self):
        free_user = UserFactory(email="free@example.com")
        ProfileFactory(user=free_user, full_name="Free User")
        response = self.client.post(
            reverse("testimony-translations", kwargs={"testimony_id": self.testimony.id}),
            {"language": "fr"},
            content_type="application/json",
            **self._auth_headers(free_user),
        )
        self.assertEqual(response.status_code, 403)

    def test_404_for_a_testimony_that_does_not_exist(self):
        premium_user = self._premium_user()
        response = self.client.post(
            reverse("testimony-translations", kwargs={"testimony_id": 999999}),
            {"language": "fr"},
            content_type="application/json",
            **self._auth_headers(premium_user),
        )
        self.assertEqual(response.status_code, 404)

    def test_400_when_transcript_is_not_ready_yet(self):
        premium_user = self._premium_user()
        response = self.client.post(
            reverse("testimony-translations", kwargs={"testimony_id": self.testimony.id}),
            {"language": "fr"},
            content_type="application/json",
            **self._auth_headers(premium_user),
        )
        self.assertEqual(response.status_code, 400)

    def test_first_call_kicks_off_the_job_and_a_second_poll_returns_the_translated_text(self):
        # The task genuinely runs asynchronously -- even with Celery eager
        # mode, the .delay() call is deferred to transaction.on_commit,
        # which only fires after the view has already returned its
        # response. So the first POST's response reflects the job as it
        # was at enqueue time (pending); a second POST (mobile's polling
        # call, same endpoint per this slice's own design) finds the
        # already-DONE job and returns the real text, with no re-enqueue.
        TranscriptionJob.objects.create(
            testimony=self.testimony, status=TranscriptionJobStatus.DONE, transcript="Original text."
        )
        premium_user = self._premium_user()
        headers = self._auth_headers(premium_user)
        with patch("apps.testimonies.tasks.translate_text", return_value="Texte traduit.") as translate_mock:
            with self.captureOnCommitCallbacks(execute=True):
                first_response = self.client.post(
                    reverse("testimony-translations", kwargs={"testimony_id": self.testimony.id}),
                    {"language": "fr"},
                    content_type="application/json",
                    **headers,
                )
            self.assertEqual(first_response.status_code, 200)
            self.assertEqual(first_response.json()["status"], "pending")

            second_response = self.client.post(
                reverse("testimony-translations", kwargs={"testimony_id": self.testimony.id}),
                {"language": "fr"},
                content_type="application/json",
                **headers,
            )

        translate_mock.assert_called_once()
        self.assertEqual(second_response.status_code, 200)
        body = second_response.json()
        self.assertEqual(body["language"], "fr")
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["translated_text"], "Texte traduit.")


class VideoUploadTriggersTranscriptionApiTests(TestCase):
    def setUp(self) -> None:
        from apps.users.choices import AdminRoleCode
        from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory

        self.category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.admin = UserFactory(email="video-admin@example.com")
        ProfileFactory(user=self.admin, full_name="Video Admin")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin, role=role)
        self.client.force_login(self.admin)

    def test_create_from_url_enqueues_a_transcription_job(self):
        with patch("apps.testimonies.tasks.transcribe_video", return_value="Text."):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    reverse("admin-testimony-create-video-from-url"),
                    {
                        "title": "Video from URL",
                        "category_id": self.category.id,
                        "body": "Uploaded by admin.",
                        "video_url": "https://res.cloudinary.com/demo/video/upload/v1/t.mp4",
                        "thumbnail_url": "",
                        "upload_status": "draft",
                    },
                    content_type="application/json",
                )
        self.assertEqual(response.status_code, 201)
        testimony = Testimony.objects.get(title="Video from URL")
        job = TranscriptionJob.objects.get(testimony=testimony)
        self.assertEqual(job.status, TranscriptionJobStatus.DONE)
        self.assertEqual(job.transcript, "Text.")
