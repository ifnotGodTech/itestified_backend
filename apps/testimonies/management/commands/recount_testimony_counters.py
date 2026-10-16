from django.core.management.base import BaseCommand

from apps.testimonies.services.commands import recount_testimony_counters


class Command(BaseCommand):
    help = "Reset every testimony's comment_count and reaction counts from its comment and reaction rows."

    def handle(self, *args, **options):
        updated = recount_testimony_counters()
        self.stdout.write(self.style.SUCCESS(f"Recounted testimony counters; corrected {updated} testimonies."))
