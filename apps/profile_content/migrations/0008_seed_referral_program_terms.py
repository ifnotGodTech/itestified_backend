from django.db import migrations

# Phase 24 Slice 5. Real money is involved, so this seed gives the terms
# screen real starting copy rather than a blank field an admin has to
# write from scratch before the referral program can launch at all --
# same reasoning as 0004's support-contact seed. Deliberately doesn't
# hardcode a commission percentage (Slice 1 made that admin-configurable
# and it can change over time); an admin can rewrite this freely via the
# existing content-block dashboard control.
REFERRAL_TERMS_BODY = (
    "iTestified's referral program rewards you for bringing new Premium "
    "subscribers to the platform.\n\n"
    "How it works:\n"
    "- Share your personal referral link or code with someone who does not "
    "already have an iTestified account.\n"
    "- If they sign up using your link or code, you become their referrer "
    "permanently. This only applies to brand-new accounts -- an existing "
    "user can never be attributed to a referrer after the fact.\n"
    "- While they remain a paying Premium subscriber and you also remain an "
    "active Premium subscriber, you earn a commission on their subscription "
    "payments at the current commission rate, which an admin may change "
    "from time to time.\n"
    "- If your own subscription lapses, you stop earning new commission "
    "until you resubscribe, but your referral relationship is never lost.\n"
    "- If the person you referred cancels and later resubscribes, your "
    "referral automatically resumes earning commission -- you do not need "
    "to do anything.\n\n"
    "Payouts:\n"
    "- Commission is tracked for you automatically, but payout is manual: "
    "our team reviews and transfers earned commission at the end of each "
    "month.\n"
    "- Commission already earned for a past period is never clawed back or "
    "recalculated, even if the commission rate later changes.\n\n"
    "By accepting these terms, you confirm you understand how referral "
    "attribution and commission work as described above."
)


def seed_referral_program_terms(apps, schema_editor):
    ProfileContentBlock = apps.get_model("profile_content", "ProfileContentBlock")
    ProfileContentBlock.objects.get_or_create(
        key="referral_program_terms", defaults={"body": REFERRAL_TERMS_BODY}
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("profile_content", "0007_alter_profilecontentblock_key"),
    ]

    operations = [
        migrations.RunPython(seed_referral_program_terms, noop),
    ]
