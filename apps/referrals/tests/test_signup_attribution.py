from django.test import TestCase

from apps.referrals.models import ReferralAttribution
from apps.referrals.services.commands import attribute_referral_signup, get_or_create_referral_code
from apps.users.tests.factories import UserFactory


class AttributeReferralSignupTests(TestCase):
    def setUp(self):
        self.referrer = UserFactory(email="signup-referrer@example.com")
        self.referral_code = get_or_create_referral_code(user=self.referrer)

    def test_a_blank_code_is_a_no_op(self):
        referred = UserFactory(email="signup-referred-blank@example.com")
        result = attribute_referral_signup(referred_user=referred, code="")
        self.assertIsNone(result)
        self.assertFalse(ReferralAttribution.objects.filter(referred_user=referred).exists())

    def test_an_unrecognized_code_is_silently_ignored(self):
        referred = UserFactory(email="signup-referred-bad-code@example.com")
        result = attribute_referral_signup(referred_user=referred, code="NOTREAL1")
        self.assertIsNone(result)
        self.assertFalse(ReferralAttribution.objects.filter(referred_user=referred).exists())

    def test_a_valid_code_creates_the_attribution(self):
        referred = UserFactory(email="signup-referred-good@example.com")
        result = attribute_referral_signup(referred_user=referred, code=self.referral_code.code)
        self.assertIsNotNone(result)
        self.assertEqual(result.referrer, self.referrer)
        self.assertEqual(result.referred_user, referred)

    def test_the_code_lookup_is_case_insensitive(self):
        referred = UserFactory(email="signup-referred-lowercase@example.com")
        result = attribute_referral_signup(referred_user=referred, code=self.referral_code.code.lower())
        self.assertIsNotNone(result)
        self.assertEqual(result.referrer, self.referrer)

    def test_a_user_cannot_be_attributed_to_themselves(self):
        # Defensive guard -- referred_user was just created and can't
        # already own a ReferralCode in the real flow, but this confirms
        # the check exists regardless.
        own_code = get_or_create_referral_code(user=self.referrer)
        result = attribute_referral_signup(referred_user=self.referrer, code=own_code.code)
        self.assertIsNone(result)
        self.assertFalse(ReferralAttribution.objects.filter(referred_user=self.referrer).exists())
