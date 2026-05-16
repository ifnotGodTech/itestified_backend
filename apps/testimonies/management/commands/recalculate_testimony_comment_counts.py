from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.testimonies.models import Testimony


class Command(BaseCommand):
    help = "Recalculate testimony comment_count values from TestimonyComment rows."

    def handle(self, *args, **options):
        annotated = Testimony.objects.annotate(computed_comment_count=Count("comments"))
        updated = 0

        for testimony in annotated.iterator():
            computed = testimony.computed_comment_count
            if testimony.comment_count != computed:
                testimony.comment_count = computed
                testimony.save(update_fields=["comment_count"])
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Recalculated comment_count for {annotated.count()} testimonies; updated {updated} rows."
            )
        )
