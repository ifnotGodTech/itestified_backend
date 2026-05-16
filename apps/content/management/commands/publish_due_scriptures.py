from django.core.management.base import BaseCommand

from apps.content.services.commands import publish_due_scheduled_scriptures


class Command(BaseCommand):
    help = "Publish scheduled scripture entries whose date is due."

    def handle(self, *args, **options):
        published_count = publish_due_scheduled_scriptures()
        self.stdout.write(
            self.style.SUCCESS(
                f"Published {published_count} scheduled scripture entr{'y' if published_count == 1 else 'ies'}."
            )
        )
