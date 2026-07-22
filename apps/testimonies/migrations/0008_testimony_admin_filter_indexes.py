from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("testimonies", "0007_add_draft_status_choice"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="testimony",
            index=models.Index(
                fields=["testimony_type", "status", "-created_at"],
                name="testim_type_status_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="testimony",
            index=models.Index(
                fields=["category", "status", "-created_at"],
                name="testim_cat_status_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="testimony",
            index=models.Index(
                fields=["-created_at", "id"],
                name="testim_created_id_idx",
            ),
        ),
    ]
