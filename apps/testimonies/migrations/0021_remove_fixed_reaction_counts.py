from django.db import migrations


class Migration(migrations.Migration):
    """Phase 15's three fixed count columns, replaced by
    TestimonyReactionCount (backfilled in 0019)."""

    dependencies = [("testimonies", "0020_testimonyreaction_reaction_fk")]

    operations = [
        migrations.RemoveField(model_name="testimony", name="praying_for_you_count"),
        migrations.RemoveField(model_name="testimony", name="amen_count"),
        migrations.RemoveField(model_name="testimony", name="gives_me_hope_count"),
    ]
