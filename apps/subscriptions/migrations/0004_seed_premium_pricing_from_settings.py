from django.conf import settings
from django.db import migrations


def seed_pricing_from_settings(apps, schema_editor):
    """One-time bridge for this deploy: PremiumPricing supersedes the
    PREMIUM_PLAN_PRICING_MINOR_UNITS / FLUTTERWAVE_PREMIUM_PLAN_IDS settings
    dicts (Phase 21 Slice 5), but this environment already has real,
    currently-working plan ids configured via env vars -- without this seed,
    subscribe() would suddenly find no PremiumPricing rows and reject every
    currency the moment this migration deploys. Only seeds a currency that
    has both a non-empty plan id and a price already configured; an
    incomplete/placeholder currency is left for an admin to set up properly
    via the new dashboard control instead."""
    PremiumPricing = apps.get_model("subscriptions", "PremiumPricing")
    plan_ids = getattr(settings, "FLUTTERWAVE_PREMIUM_PLAN_IDS", {})
    amounts = getattr(settings, "PREMIUM_PLAN_PRICING_MINOR_UNITS", {})
    for currency, plan_id in plan_ids.items():
        if not plan_id:
            continue
        amount = amounts.get(currency)
        if not amount:
            continue
        PremiumPricing.objects.update_or_create(
            currency=currency,
            defaults={"amount": amount, "provider_plan_id": plan_id},
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0003_premium_pricing"),
    ]

    operations = [
        migrations.RunPython(seed_pricing_from_settings, noop_reverse),
    ]
