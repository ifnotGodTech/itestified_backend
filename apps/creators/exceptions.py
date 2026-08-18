class CreatorProfileNotEligibleError(Exception):
    """Raised when a non-premium user tries to create or edit a
    CreatorProfile."""


class CreatorProfileAlreadyExistsError(Exception):
    pass


class CreatorProfileNotFoundError(Exception):
    pass


class CannotFollowSelfError(Exception):
    pass


class PrayerReactionNotFoundError(Exception):
    pass


class PrayerReactionNotOwnedByCreatorError(Exception):
    """Raised when a user tries to respond to a reaction on a testimony
    they don't author -- responding is a creator-only action on their own
    content, never on someone else's."""


class PrayerReactionWrongTypeError(Exception):
    """Raised for a reaction that isn't praying_for_you -- amen/gives_me_hope
    are passive acknowledgments with no implied expectation of a personal
    reply, per Phase 23's Background note."""


class PrayerReactionAlreadyRespondedError(Exception):
    pass
