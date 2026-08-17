"""Phase 22 Slice 5 -- admin visibility into transcription/translation job
failures, with a retry action. Mocks apps.common.services.ai_text's
boundary functions, never Celery itself -- CELERY_TASK_ALWAYS_EAGER runs
.delay() synchronously in-process (see test_transcription.py's own header
for the full rationale)."""

from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse

from apps.testimonies.exceptions import AIJobNotRetryableError
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
from apps.testimonies.services.commands import retry_transcription_job, retry_translation_job
from apps.common.services.ai_text import AITextServiceError
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import (
    AdminAssignmentFactory,
    AdminRoleFactory,
    ProfileFactory,
    UserFactory,
)


def _make_video_testimony(**overrides):
    category = overrides.pop("category", None) or TestimonyCategory.objects.create(
        name="Healing", slug="healing"
    )
    author = overrides.pop("author", None)
    if author is None:
        author = UserFactory(email=f"author-{uuid4().hex[:12]}@example.com")
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


class RetryTranscriptionJobCommandTests(TestCase):
    def test_retries_a_failed_job_and_it_can_succeed_this_time(self):
        testimony = _make_video_testimony()
        job = TranscriptionJob.objects.create(
            testimony=testimony,
            status=TranscriptionJobStatus.FAILED,
            error_message="Missing required environment variable: OPENAI_API_KEY",
            retry_count=1,
        )
        with patch("apps.testimonies.tasks.transcribe_video", return_value="Transcribed on retry."):
            with self.captureOnCommitCallbacks(execute=True):
                retry_transcription_job(job_id=job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, TranscriptionJobStatus.DONE)
        self.assertEqual(job.transcript, "Transcribed on retry.")
        self.assertEqual(job.error_message, "")

    def test_refuses_to_retry_a_job_that_is_not_failed(self):
        testimony = _make_video_testimony()
        job = TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.DONE)
        with self.assertRaises(AIJobNotRetryableError):
            retry_transcription_job(job_id=job.id)

    def test_raises_for_a_missing_job(self):
        with self.assertRaises(TranscriptionJob.DoesNotExist):
            retry_transcription_job(job_id=999999)


class RetryTranslationJobCommandTests(TestCase):
    def test_retries_a_failed_job_and_it_can_succeed_this_time(self):
        testimony = _make_video_testimony()
        TranscriptionJob.objects.create(
            testimony=testimony, status=TranscriptionJobStatus.DONE, transcript="Original."
        )
        testimony.refresh_from_db()
        job = TranslationJob.objects.create(
            testimony=testimony, language="fr", status=TranslationJobStatus.FAILED, error_message="boom"
        )
        with patch("apps.testimonies.tasks.translate_text", return_value="Texte."):
            with self.captureOnCommitCallbacks(execute=True):
                retry_translation_job(job_id=job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, TranslationJobStatus.DONE)
        self.assertEqual(job.translated_text, "Texte.")

    def test_refuses_to_retry_a_job_that_is_not_failed(self):
        testimony = _make_video_testimony()
        job = TranslationJob.objects.create(testimony=testimony, language="fr", status=TranslationJobStatus.PENDING)
        with self.assertRaises(AIJobNotRetryableError):
            retry_translation_job(job_id=job.id)

    def test_raises_for_a_missing_job(self):
        with self.assertRaises(TranslationJob.DoesNotExist):
            retry_translation_job(job_id=999999)


class AdminAIJobApiTestsBase(TestCase):
    def setUp(self) -> None:
        self.category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        self.admin = UserFactory(email="ai-job-admin@example.com")
        ProfileFactory(user=self.admin, full_name="AI Job Admin")
        role = AdminRoleFactory(code=AdminRoleCode.SUPER_ADMIN)
        AdminAssignmentFactory(user=self.admin, role=role)


