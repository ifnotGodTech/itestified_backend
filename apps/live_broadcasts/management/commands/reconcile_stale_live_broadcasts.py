from django.core.management.base import BaseCommand

from apps.live_broadcasts.services.commands import reconcile_stale_live_broadcasts


class Command(BaseCommand):
    help = "End any LiveBroadcast still marked LIVE well past its own publish token's expiry (a dropped stream)."

    def handle(self, *args, **options):
        ended_count = reconcile_stale_live_broadcasts()
        self.stdout.write(self.style.SUCCESS(f"Ended {ended_count} stale live broadcast(s)."))
