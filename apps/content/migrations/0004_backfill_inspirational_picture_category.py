from django.db import migrations
from django.utils.text import slugify


def _normalize_name(value: str) -> str:
    stripped = value.strip()
    return f"{stripped[:1].upper()}{stripped[1:].lower()}"


def forwards(apps, schema_editor):
    InspirationalPicture = apps.get_model("content", "InspirationalPicture")
    InspirationalPictureCategory = apps.get_model("content", "InspirationalPictureCategory")

    for picture in InspirationalPicture.objects.exclude(category="").iterator():
        name = _normalize_name(picture.category)
        if not name:
            continue
        category = InspirationalPictureCategory.objects.filter(name__iexact=name).first()
        if category is None:
            category = InspirationalPictureCategory.objects.create(name=name, slug=slugify(name))
        picture.category_fk = category
        picture.save(update_fields=["category_fk"])


class Migration(migrations.Migration):
    # Irreversible: original free-text category strings aren't recoverable
    # once the old column is dropped in the next migration.
    dependencies = [
        ("content", "0003_inspirationalpicturecategory"),
    ]

    operations = [
        migrations.RunPython(forwards),
    ]
