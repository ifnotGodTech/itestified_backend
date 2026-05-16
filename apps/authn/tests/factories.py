import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.authn.choices import ChallengePurpose
from apps.authn.models import EmailChallenge


class EmailChallengeFactory(DjangoModelFactory):
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    purpose = ChallengePurpose.REGISTRATION
    full_name = "Test User"
    code = "123456"
    expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(minutes=15))

    class Meta:
        model = EmailChallenge
