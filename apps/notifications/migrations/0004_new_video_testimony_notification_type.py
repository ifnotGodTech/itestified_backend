from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0003_alter_usernotification_notification_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usernotification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("testimony_submitted", "Testimony Submitted"),
                    ("testimony_approved", "Testimony Approved"),
                    ("testimony_rejected", "Testimony Rejected"),
                    ("testimony_comment", "Testimony Comment"),
                    ("new_video_testimony", "New Video Testimony"),
                ],
                max_length=40,
            ),
        ),
    ]
