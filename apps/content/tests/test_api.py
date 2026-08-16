import os
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.content.models import (
    FeaturedHomePicture,
    FeaturedHomeTestimony,
    HomePromoCard,
    HomePromoCardStatus,
    HomeSectionKey,
    HomeSectionOrder,
    InspirationalPicture,
    InspirationalPictureCategory,
    InspirationalPictureStatus,
    ScriptureOfTheDay,
    ScriptureStatus,
)
from apps.content.services.commands import publish_due_scheduled_scriptures
from apps.notifications.models import NotificationType, UserNotification
from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, ProfileFactory, UserFactory


class ContentAdminApiTests(TestCase):
    def setUp(self):
        self.admin = UserFactory(email="content-admin@example.com")
        AdminAssignmentFactory(user=self.admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        self.client.force_login(self.admin)

    def test_phase7_slice1_upload_inspirational_picture(self):
        category = InspirationalPictureCategory.objects.create(name="Hope", slug="hope")
        response = self.client.post(
            reverse("admin-inspirational-picture-list-create"),
            {
                "title": "Morning Mercy",
                "caption": "God is faithful.",
                "category_id": category.id,
                "source": "https://instagram.com/example",
                "image_url": "https://images.example.com/pic.jpg",
                "status": InspirationalPictureStatus.SCHEDULED,
                "publish_at": (timezone.now() + timedelta(days=1)).isoformat(),
                "expires_at": (timezone.now() + timedelta(days=5)).isoformat(),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(InspirationalPicture.objects.count(), 1)
        self.assertEqual(InspirationalPicture.objects.first().status, InspirationalPictureStatus.SCHEDULED)
        self.assertEqual(InspirationalPicture.objects.first().category_id, category.id)

    def test_upload_accepts_a_plain_attribution_label_as_source(self):
        # source is a short label ("Instagram", "Southern Living"), not a
        # clickable link -- regression test for a real 400 an admin hit when
        # this field used to be a strict URLField.
        response = self.client.post(
            reverse("admin-inspirational-picture-list-create"),
            {
                "title": "Morning Mercy",
                "source": "Instagram",
                "image_url": "https://images.example.com/pic.jpg",
                "status": InspirationalPictureStatus.DRAFT,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(InspirationalPicture.objects.first().source, "Instagram")

    def test_phase7_slice2_edit_or_unpublish_picture(self):
        category = InspirationalPictureCategory.objects.create(name="Faith", slug="faith")
        picture = InspirationalPicture.objects.create(
            title="Grace",
            caption="Caption A",
            category=category,
            image_url="https://images.example.com/a.jpg",
            status=InspirationalPictureStatus.PUBLISHED,
            created_by=self.admin,
            updated_by=self.admin,
        )
        edit_response = self.client.patch(
            reverse("admin-inspirational-picture-detail", kwargs={"pk": picture.id}),
            {"caption": "Caption B", "image_url": "https://images.example.com/b.jpg"},
            content_type="application/json",
        )
        self.assertEqual(edit_response.status_code, 200)
        picture.refresh_from_db()
        self.assertEqual(picture.caption, "Caption B")

        unpublish_response = self.client.post(
            reverse("admin-inspirational-picture-unpublish", kwargs={"picture_id": picture.id})
        )
        self.assertEqual(unpublish_response.status_code, 200)
        picture.refresh_from_db()
        self.assertEqual(picture.status, InspirationalPictureStatus.UNPUBLISHED)

    def test_admin_manage_inspirational_picture_categories(self):
        list_response = self.client.get(reverse("admin-inspirational-picture-category-list-create"))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), [])

        create_response = self.client.post(
            reverse("admin-inspirational-picture-category-list-create"),
            {"name": "faith", "description": "Faith pictures"},
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["name"], "Faith")
        created_id = create_response.json()["id"]

        duplicate_response = self.client.post(
            reverse("admin-inspirational-picture-category-list-create"),
            {"name": "FAITH", "description": "Duplicate"},
            content_type="application/json",
        )
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(duplicate_response.json()["name"], ["Category name already exists."])

        edit_response = self.client.patch(
            reverse("admin-inspirational-picture-category-detail", kwargs={"pk": created_id}),
            {"description": "Updated faith pictures"},
            content_type="application/json",
        )
        self.assertEqual(edit_response.status_code, 200)
        self.assertEqual(edit_response.json()["description"], "Updated faith pictures")

        deactivate_response = self.client.delete(
            reverse("admin-inspirational-picture-category-activation", kwargs={"category_id": created_id})
        )
        self.assertEqual(deactivate_response.status_code, 200)
        self.assertEqual(deactivate_response.json()["is_active"], False)

        reactivate_response = self.client.post(
            reverse("admin-inspirational-picture-category-activation", kwargs={"category_id": created_id})
        )
        self.assertEqual(reactivate_response.status_code, 200)
        self.assertEqual(reactivate_response.json()["is_active"], True)

    def test_inspirational_picture_upload_rejects_inactive_category(self):
        inactive = InspirationalPictureCategory.objects.create(name="Retired", slug="retired", is_active=False)
        response = self.client.post(
            reverse("admin-inspirational-picture-list-create"),
            {
                "title": "Morning Mercy",
                "category_id": inactive.id,
                "image_url": "https://images.example.com/pic.jpg",
                "status": InspirationalPictureStatus.DRAFT,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_inspirational_picture_upload_signature_returns_cloudinary_payload(self):
        env = {
            "CLOUDINARY_CLOUD_NAME": "demo-cloud",
            "CLOUDINARY_API_KEY": "demo-key",
            "CLOUDINARY_API_SECRET": "demo-secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            response = self.client.post(reverse("admin-inspirational-picture-upload-signature"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["cloud_name"], "demo-cloud")
        self.assertEqual(body["folder"], "itestified/content/inspirational-pictures")
        self.assertIn("signature", body)

    def test_phase7_slice3_schedule_scripture_with_unique_date(self):
        target_date = timezone.localdate() + timedelta(days=2)
        response = self.client.post(
            reverse("admin-scripture-list-create"),
            {
                "date": str(target_date),
                "bible_text": "Jeremiah 29:11",
                "scripture": "For I know the plans...",
                "prayer": "Give us peace.",
                "bible_version": "KJV",
                "status": ScriptureStatus.SCHEDULED,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

        duplicate = self.client.post(
            reverse("admin-scripture-list-create"),
            {
                "date": str(target_date),
                "bible_text": "Psalm 23:1",
                "scripture": "The Lord is my shepherd.",
                "prayer": "Guide us.",
                "bible_version": "KJV",
                "status": ScriptureStatus.SCHEDULED,
            },
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 400)

    def test_phase7_slice4_edit_scripture_before_publish_date(self):
        entry = ScriptureOfTheDay.objects.create(
            date=timezone.localdate() + timedelta(days=3),
            bible_text="Psalm 91:1",
            scripture="He who dwells...",
            prayer="Protect us.",
            bible_version="KJV",
            status=ScriptureStatus.SCHEDULED,
            created_by=self.admin,
            updated_by=self.admin,
        )
        edit_response = self.client.patch(
            reverse("admin-scripture-detail", kwargs={"pk": entry.id}),
            {"bible_text": "Psalm 91:2", "scripture": "I will say of the Lord..."},
            content_type="application/json",
        )
        self.assertEqual(edit_response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.bible_text, "Psalm 91:2")

    def test_scripture_created_for_today_publishes_immediately(self):
        # Regression: refresh_status_for_today() sets published_at as part of
        # flipping the status, so a caller checking "published_at is None"
        # afterward always sees it already set -- the flip never got saved.
        # Reported live: creating a scripture dated today stayed "scheduled"
        # forever, indistinguishable from one scheduled for next month.
        member = UserFactory(email="scripture-member-create@example.com")
        response = self.client.post(
            reverse("admin-scripture-list-create"),
            {
                "date": str(timezone.localdate()),
                "bible_text": "Psalm 91:1",
                "scripture": "He who dwells in the shelter of the Most High.",
                "prayer": "Protect us.",
                "bible_version": "KJV",
                "status": ScriptureStatus.SCHEDULED,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        entry = ScriptureOfTheDay.objects.get(id=response.json()["id"])
        self.assertEqual(entry.status, ScriptureStatus.PUBLISHED)
        self.assertIsNotNone(entry.published_at)
        notification = UserNotification.objects.get(recipient=member)
        self.assertEqual(notification.notification_type, NotificationType.SCRIPTURE_PUBLISHED)
        self.assertIn("Psalm 91:1", notification.message)
        # The creating admin should not notify themselves.
        self.assertFalse(UserNotification.objects.filter(recipient=self.admin).exists())

    def test_editing_a_scheduled_scripture_to_todays_date_publishes_immediately(self):
        member = UserFactory(email="scripture-member-edit@example.com")
        entry = ScriptureOfTheDay.objects.create(
            date=timezone.localdate() + timedelta(days=5),
            bible_text="Psalm 23:1",
            scripture="The Lord is my shepherd.",
            prayer="Guide us.",
            bible_version="KJV",
            status=ScriptureStatus.SCHEDULED,
            created_by=self.admin,
            updated_by=self.admin,
        )
        response = self.client.patch(
            reverse("admin-scripture-detail", kwargs={"pk": entry.id}),
            {"date": str(timezone.localdate())},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.status, ScriptureStatus.PUBLISHED)
        self.assertIsNotNone(entry.published_at)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=member, notification_type=NotificationType.SCRIPTURE_PUBLISHED
            ).exists()
        )

    def test_editing_a_scripture_without_changing_its_publish_status_does_not_renotify(self):
        member = UserFactory(email="scripture-member-noop@example.com")
        entry = ScriptureOfTheDay.objects.create(
            date=timezone.localdate() + timedelta(days=5),
            bible_text="Psalm 23:1",
            scripture="The Lord is my shepherd.",
            prayer="Guide us.",
            bible_version="KJV",
            status=ScriptureStatus.SCHEDULED,
            created_by=self.admin,
            updated_by=self.admin,
        )
        response = self.client.patch(
            reverse("admin-scripture-detail", kwargs={"pk": entry.id}),
            {"prayer": "Guide us always."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.status, ScriptureStatus.SCHEDULED)
        self.assertFalse(UserNotification.objects.filter(recipient=member).exists())

    def test_publish_due_scheduled_scriptures_command_notifies_users(self):
        # The cron-driven path (apps.content.management.commands.publish_due_scriptures)
        # has no admin actor -- unlike the immediate create/edit paths above,
        # every active non-admin user should be notified, including whoever
        # happens to be an admin (they're still excluded).
        member = UserFactory(email="scripture-member-cron@example.com")
        ScriptureOfTheDay.objects.create(
            date=timezone.localdate() - timedelta(days=1),
            bible_text="Isaiah 40:31",
            scripture="They that wait upon the Lord shall renew their strength.",
            prayer="Strengthen us.",
            bible_version="KJV",
            status=ScriptureStatus.SCHEDULED,
            created_by=self.admin,
            updated_by=self.admin,
        )

        published_count = publish_due_scheduled_scriptures()

        self.assertEqual(published_count, 1)
        notification = UserNotification.objects.get(recipient=member)
        self.assertEqual(notification.notification_type, NotificationType.SCRIPTURE_PUBLISHED)
        self.assertIn("Isaiah 40:31", notification.message)
        self.assertFalse(UserNotification.objects.filter(recipient=self.admin).exists())

    def test_phase7_slice5_home_feed_curation(self):
        category = TestimonyCategory.objects.create(name="Healing", slug="healing")
        author = UserFactory()
        approved = Testimony.objects.create(
            author=author,
            category=category,
            title="Featured Testimony",
            body="God did it.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        response = self.client.put(
            reverse("admin-home-curation"),
            {
                "section_order": [
                    HomeSectionKey.SCRIPTURE,
                    HomeSectionKey.FEATURED_TESTIMONIES,
                    HomeSectionKey.INSPIRATIONAL_PICTURE,
                ],
                "featured_testimony_ids": [approved.id],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FeaturedHomeTestimony.objects.count(), 1)
        self.assertEqual(HomeSectionOrder.objects.count(), 3)
        self.assertEqual(HomeSectionOrder.objects.order_by("position").first().section, HomeSectionKey.SCRIPTURE)

    def test_phase7_slice5_home_feed_picture_curation_add_reorder_remove(self):
        category = InspirationalPictureCategory.objects.create(name="Hope", slug="hope")
        first = InspirationalPicture.objects.create(
            title="Morning Mercy",
            category=category,
            source="Instagram",
            image_url="https://images.example.com/1.jpg",
            status=InspirationalPictureStatus.PUBLISHED,
        )
        second = InspirationalPicture.objects.create(
            title="Grace Note",
            category=category,
            source="Instagram",
            image_url="https://images.example.com/2.jpg",
            status=InspirationalPictureStatus.PUBLISHED,
        )
        unpublished = InspirationalPicture.objects.create(
            title="Draft Picture",
            category=category,
            source="Instagram",
            image_url="https://images.example.com/3.jpg",
            status=InspirationalPictureStatus.DRAFT,
        )

        # Adding an unpublished picture is rejected.
        rejected = self.client.put(
            reverse("admin-home-curation"),
            {
                "section_order": [
                    HomeSectionKey.SCRIPTURE,
                    HomeSectionKey.FEATURED_TESTIMONIES,
                    HomeSectionKey.INSPIRATIONAL_PICTURE,
                ],
                "featured_testimony_ids": [],
                "featured_picture_ids": [unpublished.id],
            },
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(FeaturedHomePicture.objects.count(), 0)

        # Add both published pictures, first then second.
        added = self.client.put(
            reverse("admin-home-curation"),
            {
                "section_order": [
                    HomeSectionKey.SCRIPTURE,
                    HomeSectionKey.FEATURED_TESTIMONIES,
                    HomeSectionKey.INSPIRATIONAL_PICTURE,
                ],
                "featured_testimony_ids": [],
                "featured_picture_ids": [first.id, second.id],
            },
            content_type="application/json",
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(FeaturedHomePicture.objects.count(), 2)
        self.assertEqual(
            list(FeaturedHomePicture.objects.order_by("position").values_list("picture_id", flat=True)),
            [first.id, second.id],
        )
        payload = added.json()
        self.assertEqual(len(payload["featured_pictures"]), 2)
        self.assertEqual(len(payload["available_pictures"]), 0)

        # Reorder: second first, first second.
        reordered = self.client.put(
            reverse("admin-home-curation"),
            {
                "section_order": [
                    HomeSectionKey.SCRIPTURE,
                    HomeSectionKey.FEATURED_TESTIMONIES,
                    HomeSectionKey.INSPIRATIONAL_PICTURE,
                ],
                "featured_testimony_ids": [],
                "featured_picture_ids": [second.id, first.id],
            },
            content_type="application/json",
        )
        self.assertEqual(reordered.status_code, 200)
        self.assertEqual(
            list(FeaturedHomePicture.objects.order_by("position").values_list("picture_id", flat=True)),
            [second.id, first.id],
        )

        # Remove one via the dedicated remove endpoint.
        removed = self.client.post(
            reverse("admin-home-curation-featured-picture-remove", args=[second.id]),
            content_type="application/json",
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(FeaturedHomePicture.objects.count(), 1)
        self.assertEqual(FeaturedHomePicture.objects.first().picture_id, first.id)

    def test_phase7_slice6_to_8_mobile_read_endpoints(self):
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        author = UserFactory()
        approved = Testimony.objects.create(
            author=author,
            category=category,
            title="Approved Home Testimony",
            body="A living testimony.",
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.APPROVED,
            video_url="https://res.cloudinary.com/itestified/video/upload/v1784672029/exmoriihzrotlki5en5k.mp4",
            thumbnail_url="",
        )
        FeaturedHomeTestimony.objects.create(testimony=approved, position=0, created_by=self.admin, updated_by=self.admin)
        HomeSectionOrder.objects.create(section=HomeSectionKey.FEATURED_TESTIMONIES, position=0)
        HomeSectionOrder.objects.create(section=HomeSectionKey.INSPIRATIONAL_PICTURE, position=1)
        HomeSectionOrder.objects.create(section=HomeSectionKey.SCRIPTURE, position=2)
        picture = InspirationalPicture.objects.create(
            title="Faith",
            caption="Keep believing.",
            category=InspirationalPictureCategory.objects.create(name="Hope", slug="hope"),
            source="Internal",
            image_url="https://images.example.com/mobile.jpg",
            status=InspirationalPictureStatus.PUBLISHED,
            created_by=self.admin,
            updated_by=self.admin,
        )
        FeaturedHomePicture.objects.create(picture=picture, position=0, created_by=self.admin, updated_by=self.admin)
        ScriptureOfTheDay.objects.create(
            date=timezone.localdate(),
            bible_text="Psalm 23:1",
            scripture="The Lord is my shepherd.",
            prayer="Lead us.",
            bible_version="KJV",
            status=ScriptureStatus.PUBLISHED,
            created_by=self.admin,
            updated_by=self.admin,
        )

        home_feed = self.client.get(reverse("mobile-home-feed"))
        self.assertEqual(home_feed.status_code, 200)
        self.assertEqual(home_feed.json()["section_order"][0], HomeSectionKey.FEATURED_TESTIMONIES)
        self.assertEqual(len(home_feed.json()["featured_testimonies"]), 1)
        self.assertEqual(
            home_feed.json()["featured_testimonies"][0]["thumbnail_url"],
            "https://res.cloudinary.com/itestified/video/upload/so_2,w_1280,h_720,c_fill,g_auto/v1784672029/exmoriihzrotlki5en5k.jpg",
        )
        self.assertEqual(len(home_feed.json()["inspirational_pictures"]), 1)
        self.assertEqual(home_feed.json()["inspirational_pictures"][0]["image_url"], "https://images.example.com/mobile.jpg")

        pictures = self.client.get(reverse("mobile-inspirational-pictures"))
        self.assertEqual(pictures.status_code, 200)
        self.assertEqual(len(pictures.json()["results"]), 1)

        scripture = self.client.get(reverse("mobile-scripture-today"))
        self.assertEqual(scripture.status_code, 200)
        self.assertEqual(scripture.json()["result"]["bible_text"], "Psalm 23:1")

    def test_admin_scripture_get_is_read_only_and_does_not_auto_publish(self):
        entry = ScriptureOfTheDay.objects.create(
            date=timezone.localdate() - timedelta(days=1),
            bible_text="Romans 8:28",
            scripture="All things work together...",
            prayer="Thank you Lord.",
            bible_version="KJV",
            status=ScriptureStatus.SCHEDULED,
            created_by=self.admin,
            updated_by=self.admin,
        )

        response = self.client.get(reverse("admin-scripture-list-create"))
        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.status, ScriptureStatus.SCHEDULED)
        self.assertIsNone(entry.published_at)

    def test_scripture_streak_stats_bucket_active_users_by_streak_length(self):
        today = timezone.localdate()
        ProfileFactory(
            user=UserFactory(email="s1@example.com"),
            scripture_streak_count=2,
            scripture_last_read_date=today,
        )
        ProfileFactory(
            user=UserFactory(email="s2@example.com"),
            scripture_streak_count=5,
            scripture_last_read_date=today - timedelta(days=1),
        )
        ProfileFactory(
            user=UserFactory(email="s3@example.com"),
            scripture_streak_count=15,
            scripture_last_read_date=today,
        )
        ProfileFactory(
            user=UserFactory(email="s4@example.com"),
            scripture_streak_count=40,
            scripture_last_read_date=today,
        )
        # Stale -- last read 3 days ago, so this shouldn't count as active
        # even though scripture_streak_count is still nonzero (it only gets
        # reset lazily on that user's *next* read).
        ProfileFactory(
            user=UserFactory(email="s5@example.com"),
            scripture_streak_count=10,
            scripture_last_read_date=today - timedelta(days=3),
        )
        # Never read at all.
        ProfileFactory(
            user=UserFactory(email="s6@example.com"),
            scripture_streak_count=0,
            scripture_last_read_date=None,
        )

        response = self.client.get(reverse("admin-scripture-streak-stats"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["active_streak_user_count"], 4)
        self.assertEqual(
            payload["streak_length_distribution"],
            {"1_to_3_days": 1, "4_to_7_days": 1, "8_to_30_days": 1, "31_plus_days": 1},
        )

    def test_scripture_streak_stats_requires_admin(self):
        self.client.logout()

        response = self.client.get(reverse("admin-scripture-streak-stats"))

        self.assertIn(response.status_code, (401, 403))

    def test_publish_due_scriptures_management_command_publishes_due_entries(self):
        due = ScriptureOfTheDay.objects.create(
            date=timezone.localdate() - timedelta(days=1),
            bible_text="Romans 8:28",
            scripture="All things work together...",
            prayer="Thank you Lord.",
            bible_version="KJV",
            status=ScriptureStatus.SCHEDULED,
            created_by=self.admin,
            updated_by=self.admin,
        )
        future = ScriptureOfTheDay.objects.create(
            date=timezone.localdate() + timedelta(days=3),
            bible_text="John 3:16",
            scripture="For God so loved the world...",
            prayer="Help us trust you.",
            bible_version="KJV",
            status=ScriptureStatus.SCHEDULED,
            created_by=self.admin,
            updated_by=self.admin,
        )

        out = StringIO()
        call_command("publish_due_scriptures", stdout=out)

        due.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(due.status, ScriptureStatus.PUBLISHED)
        self.assertIsNotNone(due.published_at)
        self.assertEqual(future.status, ScriptureStatus.SCHEDULED)

    def test_publish_due_inspirational_pictures_management_command_publishes_due_entries(self):
        due = InspirationalPicture.objects.create(
            title="Due Picture",
            caption="Ready now.",
            image_url="https://images.example.com/due.jpg",
            status=InspirationalPictureStatus.SCHEDULED,
            publish_at=timezone.now() - timedelta(minutes=5),
            created_by=self.admin,
            updated_by=self.admin,
        )
        future = InspirationalPicture.objects.create(
            title="Future Picture",
            caption="Later.",
            image_url="https://images.example.com/future.jpg",
            status=InspirationalPictureStatus.SCHEDULED,
            publish_at=timezone.now() + timedelta(days=1),
            created_by=self.admin,
            updated_by=self.admin,
        )

        out = StringIO()
        call_command("publish_due_inspirational_pictures", stdout=out)

        due.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(due.status, InspirationalPictureStatus.PUBLISHED)
        self.assertEqual(future.status, InspirationalPictureStatus.SCHEDULED)


class ScriptureReadApiTests(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory(email="scripture-read-api@example.com")
        ProfileFactory(user=self.user, full_name="Scripture Reader")
        self.token = Token.objects.create(user=self.user)
        self.today = timezone.localdate()

    def test_mark_read_requires_authentication(self) -> None:
        response = self.client.post(
            reverse("mobile-scripture-today-read"),
            {"read_date": self.today.isoformat()},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)

    def test_mark_read_returns_the_updated_streak_state(self) -> None:
        response = self.client.post(
            reverse("mobile-scripture-today-read"),
            {"read_date": self.today.isoformat()},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["streak_count"], 1)
        self.assertEqual(body["last_read_date"], self.today.isoformat())
        self.assertEqual(body["freezes_remaining"], 2)

    def test_mark_read_rejects_a_missing_read_date(self) -> None:
        response = self.client.post(
            reverse("mobile-scripture-today-read"),
            {},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.status_code, 400)

    def test_mark_read_rejects_a_date_far_from_today(self) -> None:
        response = self.client.post(
            reverse("mobile-scripture-today-read"),
            {"read_date": (self.today - timedelta(days=30)).isoformat()},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.status_code, 400)

    def test_home_feed_scripture_streak_is_null_for_a_guest(self) -> None:
        response = self.client.get(reverse("mobile-home-feed"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["scripture_streak"])

    def test_home_feed_scripture_streak_reflects_the_users_real_state(self) -> None:
        self.client.post(
            reverse("mobile-scripture-today-read"),
            {"read_date": self.today.isoformat()},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        response = self.client.get(
            reverse("mobile-home-feed"),
            HTTP_AUTHORIZATION=f"Token {self.token.key}",
        )

        self.assertEqual(response.status_code, 200)
        streak = response.json()["scripture_streak"]
        self.assertEqual(streak["streak_count"], 1)
        self.assertTrue(streak["read_today"])
        self.assertEqual(streak["freezes_remaining"], 2)
        self.assertIn(self.today.isoformat(), streak["recent_read_dates"])


class HomeCarouselApiTests(TestCase):
    """Phase 20 Slice 1 -- the immersive Home carousel is fully automatic
    (no admin curation), blending published inspirational pictures with
    approved testimonies that have a moderator-curated pull_quote."""

    def setUp(self) -> None:
        self.category = TestimonyCategory.objects.create(name="Healing", slug="healing")
        self.author = UserFactory(email="carousel-author@example.com")
        ProfileFactory(user=self.author, full_name="Grace A.")

    def _testimony(self, *, pull_quote: str = "", status: str = TestimonyStatus.APPROVED, title: str = "Testimony"):
        return Testimony.objects.create(
            author=self.author,
            category=self.category,
            title=title,
            body="God did it.",
            testimony_type=TestimonyType.WRITTEN,
            status=status,
            pull_quote=pull_quote,
        )

    def test_carousel_is_public_and_blends_pictures_with_pull_quote_testimonies(self) -> None:
        picture = InspirationalPicture.objects.create(
            title="Morning Mercy",
            caption="God is faithful.",
            image_url="https://images.example.com/pic.jpg",
            status=InspirationalPictureStatus.PUBLISHED,
        )
        testimony = self._testimony(pull_quote="God turned my mourning into dancing.")

        response = self.client.get(reverse("mobile-home-carousel"))

        self.assertEqual(response.status_code, 200)
        slides = response.json()["results"]
        kinds = {slide["kind"] for slide in slides}
        self.assertEqual(kinds, {"picture", "testimony_quote"})

        picture_slide = next(slide for slide in slides if slide["kind"] == "picture")
        self.assertEqual(picture_slide["id"], picture.id)
        self.assertEqual(picture_slide["title"], "Morning Mercy")

        quote_slide = next(slide for slide in slides if slide["kind"] == "testimony_quote")
        self.assertEqual(quote_slide["id"], testimony.id)
        self.assertEqual(quote_slide["pull_quote"], "God turned my mourning into dancing.")
        self.assertEqual(quote_slide["speaker"], "Grace A.")
        self.assertEqual(quote_slide["category"], "Healing")

    def test_carousel_excludes_unpublished_and_expired_pictures(self) -> None:
        InspirationalPicture.objects.create(
            title="Draft",
            image_url="https://images.example.com/draft.jpg",
            status=InspirationalPictureStatus.DRAFT,
        )
        InspirationalPicture.objects.create(
            title="Expired",
            image_url="https://images.example.com/expired.jpg",
            status=InspirationalPictureStatus.PUBLISHED,
            expires_at=timezone.now() - timedelta(days=1),
        )

        response = self.client.get(reverse("mobile-home-carousel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_carousel_excludes_non_approved_and_blank_pull_quote_testimonies(self) -> None:
        self._testimony(pull_quote="", title="No quote")
        self._testimony(pull_quote="A pending quote.", status=TestimonyStatus.PENDING_REVIEW, title="Not approved yet")

        response = self.client.get(reverse("mobile-home-carousel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])


class HomePromoCardApiTests(TestCase):
    """Phase 20 Slice 6: admin authors a native "From iTestified" card from
    the dashboard. Mobile rendering (Slice 7) isn't built yet -- this
    covers only the admin CRUD/activation surface, mirroring
    InspirationalPicture's own admin tests above."""

    def setUp(self):
        self.admin = UserFactory(email="promo-admin@example.com")
        AdminAssignmentFactory(user=self.admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        self.client.force_login(self.admin)

    def test_requires_authentication(self):
        # SessionAuthentication sets no WWW-Authenticate header, so DRF
        # returns 403 (not 401) for a fully anonymous request here, same as
        # every other session-only admin view in this codebase.
        self.client.logout()
        response = self.client.get(reverse("admin-home-promo-list-create"))
        self.assertEqual(response.status_code, 403)

    def test_rejects_token_authentication(self):
        # Admin views must stay Session-authenticated only, matching every
        # other admin surface in this app.
        self.client.logout()
        token = Token.objects.create(user=self.admin)
        response = self.client.get(
            reverse("admin-home-promo-list-create"), HTTP_AUTHORIZATION=f"Token {token.key}"
        )
        self.assertEqual(response.status_code, 403)

    def test_create_a_promo_card_with_no_cta(self):
        response = self.client.post(
            reverse("admin-home-promo-list-create"),
            {
                "title": "Invite a friend to iTestified",
                "body": "Share the app with someone who needs a testimony today.",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        card = HomePromoCard.objects.get()
        self.assertEqual(card.title, "Invite a friend to iTestified")
        self.assertEqual(card.created_by, self.admin)
        self.assertEqual(card.updated_by, self.admin)
        self.assertEqual(response.json()["status"], HomePromoCardStatus.ACTIVE)

    def test_create_a_promo_card_with_a_giving_cta(self):
        response = self.client.post(
            reverse("admin-home-promo-list-create"),
            {
                "title": "Someone's breakthrough is waiting on yours",
                "body": "Every gift keeps testimonies free to read, share, and film.",
                "cta_label": "Give Today",
                "cta_destination": "giving",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        card = HomePromoCard.objects.get()
        self.assertEqual(card.cta_label, "Give Today")
        self.assertEqual(card.cta_destination, "giving")

    def test_rejects_a_cta_label_without_a_destination(self):
        response = self.client.post(
            reverse("admin-home-promo-list-create"),
            {"title": "T", "body": "B", "cta_label": "Give Today"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HomePromoCard.objects.exists())

    def test_rejects_an_external_url_cta_with_no_url(self):
        response = self.client.post(
            reverse("admin-home-promo-list-create"),
            {
                "title": "Join us live",
                "body": "B",
                "cta_label": "Learn More",
                "cta_destination": "external_url",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HomePromoCard.objects.exists())

    def test_accepts_an_external_url_cta_with_a_url(self):
        response = self.client.post(
            reverse("admin-home-promo-list-create"),
            {
                "title": "Join us live",
                "body": "B",
                "cta_label": "Learn More",
                "cta_destination": "external_url",
                "cta_url": "https://itestified.app/events/convention",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_rejects_an_end_date_before_the_start_date(self):
        now = timezone.now()
        response = self.client.post(
            reverse("admin-home-promo-list-create"),
            {
                "title": "T",
                "body": "B",
                "starts_at": (now + timedelta(days=5)).isoformat(),
                "ends_at": (now + timedelta(days=1)).isoformat(),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(HomePromoCard.objects.exists())

    def test_edit_updates_fields_and_records_the_editor(self):
        card = HomePromoCard.objects.create(title="Old title", body="Old body", created_by=self.admin)
        other_admin = UserFactory(email="second-admin@example.com")
        AdminAssignmentFactory(user=other_admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        self.client.force_login(other_admin)

        response = self.client.patch(
            reverse("admin-home-promo-detail", kwargs={"pk": card.id}),
            {"title": "New title"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        card.refresh_from_db()
        self.assertEqual(card.title, "New title")
        self.assertEqual(card.updated_by, other_admin)

    def test_activation_toggle_post_activates_and_delete_deactivates(self):
        card = HomePromoCard.objects.create(title="T", body="B", is_active=False)

        activate = self.client.post(reverse("admin-home-promo-activation", kwargs={"promo_id": card.id}))
        self.assertEqual(activate.status_code, 200)
        card.refresh_from_db()
        self.assertTrue(card.is_active)

        deactivate = self.client.delete(reverse("admin-home-promo-activation", kwargs={"promo_id": card.id}))
        self.assertEqual(deactivate.status_code, 200)
        card.refresh_from_db()
        self.assertFalse(card.is_active)
        self.assertEqual(deactivate.json()["status"], HomePromoCardStatus.INACTIVE)

    def test_activation_on_a_missing_card_returns_404(self):
        response = self.client.post(reverse("admin-home-promo-activation", kwargs={"promo_id": 999999}))
        self.assertEqual(response.status_code, 404)

    def test_list_computed_status_reflects_the_date_window(self):
        now = timezone.now()
        active = HomePromoCard.objects.create(title="Active", body="B", starts_at=now - timedelta(days=1))
        scheduled = HomePromoCard.objects.create(title="Scheduled", body="B", starts_at=now + timedelta(days=1))
        ended = HomePromoCard.objects.create(
            title="Ended", body="B", starts_at=now - timedelta(days=10), ends_at=now - timedelta(days=1)
        )
        inactive = HomePromoCard.objects.create(title="Inactive", body="B", is_active=False)

        response = self.client.get(reverse("admin-home-promo-list-create"))

        self.assertEqual(response.status_code, 200)
        status_by_id = {row["id"]: row["status"] for row in response.json()["results"]}
        self.assertEqual(status_by_id[active.id], HomePromoCardStatus.ACTIVE)
        self.assertEqual(status_by_id[scheduled.id], HomePromoCardStatus.SCHEDULED)
        self.assertEqual(status_by_id[ended.id], HomePromoCardStatus.ENDED)
        self.assertEqual(status_by_id[inactive.id], HomePromoCardStatus.INACTIVE)

    def test_list_filters_by_computed_status(self):
        now = timezone.now()
        HomePromoCard.objects.create(title="Active", body="B", starts_at=now - timedelta(days=1))
        HomePromoCard.objects.create(title="Scheduled", body="B", starts_at=now + timedelta(days=1))

        response = self.client.get(reverse("admin-home-promo-list-create"), {"status": "scheduled"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()["results"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "Scheduled")

    def test_list_searches_by_title(self):
        HomePromoCard.objects.create(title="Give today", body="B")
        HomePromoCard.objects.create(title="Invite a friend", body="B")

        response = self.client.get(reverse("admin-home-promo-list-create"), {"q": "invite"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()["results"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "Invite a friend")


class MobileHomePromoCardsApiTests(TestCase):
    """Phase 20 Slice 7: the public read endpoint mobile weaves into the
    continuous feed at its own cadence."""

    def test_is_public(self):
        response = self.client.get(reverse("mobile-home-promo-cards"))
        self.assertEqual(response.status_code, 200)

    def test_returns_an_active_in_window_card(self):
        now = timezone.now()
        HomePromoCard.objects.create(
            title="Give Today",
            body="B",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
        )
        response = self.client.get(reverse("mobile-home-promo-cards"))
        payload = response.json()["results"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "Give Today")
        # Admin-only fields never leak to the public endpoint.
        self.assertNotIn("is_active", payload[0])
        self.assertNotIn("updated_by_email", payload[0])
        self.assertNotIn("starts_at", payload[0])

    def test_excludes_a_scheduled_card(self):
        now = timezone.now()
        HomePromoCard.objects.create(title="Not yet", body="B", starts_at=now + timedelta(days=1))
        response = self.client.get(reverse("mobile-home-promo-cards"))
        self.assertEqual(response.json()["results"], [])

    def test_excludes_an_ended_card(self):
        now = timezone.now()
        HomePromoCard.objects.create(
            title="Over", body="B", starts_at=now - timedelta(days=10), ends_at=now - timedelta(days=1)
        )
        response = self.client.get(reverse("mobile-home-promo-cards"))
        self.assertEqual(response.json()["results"], [])

    def test_excludes_an_inactive_card(self):
        now = timezone.now()
        HomePromoCard.objects.create(
            title="Off", body="B", starts_at=now - timedelta(days=1), is_active=False
        )
        response = self.client.get(reverse("mobile-home-promo-cards"))
        self.assertEqual(response.json()["results"], [])

    def test_returns_a_card_with_no_end_date(self):
        now = timezone.now()
        HomePromoCard.objects.create(title="Always on", body="B", starts_at=now - timedelta(days=1))
        response = self.client.get(reverse("mobile-home-promo-cards"))
        payload = response.json()["results"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "Always on")
