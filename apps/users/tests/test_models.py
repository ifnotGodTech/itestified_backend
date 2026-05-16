from django.db import IntegrityError
from django.test import TestCase

from apps.users.choices import AdminAssignmentStatus, UserAccountStatus
from apps.users.models import AdminAssignment, Profile

from .factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


class UserModelTests(TestCase):
    def test_create_user_uses_email_as_username(self) -> None:
        user = UserFactory()

        self.assertEqual(user.username, user.email)
        self.assertEqual(user.account_status, UserAccountStatus.ACTIVE)

    def test_admin_assignment_is_unique_per_user_role(self) -> None:
        assignment = AdminAssignmentFactory(status=AdminAssignmentStatus.INVITED)

        with self.assertRaises(IntegrityError):
            AdminAssignment.objects.create(
                user=assignment.user,
                role=assignment.role,
                status=AdminAssignmentStatus.ACTIVE,
            )

    def test_profile_belongs_to_user(self) -> None:
        profile = ProfileFactory()

        self.assertIsInstance(profile, Profile)
        self.assertEqual(profile.user.profile, profile)
