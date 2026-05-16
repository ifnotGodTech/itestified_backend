import factory
from factory.django import DjangoModelFactory

from apps.users.choices import AdminAssignmentStatus, AdminRoleCode, UserAccountStatus
from apps.users.models import AdminAssignment, AdminRole, Profile, User


class UserFactory(DjangoModelFactory):
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    username = factory.LazyAttribute(lambda o: o.email)
    password = factory.PostGenerationMethodCall("set_password", "StrongPass!1")
    account_status = UserAccountStatus.ACTIVE

    class Meta:
        model = User


class ProfileFactory(DjangoModelFactory):
    user = factory.SubFactory(UserFactory)
    full_name = factory.Sequence(lambda n: f"Test User {n}")

    class Meta:
        model = Profile


class AdminRoleFactory(DjangoModelFactory):
    code = AdminRoleCode.MODERATOR
    name = factory.LazyAttribute(lambda o: o.code.replace("_", " ").title())

    class Meta:
        model = AdminRole
        django_get_or_create = ("code",)


class AdminAssignmentFactory(DjangoModelFactory):
    user = factory.SubFactory(UserFactory)
    role = factory.SubFactory(AdminRoleFactory)
    status = AdminAssignmentStatus.ACTIVE

    class Meta:
        model = AdminAssignment
