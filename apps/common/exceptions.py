class EmailProviderNotConfiguredError(Exception):
    """Raised when the selected EMAIL_PROVIDER is missing required configuration."""


class PushProviderNotConfiguredError(Exception):
    """Raised when Firebase Admin SDK credentials are missing/not configured."""
