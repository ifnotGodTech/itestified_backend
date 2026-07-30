from django.core.management.base import BaseCommand

from apps.content.services.commands import send_scripture_streak_reminders


class Command(BaseCommand):
    help = "Push a once-daily reminder to every active user who hasn't read today's Scripture of the Day yet."

    def handle(self, *args, **options):
        targeted_count = send_scripture_streak_reminders()
        self.stdout.write(
            self.style.SUCCESS(
                f"Targeted {targeted_count} user{'s' if targeted_count != 1 else ''} with a scripture streak reminder."
            )
        )
