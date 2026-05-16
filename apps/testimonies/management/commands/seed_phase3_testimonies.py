from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.testimonies.models import Testimony, TestimonyCategory, TestimonyStatus, TestimonyType
from apps.users.models import Profile, User


class Command(BaseCommand):
    help = "Seed Phase 3 testimonies data for QA (idempotent)."

    def handle(self, *args, **options):
        categories = [
            ("Healing", "healing", "Healing stories"),
            ("Faith", "faith", "Faith stories"),
            ("Deliverance", "deliverance", "Deliverance stories"),
            ("Salvation", "salvation", "Salvation stories"),
        ]
        category_map = {}
        for name, slug, description in categories:
            category, _ = TestimonyCategory.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "description": description, "is_active": True},
            )
            category_map[slug] = category

        users = [
            ("qa.author1@example.com", "QA Author One"),
            ("qa.author2@example.com", "QA Author Two"),
            ("qa.viewer@example.com", "QA Viewer"),
        ]
        user_map = {}
        for email, full_name in users:
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={"username": email, "account_status": "active"},
            )
            user.username = email
            user.account_status = "active"
            user.set_password("TestPass#123")
            user.save(update_fields=["username", "account_status", "password"])
            Profile.objects.update_or_create(user=user, defaults={"full_name": full_name})
            Token.objects.get_or_create(user=user)
            user_map[email] = user

        seed_rows = [
            {
                "title": "God healed me from chronic pain",
                "author": user_map["qa.author1@example.com"],
                "category": category_map["healing"],
                "status": TestimonyStatus.APPROVED,
                "testimony_type": TestimonyType.WRITTEN,
                "body": "After months of pain, I received healing during prayer.",
                "video_url": "",
                "thumbnail_url": "",
                "rejection_reason": "",
            },
            {
                "title": "Breakthrough after fasting",
                "author": user_map["qa.author2@example.com"],
                "category": category_map["faith"],
                "status": TestimonyStatus.PENDING_REVIEW,
                "testimony_type": TestimonyType.WRITTEN,
                "body": "A new job door opened after a focused prayer season.",
                "video_url": "",
                "thumbnail_url": "",
                "rejection_reason": "",
            },
            {
                "title": "Delivered from fear",
                "author": user_map["qa.author1@example.com"],
                "category": category_map["deliverance"],
                "status": TestimonyStatus.REJECTED,
                "testimony_type": TestimonyType.WRITTEN,
                "body": "I am sharing how I found freedom from fear.",
                "video_url": "",
                "thumbnail_url": "",
                "rejection_reason": "Please add more specific details and context.",
            },
            {
                "title": "Video testimony: Restoration",
                "author": user_map["qa.author2@example.com"],
                "category": category_map["salvation"],
                "status": TestimonyStatus.APPROVED,
                "testimony_type": TestimonyType.VIDEO,
                "body": "",
                "video_url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_1MB.mp4",
                "thumbnail_url": "https://placehold.co/800x450/png",
                "rejection_reason": "",
            },
        ]

        for row in seed_rows:
            publish_at = timezone.now() if row["status"] == TestimonyStatus.APPROVED else None
            Testimony.objects.update_or_create(
                title=row["title"],
                defaults={
                    "author": row["author"],
                    "category": row["category"],
                    "status": row["status"],
                    "testimony_type": row["testimony_type"],
                    "body": row["body"],
                    "video_url": row["video_url"],
                    "thumbnail_url": row["thumbnail_url"],
                    "rejection_reason": row["rejection_reason"],
                    "publish_at": publish_at,
                    "updated_at": timezone.now(),
                },
            )

        self.stdout.write(self.style.SUCCESS("Phase 3 testimonies seed completed."))
        self.stdout.write("QA users (password: TestPass#123):")
        self.stdout.write("- qa.author1@example.com")
        self.stdout.write("- qa.author2@example.com")
        self.stdout.write("- qa.viewer@example.com")
