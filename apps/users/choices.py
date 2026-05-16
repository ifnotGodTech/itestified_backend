from django.db import models


class UserAccountStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DEACTIVATED = "deactivated", "Deactivated"
    DELETED = "deleted", "Deleted"


class AdminAssignmentStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    DEACTIVATED = "deactivated", "Deactivated"


class AdminRoleCode(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super Admin"
    CONTENT_ADMIN = "content_admin", "Content Admin"
    MODERATOR = "moderator", "Moderator"
    FINANCE_ADMIN = "finance_admin", "Finance Admin"
