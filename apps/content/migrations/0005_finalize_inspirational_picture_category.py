from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0004_backfill_inspirational_picture_category"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="inspirationalpicture",
            name="category",
        ),
        migrations.RenameField(
            model_name="inspirationalpicture",
            old_name="category_fk",
            new_name="category",
        ),
    ]
