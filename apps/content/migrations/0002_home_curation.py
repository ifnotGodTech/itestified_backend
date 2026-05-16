from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("testimonies", "0005_testimony_archived_at_testimony_publish_at_and_more"),
        ("content", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="HomeSectionOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "section",
                    models.CharField(
                        choices=[
                            ("featured_testimonies", "Featured Testimonies"),
                            ("inspirational_picture", "Inspirational Picture"),
                            ("scripture", "Scripture"),
                        ],
                        max_length=40,
                        unique=True,
                    ),
                ),
                ("position", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["position", "id"]},
        ),
        migrations.CreateModel(
            name="FeaturedHomeTestimony",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="home_featured_testimonies_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "testimony",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="home_featured_entries",
                        to="testimonies.testimony",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="home_featured_testimonies_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["position", "id"]},
        ),
        migrations.AddConstraint(
            model_name="featuredhometestimony",
            constraint=models.UniqueConstraint(fields=("testimony",), name="uniq_home_featured_testimony"),
        ),
    ]

