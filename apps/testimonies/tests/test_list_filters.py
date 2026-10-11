from django.test import TestCase
from django.urls import reverse

from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.tests.factories import UserFactory


class PublicTestimonyListTypeFilterTests(TestCase):
    """Phase 34 Slice 1 -- the relocated category screen pages each of its
    Video / Audio / Written tabs from the server, so the list endpoint needs
    a type filter alongside the existing category filter."""

    url = reverse("testimony-list")

    def setUp(self):
        author = UserFactory(email="author@example.com")
        self.healing = TestimonyCategory.objects.create(name="Healing", slug="healing")
        faith = TestimonyCategory.objects.create(name="Faith", slug="faith")
        for title, category, kind in [
            ("Healing video", self.healing, TestimonyType.VIDEO),
            ("Healing audio", self.healing, TestimonyType.AUDIO),
            ("Healing written", self.healing, TestimonyType.WRITTEN),
            ("Faith video", faith, TestimonyType.VIDEO),
        ]:
            Testimony.objects.create(
                author=author, category=category, title=title, body="...",
                testimony_type=kind, status=TestimonyStatus.APPROVED,
            )

    def _titles(self, query: str) -> set[str]:
        response = self.client.get(f"{self.url}?{query}")
        self.assertEqual(response.status_code, 200)
        return {item["title"] for item in response.json()["results"]}

    def test_type_combines_with_category(self):
        self.assertEqual(self._titles("category=healing&type=video"), {"Healing video"})
        self.assertEqual(self._titles("category=healing&type=written"), {"Healing written"})

    def test_type_alone_filters_across_categories(self):
        self.assertEqual(self._titles("type=video"), {"Healing video", "Faith video"})

    def test_no_type_keeps_every_type(self):
        self.assertEqual(len(self._titles("category=healing")), 3)

    def test_unknown_type_is_a_clear_400(self):
        response = self.client.get(f"{self.url}?type=podcast")
        self.assertEqual(response.status_code, 400)
        self.assertIn("type", response.json())
