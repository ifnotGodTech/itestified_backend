from django.db import models


class ChallengePurpose(models.TextChoices):
    REGISTRATION = "registration", "Registration"
    PASSWORD_RESET = "password_reset", "Password Reset"
    ADMIN_INVITE = "admin_invite", "Admin Invite"


class AccountDeletionReason(models.TextChoices):
    NOT_USING = "not_using", "I don't use the app anymore"
    PRIVACY_CONCERNS = "privacy_concerns", "I have privacy concerns"
    NEW_ACCOUNT = "new_account", "I'm creating a new account"
    OTHER = "other", "Other"
