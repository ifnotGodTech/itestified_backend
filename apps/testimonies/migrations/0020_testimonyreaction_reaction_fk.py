import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """TestimonyReaction now points at a Reaction by key. The column keeps
    its name and values (the three seeded keys), so no data moves."""

    dependencies = [("testimonies", "0019_seed_default_reactions")]

    operations = [
        migrations.RenameField(model_name="testimonyreaction", old_name="reaction_type", new_name="reaction"),
        migrations.AlterField(
            model_name="testimonyreaction",
            name="reaction",
            field=models.ForeignKey(
                db_column="reaction_type",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="responses",
                to="testimonies.reaction",
                to_field="key",
            ),
        ),
    ]
