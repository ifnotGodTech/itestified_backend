class LiveBroadcastNotFoundError(Exception):
    pass


class NotAVerifiedMinistryError(Exception):
    """Raised when a user with no verified CreatorProfile tries to
    schedule/go-live -- eligibility is Ministry-only, per the 2026-08-25
    product decision, not open to Premium individuals."""


class LiveBroadcastingDisabledError(Exception):
    """Raised when LiveStreamingPolicy.is_enabled is False -- the
    feature-wide kill switch, separate from any single broadcast's own
    admin-terminated state (Slice 8)."""


class LiveBroadcastWrongStatusError(Exception):
    """Raised when an action expects a different LiveBroadcastStatus than
    the one the broadcast is actually in (e.g. go-live on an already-live
    or already-ended broadcast)."""


class InsufficientAllowanceError(Exception):
    """Raised by go_live() when a Ministry's remaining monthly allowance
    can't cover this broadcast's worst-case reservation. Carries the
    shortfall so the caller can offer a self-service purchase for exactly
    that amount rather than a vague "not enough minutes" message."""

    def __init__(self, *, shortfall_minutes: int, remaining_minutes: int):
        self.shortfall_minutes = shortfall_minutes
        self.remaining_minutes = remaining_minutes
        super().__init__(
            f"This broadcast needs {shortfall_minutes} more participant-minutes than your remaining allowance ({remaining_minutes})."
        )


class LiveMinutePurchaseNotFoundError(Exception):
    pass


class LiveMinutePricingNotConfiguredError(Exception):
    """Raised when a Ministry tries to purchase extra minutes in a
    currency the admin hasn't configured a LiveMinutePricing row for."""


class LiveBroadcastApprovalRequestNotFoundError(Exception):
    pass


class LiveBroadcastApprovalAlreadyDecidedError(Exception):
    pass


class AgoraNotConfiguredError(Exception):
    """Raised when an Agora call is attempted with no App ID/Certificate or
    Customer ID/Secret configured -- expected until a real Agora project
    exists (see Background note in config/settings/base.py)."""
