from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.testimonies.services.commands import redispatch_stranded_transcription_jobs


class Command(BaseCommand):
    help = "Redispatch old pending transcription jobs and recover stale processing jobs."

    def add_arguments(self, parser):
        parser.add_argument("--pending-older-than-seconds", type=int, default=60)
        parser.add_argument("--processing-older-than-seconds", type=int, default=1800)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        pending_seconds = options["pending_older_than_seconds"]
        processing_seconds = options["processing_older_than_seconds"]
        limit = options["limit"]
        if pending_seconds < 0 or processing_seconds < 0 or limit <= 0:
            raise CommandError("Age thresholds must be non-negative and limit must be positive.")

        attempted, published = redispatch_stranded_transcription_jobs(
            pending_older_than=timedelta(seconds=pending_seconds),
            processing_older_than=timedelta(seconds=processing_seconds),
            limit=limit,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Transcription redispatch attempted={attempted} published={published}."
            )
        )
