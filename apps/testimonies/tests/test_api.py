from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyFavorite,
    TestimonyStatus,
    TestimonyType,
)
from apps.users.tests.factories import ProfileFactory, UserFactory


class TestimonyApiTests(TestCase):
    def setUp(self) -> None:
        self.category_faith = TestimonyCategory.objects.create(
            name="Faith",
            slug="faith",
            description="Faith stories",
            is_active=True,
        )
        self.category_healing = TestimonyCategory.objects.create(
            name="Healing",
            slug="healing",
            description="Healing stories",
            is_active=True,
        )
        self.category_inactive = TestimonyCategory.objects.create(
            name="Archived",
            slug="archived",
            is_active=False,
        )

        author = UserFactory(email="approved@author.com")
        ProfileFactory(user=author, full_name="Approved Author")
        Testimony.objects.create(
            author=author,
            category=self.category_faith,
            title="God healed me",
            body="I was healed after prayer.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
            view_count=100,
            comment_count=4,
        )
        Testimony.objects.create(
            author=author,
            category=self.category_healing,
            title="Breakthrough after fasting",
            body="A powerful breakthrough came.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
            view_count=22,
            comment_count=1,
        )
        Testimony.objects.create(
            author=author,
            category=self.category_faith,
            title="Pending testimony",
            body="This should not be listed publicly.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.PENDING_REVIEW,
        )
        Testimony.objects.create(
            author=author,
            category=self.category_inactive,
            title="Hidden by inactive category",
            body="Should not be listed publicly.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

    def test_slice1_browse_testimonies_lists_only_approved_with_filters(self) -> None:
        response = self.client.get(reverse("testimony-list"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["results"]), 2)

        filtered = self.client.get(f'{reverse("testimony-list")}?category=faith')
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["count"], 1)
        self.assertEqual(filtered.json()["results"][0]["category_slug"], "faith")

        searched = self.client.get(f'{reverse("testimony-list")}?search=breakthrough')
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()["count"], 1)
        self.assertIn("Breakthrough", searched.json()["results"][0]["title"])

    def test_slice2_view_testimony_detail_returns_full_fields(self) -> None:
        testimony = Testimony.objects.get(title="God healed me")
        response = self.client.get(reverse("testimony-detail", kwargs={"pk": testimony.pk}))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], testimony.title)
        self.assertEqual(body["body"], testimony.body)
        self.assertEqual(body["author_name"], "Approved Author")
        self.assertEqual(body["category"], testimony.category.name)
        self.assertEqual(body["view_count"], testimony.view_count)
        self.assertEqual(body["comment_count"], testimony.comment_count)

    def test_slice3_submit_written_testimony_requires_auth_and_sets_pending(self) -> None:
        unauth_response = self.client.post(
            reverse("testimony-submit-written"),
            {
                "title": "Fresh testimony",
                "body": "God did it for me again.",
                "category_id": self.category_faith.id,
            },
            content_type="application/json",
        )
        self.assertEqual(unauth_response.status_code, 401)

        user = UserFactory(email="writer@example.com")
        ProfileFactory(user=user, full_name="Writer User")
        token = Token.objects.create(user=user)
        auth_response = self.client.post(
            reverse("testimony-submit-written"),
            {
                "title": "Fresh testimony",
                "body": "God did it for me again.",
                "category_id": self.category_faith.id,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(auth_response.status_code, 201)
        created = Testimony.objects.get(title="Fresh testimony")
        self.assertEqual(created.author, user)
        self.assertEqual(created.status, TestimonyStatus.PENDING_REVIEW)
        self.assertEqual(created.testimony_type, TestimonyType.WRITTEN)

    def test_slice4_submit_video_testimony_sets_pending_review(self) -> None:
        user = UserFactory(email="video@example.com")
        ProfileFactory(user=user, full_name="Video User")
        token = Token.objects.create(user=user)
        response = self.client.post(
            reverse("testimony-submit-video"),
            {
                "title": "Healing video testimony",
                "category_id": self.category_healing.id,
                "video_url": "https://cdn.example.com/testimony.mp4",
                "thumbnail_url": "https://cdn.example.com/thumb.jpg",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 201)
        created = Testimony.objects.get(title="Healing video testimony")
        self.assertEqual(created.author, user)
        self.assertEqual(created.status, TestimonyStatus.PENDING_REVIEW)
        self.assertEqual(created.testimony_type, TestimonyType.VIDEO)

    def test_slice5_my_testimonies_lists_all_statuses_for_user(self) -> None:
        owner = UserFactory(email="mine@example.com")
        ProfileFactory(user=owner, full_name="Mine User")
        other = UserFactory(email="other@example.com")
        ProfileFactory(user=other, full_name="Other User")
        token = Token.objects.create(user=owner)

        Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Mine approved",
            body="Approved one",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        Testimony.objects.create(
            author=owner,
            category=self.category_faith,
            title="Mine rejected",
            body="Rejected one",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.REJECTED,
        )
        Testimony.objects.create(
            author=other,
            category=self.category_faith,
            title="Not mine",
            body="Not mine",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )

        response = self.client.get(
            reverse("testimony-mine-list"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)
        titles = {item["title"] for item in response.json()["results"]}
        self.assertIn("Mine approved", titles)
        self.assertIn("Mine rejected", titles)
        self.assertNotIn("Not mine", titles)

    def test_slice6_and_slice7_add_and_remove_favorite(self) -> None:
        user = UserFactory(email="favorite@example.com")
        ProfileFactory(user=user, full_name="Favorite User")
        token = Token.objects.create(user=user)
        testimony = Testimony.objects.filter(status=TestimonyStatus.APPROVED).first()
        assert testimony is not None

        add_response = self.client.post(
            reverse("testimony-favorite-toggle", kwargs={"testimony_id": testimony.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(add_response.status_code, 201)
        self.assertTrue(
            TestimonyFavorite.objects.filter(user=user, testimony=testimony).exists()
        )

        list_response = self.client.get(
            reverse("testimony-favorite-list"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(list_response.status_code, 200)
        favorite_ids = [item["testimony_id"] for item in list_response.json()]
        self.assertIn(testimony.id, favorite_ids)

        remove_response = self.client.delete(
            reverse("testimony-favorite-toggle", kwargs={"testimony_id": testimony.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertFalse(
            TestimonyFavorite.objects.filter(user=user, testimony=testimony).exists()
        )
