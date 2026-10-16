import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Phase 35 Slice 6: the reaction catalogue, category sets, per-testimony
    counts and the change log. Schema only -- 0019 seeds and backfills."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("testimonies", "0017_testimony_search_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="Reaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=40, unique=True)),
                ("label", models.CharField(max_length=24)),
                (
                    "icon",
                    models.CharField(
                        choices=[
                            ("pray", "🙏"),
                            ("raised_hands", "🙌"),
                            ("sparkles", "✨"),
                            ("handshake", "🤝"),
                            ("heart", "💜"),
                            ("fire", "🔥"),
                            ("dove", "🕊️"),
                            ("sprout", "🌱"),
                            ("strength", "💪"),
                            ("celebrate", "🎉"),
                            ("love", "❤️"),
                            ("star", "⭐"),
                        ],
                        max_length=20,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("default_position", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.AddConstraint(
            model_name="reaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(default_position__isnull=False),
                fields=("default_position",),
                name="uniq_reaction_default_position",
            ),
        ),
        migrations.CreateModel(
            name="CategoryReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveSmallIntegerField()),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reaction_set",
                        to="testimonies.testimonycategory",
                    ),
                ),
                (
                    "reaction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="category_sets",
                        to="testimonies.reaction",
                    ),
                ),
            ],
            options={"ordering": ["category_id", "position"]},
        ),
        migrations.AddConstraint(
            model_name="categoryreaction",
            constraint=models.UniqueConstraint(fields=("category", "reaction"), name="uniq_category_reaction"),
        ),
        migrations.AddConstraint(
            model_name="categoryreaction",
            constraint=models.UniqueConstraint(fields=("category", "position"), name="uniq_category_reaction_position"),
        ),
        migrations.CreateModel(
            name="TestimonyReactionCount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("count", models.PositiveIntegerField(default=0)),
                (
                    "reaction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="testimonies.reaction",
                    ),
                ),
                (
                    "testimony",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reaction_totals",
                        to="testimonies.testimony",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="testimonyreactioncount",
            constraint=models.UniqueConstraint(fields=("testimony", "reaction"), name="uniq_testimony_reaction_count"),
        ),
        migrations.CreateModel(
            name="ReactionChangeLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("edited", "Edited"),
                            ("retired", "Retired"),
                            ("restored", "Brought back"),
                            ("set_changed", "Set changed"),
                        ],
                        max_length=20,
                    ),
                ),
                ("summary", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="testimonies.testimonycategory",
                    ),
                ),
                (
                    "reaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="testimonies.reaction",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
