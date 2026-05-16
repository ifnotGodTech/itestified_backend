from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("testimonies", "0002_testimonyfavorite"),
    ]

    operations = [
        migrations.CreateModel(
            name="TestimonyComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="testimony_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "testimony",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="testimonies.testimony",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