class AdminTranscriptionJobListApiTests(AdminAIJobApiTestsBase):
    def test_requires_admin_session(self):
        response = self.client.get(reverse("admin-transcription-job-list"))
        self.assertEqual(response.status_code, 403)

    def test_lists_jobs_and_filters_by_status(self):
        testimony = _make_video_testimony(category=self.category)
        TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.FAILED, error_message="boom")
        other = _make_video_testimony(category=self.category)
        TranscriptionJob.objects.create(testimony=other, status=TranscriptionJobStatus.DONE, transcript="ok")

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-transcription-job-list"), {"status": "failed"})
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(results[0]["testimony_id"], testimony.id)
        self.assertEqual(results[0]["error_message"], "boom")

    def test_no_filter_returns_every_status(self):
        testimony = _make_video_testimony(category=self.category)
        TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.PROCESSING)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-transcription-job-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)


class AdminTranscriptionJobRetryApiTests(AdminAIJobApiTestsBase):
    def test_requires_admin_session(self):
        testimony = _make_video_testimony(category=self.category)
        job = TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.FAILED)
        response = self.client.post(reverse("admin-transcription-job-retry", kwargs={"job_id": job.id}))
        self.assertEqual(response.status_code, 403)

    def test_retries_a_failed_job(self):
        testimony = _make_video_testimony(category=self.category)
        job = TranscriptionJob.objects.create(
            testimony=testimony, status=TranscriptionJobStatus.FAILED, error_message="boom", retry_count=1
        )
        self.client.force_login(self.admin)
        with patch("apps.testimonies.tasks.transcribe_video", return_value="Fixed."):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("admin-transcription-job-retry", kwargs={"job_id": job.id}))
        self.assertEqual(response.status_code, 200)
        # The response reflects the job as it was reset at request time
        # (pending) -- the retried task only actually runs once the
        # captureOnCommitCallbacks block exits, same on_commit timing
        # documented in test_transcription.py.
        self.assertEqual(response.json()["status"], "pending")
        job.refresh_from_db()
        self.assertEqual(job.status, TranscriptionJobStatus.DONE)
        self.assertEqual(job.transcript, "Fixed.")

    def test_400_when_job_is_not_failed(self):
        testimony = _make_video_testimony(category=self.category)
        job = TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.PROCESSING)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin-transcription-job-retry", kwargs={"job_id": job.id}))
        self.assertEqual(response.status_code, 400)

    def test_404_for_a_missing_job(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin-transcription-job-retry", kwargs={"job_id": 999999}))
        self.assertEqual(response.status_code, 404)


class AdminTranslationJobListApiTests(AdminAIJobApiTestsBase):
    def test_lists_jobs_and_filters_by_status(self):
        testimony = _make_video_testimony(category=self.category)
        TranslationJob.objects.create(
            testimony=testimony, language="fr", status=TranslationJobStatus.FAILED, error_message="boom"
        )
        TranslationJob.objects.create(testimony=testimony, language="ig", status=TranslationJobStatus.DONE)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-translation-job-list"), {"status": "failed"})
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["language"], "fr")


class AdminTranslationJobRetryApiTests(AdminAIJobApiTestsBase):
    def test_retries_a_failed_job(self):
        testimony = _make_video_testimony(category=self.category)
        TranscriptionJob.objects.create(testimony=testimony, status=TranscriptionJobStatus.DONE, transcript="Original.")
        testimony.refresh_from_db()
        job = TranslationJob.objects.create(testimony=testimony, language="fr", status=TranslationJobStatus.FAILED)

        self.client.force_login(self.admin)
        with patch("apps.testimonies.tasks.translate_text", return_value="Texte."):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("admin-translation-job-retry", kwargs={"job_id": job.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")
        job.refresh_from_db()
        self.assertEqual(job.status, TranslationJobStatus.DONE)
        self.assertEqual(job.translated_text, "Texte.")

    def test_400_when_job_is_not_failed(self):
        testimony = _make_video_testimony(category=self.category)
        job = TranslationJob.objects.create(testimony=testimony, language="fr", status=TranslationJobStatus.DONE)
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin-translation-job-retry", kwargs={"job_id": job.id}))
        self.assertEqual(response.status_code, 400)
