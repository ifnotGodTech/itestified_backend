import os
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.content.models import (
    FeaturedHomePicture,
    FeaturedHomeTestimony,
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
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


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
