from django.db import models


class ChallengePurpose(models.TextChoices):
    REGISTRATION = "registration", "Registration"
    PASSWORD_RESET = "password_reset", "Password Reset"
    ADMIN_INVITE = "admin_invite", "Admin Invite"
