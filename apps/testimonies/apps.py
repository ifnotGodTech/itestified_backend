from django.apps import AppConfig


class TestimoniesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.testimonies"

    def ready(self) -> None:
        from apps.testimonies import signals  # noqa: F401 - registers the receivers.
