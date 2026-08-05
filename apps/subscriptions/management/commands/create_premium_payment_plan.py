from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.common.services.flutterwave import FlutterwaveGateway, FlutterwaveGatewayError


class Command(BaseCommand):
    """One-off setup command (Phase 21): creates the single Premium payment
    plan on Flutterwave and prints its id, to be set as
    FLUTTERWAVE_PREMIUM_PLAN_ID. Deliberately not run automatically at
    request time or in a migration -- a payment plan is a stable, real-world
    billing artifact, not something to recreate per-deploy."""

    help = "Create the Premium payment plan on Flutterwave and print its id."

    def handle(self, *args, **options):
        if not settings.FLUTTERWAVE_SECRET_KEY:
            raise CommandError("FLUTTERWAVE_SECRET_KEY is not configured.")

        gateway = FlutterwaveGateway(
            secret_key=settings.FLUTTERWAVE_SECRET_KEY,
            base_url=settings.FLUTTERWAVE_BASE_URL,
        )
        try:
            result = gateway.create_payment_plan(
                name="iTestified Premium",
                amount=settings.PREMIUM_PLAN_AMOUNT_KOBO,
                currency=settings.PREMIUM_PLAN_CURRENCY,
                interval="monthly",
            )
        except FlutterwaveGatewayError as exc:
            raise CommandError(f"Failed to create payment plan: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Created payment plan: {result.provider_plan_id}"))
        self.stdout.write("Set this as FLUTTERWAVE_PREMIUM_PLAN_ID in your environment.")
