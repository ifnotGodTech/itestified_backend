from django.db import migrations
from django.db.models import Count

# Phase 15's three reactions become the default set, in their old order.
DEFAULT_SET = [
    ("praying_for_you", "Praying for you", "pray"),
    ("amen", "Amen", "raised_hands"),
    ("gives_me_hope", "Gives me hope", "sparkles"),
]


def seed_and_backfill(apps, schema_editor):
    Reaction = apps.get_model("testimonies", "Reaction")
    TestimonyReaction = apps.get_model("testimonies", "TestimonyReaction")
    TestimonyReactionCount = apps.get_model("testimonies", "TestimonyReactionCount")

    reactions = {}
    for position, (key, label, icon) in enumerate(DEFAULT_SET, start=1):
        reactions[key], _ = Reaction.objects.get_or_create(
            key=key, defaults={"label": label, "icon": icon, "default_position": position}
        )

    # Counted from the reaction rows themselves rather than copied from the
    # old columns, which could have drifted (see recount_testimony_counters).
    rows = (
        TestimonyReaction.objects.values("testimony_id", "reaction_type")
        .annotate(n=Count("id"))
        .order_by()
    )
    TestimonyReactionCount.objects.bulk_create(
        [
            TestimonyReactionCount(
                testimony_id=row["testimony_id"], reaction=reactions[row["reaction_type"]], count=row["n"]
            )
            for row in rows
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )


def unseed(apps, schema_editor):
    apps.get_model("testimonies", "TestimonyReactionCount").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("testimonies", "0018_reaction_catalogue")]

    operations = [migrations.RunPython(seed_and_backfill, unseed)]
