class AuthnError(Exception):
    pass


class ChallengeVerificationError(AuthnError):
    pass


class EmailDeliveryError(AuthnError):
    pass
