from django.core.management.base import BaseCommand, CommandError

from apps.authn.services.commands import bootstrap_super_admin


class Command(BaseCommand):
    help = "Provision or rotate credentials for the initial super admin account."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Super admin email address")
        parser.add_argument("--full-name", default="", help="Optional full name for profile")

    def handle(self, *args, **options):
        email = options["email"]
        full_name = options.get("full_name", "")

        if not email:
            raise CommandError("--email is required")

        user, temp_password = bootstrap_super_admin(email=email, full_name=full_name)
        self.stdout.write(self.style.SUCCESS("Super admin bootstrap completed."))
        self.stdout.write(f"email={user.email}")
        self.stdout.write(f"temporary_password={temp_password}")
