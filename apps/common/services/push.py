import json
import logging
from typing import Iterable, Optional

import firebase_admin
from django.conf import settings
from firebase_admin import credentials, messaging

from apps.common.exceptions import PushProviderNotConfiguredError

logger = logging.getLogger(__name__)

_firebase_app: Optional[firebase_admin.App] = None


def _get_firebase_app() -> firebase_admin.App:
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    raw_credentials = getattr(settings, "FIREBASE_CREDENTIALS_JSON", "")
    if not raw_credentials:
        raise PushProviderNotConfiguredError(
            "Firebase Admin credentials are not configured (FIREBASE_CREDENTIALS_JSON)."
        )
    try:
        credentials_dict = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise PushProviderNotConfiguredError(
            "FIREBASE_CREDENTIALS_JSON is not valid JSON."
        ) from exc

    cert = credentials.Certificate(credentials_dict)
    _firebase_app = firebase_admin.initialize_app(cert)
    return _firebase_app


def send_push_to_tokens(
    *,
    tokens: list[str],
    title: str,
    body: str,
    data: Optional[dict[str, str]] = None,
) -> list[str]:
    """Sends one push to up to 500 FCM tokens at once.

    Returns the subset of `tokens` that FCM reports as permanently invalid
    (unregistered/uninstalled), so the caller can delete those DeviceToken
    rows -- self-cleaning rather than letting dead tokens accumulate and
    fail every future send.
    """
    if not tokens:
        return []
    app = _get_firebase_app()

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        tokens=tokens,
    )
    response = messaging.send_each_for_multicast(message, app=app)

    invalid_tokens: list[str] = []
    for token, result in zip(tokens, response.responses):
        if result.success:
            continue
        if isinstance(result.exception, messaging.UnregisteredError):
            invalid_tokens.append(token)
        else:
            logger.warning(
                "push.send_each_for_multicast.token_failed error=%s",
                result.exception,
            )
    return invalid_tokens


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
