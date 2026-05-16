from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from typing import Optional

from .choices import AdminAssignmentStatus, AdminRoleCode, UserAccountStatus


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: Optional[str], **extra_fields):
        if not email:
            raise ValueError("The email field must be set.")

        email = self.normalize_email(email)
        user = self.model(email=email, username=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: Optional[str] = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("account_status", UserAccountStatus.ACTIVE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = models.EmailField(unique=True)
    email = models.EmailField(unique=True)
    must_change_password = models.BooleanField(default=False)
    account_status = models.CharField(
        max_length=20,
        choices=UserAccountStatus.choices,
        default=UserAccountStatus.ACTIVE,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()


class Profile(models.Model):
    user = models.OneToOneField("users.User", on_delete=models.CASCADE, related_name="profile")
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=32, blank=True)
    avatar = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile<{self.user.email}>"


class AdminRole(models.Model):
    code = models.CharField(
        max_length=50,
        choices=AdminRoleCode.choices,
        unique=True,
    )
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class AdminAssignment(models.Model):
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="admin_assignments")
    role = models.ForeignKey("users.AdminRole", on_delete=models.PROTECT, related_name="assignments")
    status = models.CharField(
        max_length=20,
        choices=AdminAssignmentStatus.choices,
        default=AdminAssignmentStatus.INVITED,
    )
    invited_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_invitations_sent",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uniq_admin_assignment_user_role"),
        ]

    def __str__(self) -> str:
        return f"AdminAssignment<{self.user.email}:{self.role.code}>"
