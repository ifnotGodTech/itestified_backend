from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.content.models import (
    FeaturedHomeTestimony,
    HomeSectionKey,
    HomeSectionOrder,
    InspirationalPicture,
    InspirationalPictureStatus,
    ScriptureOfTheDay,
    ScriptureStatus,
)
from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.choices import AdminRoleCode
from apps.users.tests.factories import AdminAssignmentFactory, AdminRoleFactory, UserFactory


class ContentAdminApiTests(TestCase):
    def setUp(self):
        self.admin = UserFactory(email="content-admin@example.com")
        AdminAssignmentFactory(user=self.admin, role=AdminRoleFactory(code=AdminRoleCode.CONTENT_ADMIN))
        self.client.force_login(self.admin)

    def test_phase7_slice1_upload_inspirational_picture(self):
        response = self.client.post(
            reverse("admin-inspirational-picture-list-create"),
            {
                "title": "Morning Mercy",
                "caption": "God is faithful.",
                "category": "Hope",
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

    def test_phase7_slice2_edit_or_unpublish_picture(self):
        picture = InspirationalPicture.objects.create(
            title="Grace",
            caption="Caption A",
            category="Faith",
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

    def test_phase7_slice6_to_8_mobile_read_endpoints(self):
        category = TestimonyCategory.objects.create(name="Faith", slug="faith")
        author = UserFactory()
        approved = Testimony.objects.create(
            author=author,
            category=category,
            title="Approved Home Testimony",
            body="A living testimony.",
            testimony_type=TestimonyType.WRITTEN,
            status=TestimonyStatus.APPROVED,
        )
        FeaturedHomeTestimony.objects.create(testimony=approved, position=0, created_by=self.admin, updated_by=self.admin)
        HomeSectionOrder.objects.create(section=HomeSectionKey.FEATURED_TESTIMONIES, position=0)
        HomeSectionOrder.objects.create(section=HomeSectionKey.INSPIRATIONAL_PICTURE, position=1)
        HomeSectionOrder.objects.create(section=HomeSectionKey.SCRIPTURE, position=2)
        InspirationalPicture.objects.create(
            title="Faith",
            caption="Keep believing.",
            category="Hope",
            source="Internal",
            image_url="https://images.example.com/mobile.jpg",
            status=InspirationalPictureStatus.PUBLISHED,
            created_by=self.admin,
            updated_by=self.admin,
        )
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
