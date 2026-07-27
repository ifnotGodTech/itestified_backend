from django.db import migrations


def _normalize_full_name(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())


def forwards(apps, schema_editor):
    Profile = apps.get_model("users", "Profile")
    for profile in Profile.objects.exclude(full_name="").iterator():
        normalized = _normalize_full_name(profile.full_name)
        if normalized != profile.full_name:
            profile.full_name = normalized
            profile.save(update_fields=["full_name"])


class Migration(migrations.Migration):
    # Irreversible: original casing isn't recoverable once overwritten.
    dependencies = [
        ("users", "0002_user_must_change_password"),
    ]

    operations = [
        migrations.RunPython(forwards),
    ]
