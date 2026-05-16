from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("testimonies", "0005_testimony_archived_at_testimony_publish_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="testimonycomment",
            name="parent_comment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="replies",
                to="testimonies.testimonycomment",
            ),
        ),
    ]

