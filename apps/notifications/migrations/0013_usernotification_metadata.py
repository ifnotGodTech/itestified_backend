from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0012_alter_usernotification_notification_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="usernotification",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
