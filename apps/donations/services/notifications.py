from __future__ import annotations

import logging

from django.conf import settings

from apps.common.exceptions import EmailProviderNotConfiguredError
from apps.common.services.email import send_email
from apps.donations.models import Donation
from apps.notifications.models import UserNotificationPreference
from apps.notifications.services import notify_admins_of_new_donation

logger = logging.getLogger(__name__)


def _donor_label(user) -> str:
    profile = getattr(user, "profile", None)
    full_name = profile.full_name if profile else ""
    return full_name or user.email


def _amount_label(donation: Donation) -> str:
    major_units = donation.amount / 100
    return f"{donation.currency} {major_units:,.2f}"


def maybe_notify_new_donation(donation: Donation) -> None:
    """Notify active admins that a donation was submitted, per Phase 6 Slice 8's
    "New Donation Received" preference. Failures here must never surface as a
    donation-submission error, so exceptions are logged and swallowed."""
    try:
        notify_admins_of_new_donation(
            donor=donation.user,
            donor_label=_donor_label(donation.user),
            amount_label=_amount_label(donation),
        )
    except Exception:
        logger.exception(
            "donations.notify_new_donation.failed donation_id=%s", donation.id
        )


def maybe_send_donation_thank_you_email(donation: Donation) -> None:
    """Email the donor a thank-you note, per Phase 6 Slice 8's "Thank You Email"
    preference, gated on the donor also allowing email notifications overall.
    A user with no preference row yet gets the model defaults: email
    notifications allowed, thank-you email off. Failures are logged and
    swallowed -- a failed thank-you email must never affect the donation's
    already-committed successful status."""
    preference = UserNotificationPreference.objects.filter(user=donation.user).first()
    wants_thank_you = preference.send_donation_thank_you_email if preference else False
    allows_email = preference.allow_email_notifications if preference else True
    if not (wants_thank_you and allows_email):
        return

    donor_label = _donor_label(donation.user)
    amount_label = _amount_label(donation)
    support_email = getattr(settings, "SUPPORT_EMAIL", "support@itestified.app")
    subject = "Thank you for your donation to iTestified"
    text_message = "\n".join(
        [
            f"Hello {donor_label},",
            "",
            f"Thank you for your generous donation of {amount_label} to iTestified.",
            f"Payment reference: {donation.payment_reference}",
            "",
            "Your support helps us keep sharing testimonies that change lives.",
            "",
            f"Support: {support_email}",
        ]
    )
    html_message = f"""
<html>
  <body style="margin:0;padding:24px;background:#F6F1FF;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#120F1A;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #E6D8FF;border-radius:16px;overflow:hidden;">
      <tr>
        <td style="background:#6E46FF;padding:20px 24px;text-align:center;">
          <div style="color:#FFFFFF;font-size:22px;font-weight:800;letter-spacing:0.02em;">iTestified</div>
        </td>
      </tr>
      <tr>
        <td style="padding:24px;">
          <p style="margin:0 0 12px;font-size:16px;font-weight:600;">Hello {donor_label},</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.5;">
            Thank you for your generous donation of <strong>{amount_label}</strong> to iTestified.
          </p>
          <p style="margin:0 0 10px;font-size:14px;color:#312C3B;">Payment reference: {donation.payment_reference}</p>
          <p style="margin:0 0 16px;font-size:14px;color:#5E6470;">
            Your support helps us keep sharing testimonies that change lives.
          </p>
          <div style="margin-top:18px;padding-top:14px;border-top:1px solid #E5E7EB;font-size:13px;color:#5E6470;">
            Need help? <a href="mailto:{support_email}" style="color:#FF9F4A;text-decoration:none;font-weight:600;">{support_email}</a>
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()

    try:
        send_email(
            subject=subject,
            text_message=text_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to_email=donation.user.email,
        )
    except EmailProviderNotConfiguredError:
        logger.warning(
            "donations.thank_you_email.provider_not_configured donation_id=%s", donation.id
        )
    except Exception:
        logger.exception(
            "donations.thank_you_email.failed donation_id=%s", donation.id
        )
