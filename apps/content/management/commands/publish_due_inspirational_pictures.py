from django.core.management.base import BaseCommand

from apps.content.services.commands import publish_due_scheduled_inspirational_pictures


class Command(BaseCommand):
    help = "Publish scheduled inspirational pictures whose publish time is due."

    def handle(self, *args, **options):
        published_count = publish_due_scheduled_inspirational_pictures()
        self.stdout.write(
            self.style.SUCCESS(
                f"Published {published_count} scheduled inspirational picture"
                f"{'' if published_count == 1 else 's'}."
            )
        )
