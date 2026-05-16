from django.core.management.base import BaseCommand

from apps.testimonies.services.commands import auto_publish_due_scheduled_testimonies


class Command(BaseCommand):
    help = "Publish testimonies that are scheduled and due."

    def handle(self, *args, **options):
        published_count = auto_publish_due_scheduled_testimonies()
        self.stdout.write(self.style.SUCCESS(f"Published {published_count} scheduled testimonies."))
