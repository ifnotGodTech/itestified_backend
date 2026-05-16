from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testimonies", "0003_testimonycomment"),
    ]

    operations = [
        migrations.AddField(
            model_name="testimony",
            name="rejection_reason",
            field=models.TextField(blank=True),
        ),
    ]
