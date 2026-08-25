from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import requests
from django.conf import settings

from apps.live_broadcasts.exceptions import AgoraNotConfiguredError

# agora-token-builder's own Role_Publisher/Role_Subscriber constants aren't
# reliably importable across published versions of the package, but the
# underlying protocol value is stable -- 1 is "publisher/broadcaster" in
# Agora's live-broadcast profile, 2 is "subscriber/audience" (the default).
# Verified against https://github.com/AgoraIO-Community/python-token-builder.
ROLE_PUBLISHER = 1
ROLE_SUBSCRIBER = 2


@dataclass(frozen=True)
class PublisherCredential:
    app_id: str
    channel_name: str
    uid: int
    token: str
    expires_at_unix: int


def _require_token_credentials() -> tuple[str, str]:
    app_id = settings.AGORA_APP_ID.strip()
    app_certificate = settings.AGORA_APP_CERTIFICATE.strip()
    if not app_id or not app_certificate:
        raise AgoraNotConfiguredError("Agora App ID/Certificate are not configured.")
    return app_id, app_certificate


def issue_publisher_credential(*, channel_name: str, uid: int, expire_seconds: int) -> PublisherCredential:
    """Issues the creator's own publish token for `channel_name` -- a
    separate, subscribe-only token is issued per viewer in Slice 2, not
    here. `agora-token-builder` signs the token locally (HMAC over the
    App Certificate); no network call to Agora is needed to mint it."""
    from agora_token_builder import RtcTokenBuilder

    app_id, app_certificate = _require_token_credentials()
    expires_at_unix = int(time.time()) + expire_seconds
    token = RtcTokenBuilder.buildTokenWithUid(
        app_id, app_certificate, channel_name, uid, ROLE_PUBLISHER, expires_at_unix
    )
    return PublisherCredential(
        app_id=app_id,
        channel_name=channel_name,
        uid=uid,
        token=token,
        expires_at_unix=expires_at_unix,
    )


def _rest_auth_header() -> dict[str, str]:
    customer_id = settings.AGORA_CUSTOMER_ID.strip()
    customer_secret = settings.AGORA_CUSTOMER_SECRET.strip()
    if not customer_id or not customer_secret:
        raise AgoraNotConfiguredError("Agora Customer ID/Secret are not configured.")
    credential = base64.b64encode(f"{customer_id}:{customer_secret}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {credential}"}


def get_participant_minutes_used(*, year: int, month: int) -> int:
    """Queries Agora's Analytics/Usage REST API for this project's total
    participant-minutes consumed in the given calendar month, across every
    Ministry -- this is what the shared monthly ceiling (LiveStreamingPolicy
    .shared_monthly_ceiling_minutes) is checked against, deliberately not a
    locally reconstructed estimate that could drift from what Agora
    actually bills.

    NOTE: the exact Analytics endpoint path/response shape could not be
    directly verified against Agora's live docs while building this (the
    reference page at
    https://docs.agora.io/en/agora-analytics/reference/api render
    client-side and returned 404 to a plain fetch); this targets the
    `/beta/insight/usage/by_time` path surfaced via search results as the
    usage-by-time endpoint. Confirm this against the Agora Console once a
    real project/App ID exists, before relying on it for the go-live cap
    check -- everything else in this module doesn't depend on getting this
    one path exactly right.
    """
    app_id, _ = _require_token_credentials()
    headers = _rest_auth_header()
    from_date = f"{year:04d}-{month:02d}-01"
    response = requests.get(
        f"{settings.AGORA_REST_BASE_URL.rstrip('/')}/beta/insight/usage/by_time",
        headers=headers,
        params={"appId": app_id, "from": from_date, "granularity": "month"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    return int(data.get("participant_minutes") or data.get("usage", {}).get("participant_minutes") or 0)
