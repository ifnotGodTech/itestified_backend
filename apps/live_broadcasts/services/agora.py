from __future__ import annotations

import base64
import calendar
import time
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone

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


def issue_viewer_credential(*, channel_name: str, uid: int, expire_seconds: int) -> PublisherCredential:
    """Phase 27 Slice 2 -- a per-viewer subscribe-only token, issued only
    once (join time), never persisted. Subscriber role: a viewer only
    watches what the Ministry publishes, matching the phase's own
    no-real-time-comments decision -- there's nothing for a viewer to
    publish into the channel."""
    return _build_rtc_credential(channel_name=channel_name, uid=uid, role=ROLE_SUBSCRIBER, expire_seconds=expire_seconds)


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


def ban_channel_publisher(*, channel_name: str, uid: int, ban_seconds: int) -> None:
    """Phase 27 Slice 8 -- admin kill switch. Calls Agora's Channel
    Management REST API to revoke the creator's own `join_channel`
    privilege on this specific channel for `ban_seconds` -- what Agora's
    docs call "ban user privileges", backed by what its own examples call
    the "kicking rule" endpoint. Since there's only ever one publisher,
    kicking them ends the broadcast for every viewer at once; the
    cool-down (`ban_seconds`) stops the same Ministry from simply
    rejoining the same channel and restarting on the spot. The kicked
    client receives Agora's own `CONNECTION_CHANGED_BANNED_BY_SERVER`
    callback.

    Endpoint verified against Agora's own docs (`POST
    https://api.agora.io/dev/v1/kicking-rule`); the exact response shape
    (`{"status": "success", "id": ...}`) is reconstructed from a
    search-engine-indexed excerpt of that same page -- it renders
    client-side and 404s to a direct fetch, the same limitation noted on
    get_channel_viewer_count/get_participant_minutes_used above -- so
    confirm against the Agora Console once a real project exists.

    Unlike get_channel_viewer_count, this does not swallow failures: an
    admin's kill action must surface clearly if it didn't actually work,
    never silently report success while the stream keeps running.
    """
    app_id, _ = _require_token_credentials()
    headers = {**_rest_auth_header(), "Content-Type": "application/json", "Accept": "application/json"}
    response = requests.post(
        f"{settings.AGORA_REST_BASE_URL.rstrip('/')}/dev/v1/kicking-rule",
        headers=headers,
        json={
            "appid": app_id,
            "cname": channel_name,
            "uid": str(uid),
            "ip": "",
            "time": ban_seconds,
            "privileges": ["join_channel"],
        },
        timeout=10,
    )
    response.raise_for_status()


