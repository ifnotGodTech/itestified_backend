from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testimonies", "0006_testimonycomment_parent_comment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="testimony",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending_review", "Pending Review"),
                    ("scheduled", "Scheduled"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("archived", "Archived"),
                ],
                default="pending_review",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="testimonymoderationhistory",
            name="from_status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending_review", "Pending Review"),
                    ("scheduled", "Scheduled"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("archived", "Archived"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="testimonymoderationhistory",
            name="to_status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending_review", "Pending Review"),
                    ("scheduled", "Scheduled"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("archived", "Archived"),
                ],
                max_length=20,
            ),
        ),
    ]
