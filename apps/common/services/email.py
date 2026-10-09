import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from apps.common.exceptions import EmailProviderNotConfiguredError

BREVO_EMAIL_API_URL = "https://api.brevo.com/v3/smtp/email"


def _parse_email_address(value: str) -> tuple[str, str]:
    text = value.strip()
    if "<" in text and ">" in text:
        name, raw_email = text.split("<", 1)
        return name.strip().strip('"'), raw_email.split(">", 1)[0].strip()
    return "", text


def send_email(
    *,
    subject: str,
    text_message: str,
    html_message: str,
    from_email: str,
    to_email: str,
) -> None:
    """Send an email via the configured EMAIL_PROVIDER.

    "brevo" (the live provider) sends through Brevo's HTTP API. "smtp" sends
    through Django's EMAIL_BACKEND -- used by local development and tests
    (console/locmem backends), not production.

    Raises EmailProviderNotConfiguredError for an unknown provider or a
    missing Brevo API key, or the provider's own exception on delivery failure.
    """
    provider = getattr(settings, "EMAIL_PROVIDER", "smtp").lower()

    if provider not in ("brevo", "smtp"):
        raise EmailProviderNotConfiguredError(f"Unknown EMAIL_PROVIDER '{provider}'; expected 'brevo' or 'smtp'.")

    if provider == "brevo":
        api_key = getattr(settings, "BREVO_API_KEY", "")
        if not api_key:
            raise EmailProviderNotConfiguredError("Brevo API key is not configured.")
        sender_name, sender_email = _parse_email_address(
            getattr(settings, "BREVO_FROM_EMAIL", from_email)
        )
        recipient_name, recipient_email = _parse_email_address(to_email)
        response = requests.post(
            BREVO_EMAIL_API_URL,
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
                "User-Agent": "itestified-backend",
            },
            json={
                "sender": {
                    "name": sender_name or "iTestified",
                    "email": sender_email,
                },
                "to": [
                    {
                        "email": recipient_email,
                        **({"name": recipient_name} if recipient_name else {}),
                    }
                ],
                "subject": subject,
                "htmlContent": html_message,
                "textContent": text_message,
            },
            timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
        )
        response.raise_for_status()
        return

    connection = get_connection(
        fail_silently=False,
        timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
    )
    email_message = EmailMultiAlternatives(
        subject=subject,
        body=text_message,
        from_email=from_email,
        to=[to_email],
        connection=connection,
    )
    email_message.attach_alternative(html_message, "text/html")
    email_message.send(fail_silently=False)