def get_participant_minutes_used(*, year: int, month: int) -> int | None:
    """Phase 27 Slice 9 -- queries Agora's Analytics/Usage REST API for
    this project's total usage in the given calendar month, across every
    Ministry combined. This is what the shared platform-wide monthly
    ceiling (LiveStreamingPolicy.shared_monthly_ceiling_minutes) is
    checked against for the admin cost-visibility view -- deliberately
    not a locally reconstructed estimate that could drift from what
    Agora actually bills. Per-Ministry attribution is NOT available from
    this endpoint (Agora has no concept of "Ministry", only App ID/
    channel/user) -- see selectors.list_ministry_usage_for_current_month
    for the per-Ministry breakdown, which reuses the same local
    worst-case-reservation methodology as Slice 4's own allowance check.

    Endpoint verified by directly fetching Agora's own docs-portal source
    on GitHub (`AgoraIO/docs-portal`, `.../api-reference/api-ref/
    agora-analytics/analytics-rest-api.md`) -- unlike every other Agora
    endpoint in this module, this page's *rendered* docs.agora.io version
    is client-side JS and 404s to a direct fetch, but its raw markdown
    source on GitHub does not: `GET /beta/insight/usage/by_time` takes
    `appid`, `startTs`/`endTs` (Unix seconds), `metric`, and
    `aggregateGranularity` (`1d`/`1h`), returning
    `{"data": [{"<metric>": number, "ts": number}, ...]}` -- one row per
    period, summed here across the whole month. `metric=totalDuration` is
    used as the closest available metric to "usage minutes"; Agora's own
    billing docs confirm usage is calculated per-user (i.e. participant-
    minutes, matching this app's own methodology), but the exact unit
    `totalDuration` reports in (seconds vs. minutes, per-call vs.
    per-participant) could not be confirmed from documentation alone --
    confirm against the Agora Console once a real project exists, before
    treating this as authoritative rather than directional.

    Returns None (never raises) on any failure -- this is a best-effort
    cost-visibility figure, not something that should break the admin
    dashboard if Agora is unreachable/misconfigured.
    """
    try:
        app_id, _ = _require_token_credentials()
        headers = _rest_auth_header()
    except AgoraNotConfiguredError:
        return None

    _, days_in_month = calendar.monthrange(year, month)
    start_ts = int(datetime(year, month, 1, tzinfo=dt_timezone.utc).timestamp())
    end_ts = int(datetime(year, month, days_in_month, 23, 59, 59, tzinfo=dt_timezone.utc).timestamp())

    try:
        response = requests.get(
            f"{settings.AGORA_REST_BASE_URL.rstrip('/')}/beta/insight/usage/by_time",
            headers=headers,
            params={
                "appid": app_id,
                "startTs": start_ts,
                "endTs": end_ts,
                "metric": "totalDuration",
                "aggregateGranularity": "1d",
            },
            timeout=15,
        )
        response.raise_for_status()
        rows = response.json().get("data") or []
    except requests.RequestException:
        return None

    return sum(int(row.get("totalDuration") or 0) for row in rows)


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
            # 2026-09-10 fix, found live-testing this app's first real
            # broadcast: mix mode defaults to HLS output only (an .m3u8
            # manifest referencing separate .ts segment files), which
            # Cloudinary's upload-by-URL rejects outright ("invalid
            # file") since it isn't a single playable video -- confirmed
            # live. First attempt put avFileType inside recordingConfig,
            # which Agora silently ignored (recording still succeeded,
            # just stayed HLS-only) -- it's actually a sibling object,
            # recordingFileConfig, confirmed against Agora's own request-
            # body example. "hls" must stay listed alongside "mp4"
            # (mp4-only errors); the mp4 file is what
            # extract_recording_file_name now selects.
            "recordingFileConfig": {
                "avFileType": ["hls", "mp4"],
            },
            "storageConfig": {
                "vendor": settings.AGORA_RECORDING_STORAGE_VENDOR,
                "region": settings.AGORA_RECORDING_STORAGE_REGION,
                "bucket": settings.AGORA_RECORDING_STORAGE_BUCKET,
                "accessKey": settings.AGORA_RECORDING_STORAGE_ACCESS_KEY,
                "secretKey": settings.AGORA_RECORDING_STORAGE_SECRET_KEY,
                # 2026-09-10 fix, found live-testing this app's first real
                # broadcast: without this, Agora writes to the bucket
                # root, which 403s against any bucket policy scoped to a
                # "recordings/*"-style prefix (the natural way to grant
                # public read to just this app's own folder rather than
                # the whole bucket) -- confirmed live, a direct fetch of
                # the root-level file 403'd. This must match whatever
                # prefix the bucket's public-read policy actually grants.
                "fileNamePrefix": ["recordings"],
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


def stop_cloud_recording(*, channel_name: str, recording_uid: int, resource_id: str, sid: str) -> dict:
    """Returns the raw `serverResponse` payload -- Agora's own `stop` call
    is the authoritative source for the finished recording's file list,
    not a follow-up `query` call (2026-09-10 correction, found live-
    testing this app's first real broadcast). The original design here
    called `stop` and then polled `query_cloud_recording` with backoff,
    on the assumption `stop` returns before the file finishes uploading.
    That assumption was wrong: Agora's own docs state `query` (and a
    second `stop`) return 404 once a recording session has already ended
    -- confirmed live, every `query` attempt 404'd starting from the very
    first one, never once succeeding, because `stop` had already ended
    the session by definition. `stop`'s own response carries the same
    `serverResponse.fileList` shape `query` would have -- see
    `extract_recording_file_name`."""
    app_id, _ = _require_token_credentials()
    headers = _rest_auth_header()
    response = requests.post(
        f"{_cloud_recording_base_url(app_id)}/resourceid/{resource_id}/sid/{sid}/mode/mix/stop",
        headers=headers,
        json={"cname": channel_name, "uid": str(recording_uid), "clientRequest": {}},
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("serverResponse") or {}


def extract_recording_file_name(server_response: dict) -> str:
    """Agora's exact mix-mode fileList shape couldn't be directly verified
    against live docs while building this (see get_participant_minutes_used's
    own note on the same doc-access limitation) -- handle both a bare
    filename string and a fileList array of objects defensively rather
    than assuming one shape. Shared by end_broadcast() (reading `stop`'s
    own response) -- moved here from tasks.py's private helper once
    `query` was dropped from the archival path.

    2026-09-10 fix: with `avFileType: ["hls", "mp4"]` (see
    start_cloud_recording), a real response's fileList is an array
    containing BOTH the .m3u8 manifest and the .mp4 file -- confirmed
    live that picking whichever happens to be first (the original logic
    here) can hand Cloudinary the unplayable HLS manifest instead. When
    multiple entries exist, the .mp4 one is preferred explicitly rather
    than assumed to be first."""
    file_list = server_response.get("fileList")
    if isinstance(file_list, str) and file_list.strip():
        return file_list.strip()
    if isinstance(file_list, list) and file_list:
        names = [
            str(item.get("fileName") or "").strip() if isinstance(item, dict) else str(item).strip()
            for item in file_list
        ]
        for name in names:
            if name.lower().endswith(".mp4"):
                return name
        return names[0] if names else ""
    return ""


def get_channel_viewer_count(*, channel_name: str) -> int | None:
    """Phase 27 Slice 7 -- admin monitoring panel, queried on demand each
    time it's viewed/refreshed rather than the backend joining the
    channel itself (see Slice 4's own "no new real-time backend
    infrastructure" stance). Endpoint path is verified against Agora's
    live docs (`https://api.agora.io/dev/v1/channel/user/{appid}/
    {channelName}`, "Query user list"); the exact response shape below
    (`audience_total` alongside a `broadcasters`/`audience` uid list) is
    reconstructed from a search-engine-indexed excerpt of that same page
    -- the page itself renders client-side and 404s to a direct fetch,
    the same limitation noted on get_participant_minutes_used/
    query_cloud_recording above -- so confirm it against the Agora
    Console once a real project exists. `broadcasters` (the Ministry's
    own publisher) is deliberately excluded from the count returned here
    since this is "viewer count", not "participant count".

    Returns None (never raises) on any failure -- Agora being
    unreachable/misconfigured must never break the monitoring panel
    itself, only make one row's viewer count show as unavailable.
    """
    try:
        app_id, _ = _require_token_credentials()
        headers = _rest_auth_header()
    except AgoraNotConfiguredError:
        return None
    try:
        response = requests.get(
            f"{settings.AGORA_REST_BASE_URL.rstrip('/')}/dev/v1/channel/user/{app_id}/{channel_name}",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
    except requests.RequestException:
        return None
    if not data.get("channel_exist"):
        return 0
    audience_total = data.get("audience_total")
    if audience_total is not None:
        return int(audience_total)
    return len(data.get("audience") or [])


def query_cloud_recording(*, resource_id: str, sid: str) -> dict:
    """Returns the raw `serverResponse` payload -- for checking status on a
    recording session Agora still considers ongoing. NOT used by the
    archival flow (see stop_cloud_recording's own docstring): once `stop`
    has already succeeded for a resource_id/sid pair, Agora's own docs
    confirm this 404s (the session has ended), which is exactly what a
    real broadcast on 2026-09-10 reproduced -- every attempt 404'd from
    the first one. Kept for any future status-check use against a
    recording still in progress, not archival."""
    app_id, _ = _require_token_credentials()
    headers = _rest_auth_header()
    response = requests.get(
        f"{_cloud_recording_base_url(app_id)}/resourceid/{resource_id}/sid/{sid}/mode/mix/query",
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("serverResponse") or {}
