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


def _build_rtc_credential(*, channel_name: str, uid: int, role: int, expire_seconds: int) -> PublisherCredential:
    from agora_token_builder import RtcTokenBuilder

    app_id, app_certificate = _require_token_credentials()
    expires_at_unix = int(time.time()) + expire_seconds
    token = RtcTokenBuilder.buildTokenWithUid(app_id, app_certificate, channel_name, uid, role, expires_at_unix)
    return PublisherCredential(
        app_id=app_id,
        channel_name=channel_name,
        uid=uid,
        token=token,
        expires_at_unix=expires_at_unix,
    )


def issue_publisher_credential(*, channel_name: str, uid: int, expire_seconds: int) -> PublisherCredential:
    """Issues the creator's own publish token for `channel_name` -- a
    separate, subscribe-only token is issued per viewer in Slice 2, not
    here. `agora-token-builder` signs the token locally (HMAC over the
    App Certificate); no network call to Agora is needed to mint it."""
    return _build_rtc_credential(channel_name=channel_name, uid=uid, role=ROLE_PUBLISHER, expire_seconds=expire_seconds)


def issue_recording_token(*, channel_name: str, uid: int, expire_seconds: int) -> PublisherCredential:
    """Phase 27 Slice 5 -- token for the Cloud Recording bot's own uid to
    join the channel. Subscriber role: the bot only records what's
    already published, it never publishes itself."""
    return _build_rtc_credential(channel_name=channel_name, uid=uid, role=ROLE_SUBSCRIBER, expire_seconds=expire_seconds)


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


# Cloud Recording (Phase 27 Slice 5) -- endpoint paths and request bodies
# below are verified against Agora's own published Postman collection
# (https://github.com/AgoraIO/Agora-RESTful-Service/blob/master/cloud-recording/Cloud_Recording.postman_collection.json),
# not guessed. "mix" mode is composite recording (one merged audio+video
# file), correct here since a broadcast only ever has one publisher --
# Agora's "individual" mode exists for multi-party calls, not this.
def _cloud_recording_base_url(app_id: str) -> str:
    return f"{settings.AGORA_REST_BASE_URL.rstrip('/')}/v1/apps/{app_id}/cloud_recording"


def acquire_cloud_recording(*, channel_name: str, recording_uid: int) -> str:
    app_id, _ = _require_token_credentials()
    headers = _rest_auth_header()
    response = requests.post(
        f"{_cloud_recording_base_url(app_id)}/acquire",
        headers=headers,
        json={"cname": channel_name, "uid": str(recording_uid), "clientRequest": {}},
        timeout=15,
    )
    response.raise_for_status()
    resource_id = response.json().get("resourceId")
    if not resource_id:
        raise AgoraNotConfiguredError("Agora did not return a Cloud Recording resourceId.")
    return resource_id


def start_cloud_recording(
    *, channel_name: str, recording_uid: int, resource_id: str, recording_token: str
) -> str:
    app_id, _ = _require_token_credentials()
    headers = _rest_auth_header()
    payload = {
        "cname": channel_name,
        "uid": str(recording_uid),
        "clientRequest": {
            "token": recording_token,
            "recordingConfig": {
                # A dropped connection stops the recording on its own
                # within this many seconds of the channel going empty --
                # the same signal the reconcile_stale_live_broadcasts
                # management command uses as its own backstop for marking
                # a LiveBroadcast ended (see services/commands.py).
                "maxIdleTime": 120,
                "streamTypes": 2,  # audio + video
                "channelType": 1,  # live-broadcast profile
            },
            "storageConfig": {
                "vendor": settings.AGORA_RECORDING_STORAGE_VENDOR,
                "region": settings.AGORA_RECORDING_STORAGE_REGION,
                "bucket": settings.AGORA_RECORDING_STORAGE_BUCKET,
                "accessKey": settings.AGORA_RECORDING_STORAGE_ACCESS_KEY,
                "secretKey": settings.AGORA_RECORDING_STORAGE_SECRET_KEY,
            },
        },
    }
    response = requests.post(
        f"{_cloud_recording_base_url(app_id)}/resourceid/{resource_id}/mode/mix/start",
        headers=headers,
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    sid = response.json().get("sid")
    if not sid:
        raise AgoraNotConfiguredError("Agora did not return a Cloud Recording sid.")
    return sid


def stop_cloud_recording(*, channel_name: str, recording_uid: int, resource_id: str, sid: str) -> None:
    app_id, _ = _require_token_credentials()
    headers = _rest_auth_header()
    response = requests.post(
        f"{_cloud_recording_base_url(app_id)}/resourceid/{resource_id}/sid/{sid}/mode/mix/stop",
        headers=headers,
        json={"cname": channel_name, "uid": str(recording_uid), "clientRequest": {}},
        timeout=15,
    )
    response.raise_for_status()


def query_cloud_recording(*, resource_id: str, sid: str) -> dict:
    """Returns the raw `serverResponse` payload. NOTE: Agora's exact
    fileList shape for mix-mode recordings couldn't be directly verified
    against live docs while building this (see get_participant_minutes_used's
    own note on the same doc-access limitation) -- callers should treat
    both a bare filename string and a fileList array defensively (see
    services/commands.py's parsing)."""
    app_id, _ = _require_token_credentials()
    headers = _rest_auth_header()
    response = requests.get(
        f"{_cloud_recording_base_url(app_id)}/resourceid/{resource_id}/sid/{sid}/mode/mix/query",
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("serverResponse") or {}
