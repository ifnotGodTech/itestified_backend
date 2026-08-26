from __future__ import annotations

from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.tests.factories import UserFactory


def premium_user(email: str = "premium@example.com"):
    user = UserFactory(email=email)
    Subscription.objects.create(
        user=user,
        amount=300000,
        payment_reference=f"SUB-PLAYLISTS-{user.id}",
        status=SubscriptionStatus.ACTIVE,
    )
    return user


def free_user(email: str = "free@example.com"):
    return UserFactory(email=email)


def category(slug: str = "faith") -> TestimonyCategory:
    return TestimonyCategory.objects.create(name=slug.title(), slug=slug)


def approved_testimony(*, author=None, title: str = "A testimony", category_obj: TestimonyCategory | None = None) -> Testimony:
    return Testimony.objects.create(
        author=author or UserFactory(),
        category=category_obj or category(),
        title=title,
        body="Body text.",
        testimony_type=TestimonyType.WRITTEN,
        status=TestimonyStatus.APPROVED,
    )
