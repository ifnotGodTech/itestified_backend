class EmailProviderNotConfiguredError(Exception):
    """Raised when the selected EMAIL_PROVIDER is missing required configuration."""
