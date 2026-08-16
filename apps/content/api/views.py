from datetime import timedelta
from typing import Optional

from django.utils import timezone
from django.db import models
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.common.services.media_uploads import CloudinaryUploadError, create_direct_upload_signature
from apps.content.exceptions import ContentError
from apps.content.models import (
    FeaturedHomePicture,
    FeaturedHomeTestimony,
    HomePromoCard,
    HomeSectionKey,
    HomeSectionOrder,
    InspirationalPicture,
    InspirationalPictureCategory,
    InspirationalPictureStatus,
    ScriptureOfTheDay,
    ScriptureReadReceipt,
    ScriptureStatus,
)
from apps.content.services.commands import mark_scripture_read, scripture_streak_freezes_remaining
from apps.content.services.queries import home_carousel_slides, scripture_streak_engagement_stats
from apps.notifications.services import notify_all_users_of_scripture_published
from apps.testimonies.models import Testimony, TestimonyStatus
from apps.testimonies.services.media_uploads import build_cloudinary_video_thumbnail_url
from apps.users.models import Profile

from .serializers import (
    FeaturedHomePictureSerializer,
    FeaturedHomeTestimonySerializer,
    HomeCurationUpdateSerializer,
    HomePromoCardSerializer,
    HomeSectionOrderSerializer,
    InspirationalPictureCategorySerializer,
    InspirationalPictureSerializer,
    ScriptureReadInputSerializer,
    ScriptureSerializer,
)


class ContentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminInspirationalPictureCategoryListCreateView(generics.ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = InspirationalPictureCategorySerializer
    queryset = InspirationalPictureCategory.objects.all().order_by("name")
    pagination_class = None


class AdminInspirationalPictureCategoryDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = InspirationalPictureCategorySerializer
    queryset = InspirationalPictureCategory.objects.all()


class AdminInspirationalPictureCategoryActivationView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, category_id: int):
        category = InspirationalPictureCategory.objects.filter(id=category_id).first()
        if category is None:
            return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = InspirationalPictureCategorySerializer(category, data={"is_active": True}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, category_id: int):
        category = InspirationalPictureCategory.objects.filter(id=category_id).first()
        if category is None:
            return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = InspirationalPictureCategorySerializer(category, data={"is_active": False}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminInspirationalPictureUploadSignatureView(APIView):
    """Issues a signed Cloudinary direct-upload payload so the dashboard can
    upload a picture file straight to Cloudinary without proxying the bytes
    through this server -- same pattern as testimony/avatar media uploads
    (see apps.common.services.media_uploads)."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request):
        try:
            upload_signature = create_direct_upload_signature(resource_type="inspirational_picture")
        except CloudinaryUploadError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "cloud_name": upload_signature.cloud_name,
                "api_key": upload_signature.api_key,
                "timestamp": upload_signature.timestamp,
                "folder": upload_signature.folder,
                "signature": upload_signature.signature,
                "resource_type": "image",
            },
            status=status.HTTP_200_OK,
        )


class AdminInspirationalPictureListCreateView(generics.ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = InspirationalPictureSerializer
    pagination_class = ContentPagination

    def get_queryset(self):
        queryset = InspirationalPicture.objects.all()
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        search_text = (self.request.query_params.get("q") or "").strip()
        if status_filter in {"draft", "scheduled", "published", "unpublished"}:
            queryset = queryset.filter(status=status_filter)
        if search_text:
            queryset = queryset.filter(title__icontains=search_text)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)


class AdminInspirationalPictureDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = InspirationalPictureSerializer
    queryset = InspirationalPicture.objects.all()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class AdminInspirationalPictureUnpublishView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, picture_id: int):
        picture = InspirationalPicture.objects.filter(id=picture_id).first()
        if picture is None:
            return Response({"message": "Picture not found."}, status=status.HTTP_404_NOT_FOUND)
        picture.status = InspirationalPictureStatus.UNPUBLISHED
        picture.updated_by = request.user
        picture.save(update_fields=["status", "updated_by", "updated_at"])
        return Response(InspirationalPictureSerializer(picture).data, status=status.HTTP_200_OK)


class AdminHomePromoCardUploadSignatureView(APIView):
    """Same direct-to-Cloudinary signing pattern as
    AdminInspirationalPictureUploadSignatureView -- the dashboard uploads
    the file straight to Cloudinary, this server never proxies the bytes."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request):
        try:
            upload_signature = create_direct_upload_signature(resource_type="home_promo_card")
        except CloudinaryUploadError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "cloud_name": upload_signature.cloud_name,
                "api_key": upload_signature.api_key,
                "timestamp": upload_signature.timestamp,
                "folder": upload_signature.folder,
                "signature": upload_signature.signature,
                "resource_type": "image",
            },
            status=status.HTTP_200_OK,
        )


class AdminHomePromoCardListCreateView(generics.ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = HomePromoCardSerializer
    pagination_class = ContentPagination

    def get_queryset(self):
        queryset = HomePromoCard.objects.all()
        search_text = (self.request.query_params.get("q") or "").strip()
        if search_text:
            queryset = queryset.filter(title__icontains=search_text)

        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        if status_filter in {"active", "scheduled", "ended", "inactive"}:
            # computed_status() isn't a DB column -- filter in Python over a
            # bounded admin list rather than duplicating the same window
            # logic as a queryset filter (this table is small by design,
            # unlike testimonies/donations).
            now = timezone.now()
            matching_ids = [card.id for card in queryset if card.computed_status(now=now) == status_filter]
            queryset = queryset.filter(id__in=matching_ids)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)


class AdminHomePromoCardDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = HomePromoCardSerializer
    queryset = HomePromoCard.objects.all()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class AdminHomePromoCardActivationView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, promo_id: int):
        return self._set_active(request, promo_id, True)

    def delete(self, request, promo_id: int):
        return self._set_active(request, promo_id, False)

    def _set_active(self, request, promo_id: int, is_active: bool):
        card = HomePromoCard.objects.filter(id=promo_id).first()
        if card is None:
            return Response({"message": "Promo card not found."}, status=status.HTTP_404_NOT_FOUND)
        card.is_active = is_active
        card.updated_by = request.user
        card.save(update_fields=["is_active", "updated_by", "updated_at"])
        return Response(HomePromoCardSerializer(card).data, status=status.HTTP_200_OK)


class AdminScriptureListCreateView(generics.ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = ScriptureSerializer
    pagination_class = ContentPagination

    def get_queryset(self):
        queryset = ScriptureOfTheDay.objects.all()
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        search_text = (self.request.query_params.get("q") or "").strip()
        if status_filter in {"scheduled", "published"}:
            queryset = queryset.filter(status=status_filter)
        if search_text:
            queryset = queryset.filter(bible_text__icontains=search_text)
        return queryset

    def perform_create(self, serializer):
        entry = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        # refresh_status_for_today() already sets published_at as part of
        # flipping the status, so checking "published_at is None" afterward
        # is always false -- the flip was never actually persisted. Compare
        # against the status before the call instead.
        previous_status = entry.status
        entry.refresh_status_for_today()
        if entry.status != previous_status:
            entry.save(update_fields=["status", "published_at", "updated_at"])
            if entry.status == ScriptureStatus.PUBLISHED:
                notify_all_users_of_scripture_published(scripture=entry, actor=self.request.user)


class AdminScriptureDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = ScriptureSerializer
    queryset = ScriptureOfTheDay.objects.all()

    def perform_update(self, serializer):
        entry = serializer.save(updated_by=self.request.user)
        # Same immediate-publish behavior as create: if an edit moves the
        # date to today (or earlier), it should go live now rather than
        # waiting for the next publish_due_scriptures run.
        previous_status = entry.status
        entry.refresh_status_for_today()
        if entry.status != previous_status:
            entry.save(update_fields=["status", "published_at", "updated_at"])
            if entry.status == ScriptureStatus.PUBLISHED:
                notify_all_users_of_scripture_published(scripture=entry, actor=self.request.user)


class AdminScriptureStreakStatsView(APIView):
    """Phase 17 Slice 4: lets an admin see whether the streak feature is
    actually being used -- not exposed to mobile."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        return Response(scripture_streak_engagement_stats())


class AdminHomeCurationView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request):
        section_rows = list(HomeSectionOrder.objects.all())
        if not section_rows:
            defaults = [
                HomeSectionKey.FEATURED_TESTIMONIES,
                HomeSectionKey.INSPIRATIONAL_PICTURE,
                HomeSectionKey.SCRIPTURE,
            ]
            for index, section in enumerate(defaults):
                HomeSectionOrder.objects.create(section=section, position=index)
            section_rows = list(HomeSectionOrder.objects.all())

        featured_rows = FeaturedHomeTestimony.objects.select_related("testimony", "testimony__category")
        available_rows = (
            Testimony.objects.filter(status=TestimonyStatus.APPROVED)
            .exclude(home_featured_entries__isnull=False)
            .select_related("category", "author")
            .order_by("-created_at")
        )
        available_payload = [
            {
                "id": row.id,
                "title": row.title,
                "category": row.category.name,
                "testimony_type": row.testimony_type,
                "body": row.body,
                "video_url": row.video_url,
                "thumbnail_url": row.thumbnail_url or build_cloudinary_video_thumbnail_url(row.video_url),
                "created_at": row.created_at,
                "author_name": row.author.get_full_name() or row.author.email,
            }
            for row in available_rows
        ]

        featured_picture_rows = FeaturedHomePicture.objects.select_related("picture", "picture__category")
        available_picture_rows = (
            InspirationalPicture.objects.filter(status=InspirationalPictureStatus.PUBLISHED)
            .exclude(home_featured_entries__isnull=False)
            .select_related("category")
            .order_by("-created_at")
        )
        available_picture_payload = [
            {
                "id": row.id,
                "title": row.title,
                "caption": row.caption,
                "category": row.category.name if row.category_id else "",
                "source": row.source,
                "image_url": row.image_url,
                "created_at": row.created_at,
            }
            for row in available_picture_rows
        ]

        return Response(
            {
                "section_order": HomeSectionOrderSerializer(section_rows, many=True).data,
                "featured_testimonies": FeaturedHomeTestimonySerializer(featured_rows, many=True).data,
                "available_testimonies": available_payload,
                "featured_pictures": FeaturedHomePictureSerializer(featured_picture_rows, many=True).data,
                "available_pictures": available_picture_payload,
            }
        )

    def put(self, request):
        serializer = HomeCurationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        section_order = serializer.validated_data["section_order"]
        featured_ids = serializer.validated_data["featured_testimony_ids"]
        featured_picture_ids = serializer.validated_data["featured_picture_ids"]

        for index, section in enumerate(section_order):
            HomeSectionOrder.objects.update_or_create(section=section, defaults={"position": index})

        FeaturedHomeTestimony.objects.exclude(testimony_id__in=featured_ids).delete()
        for index, testimony_id in enumerate(featured_ids):
            FeaturedHomeTestimony.objects.update_or_create(
                testimony_id=testimony_id,
                defaults={
                    "position": index,
                    "updated_by": request.user,
                    "created_by": request.user,
                },
            )

        FeaturedHomePicture.objects.exclude(picture_id__in=featured_picture_ids).delete()
        for index, picture_id in enumerate(featured_picture_ids):
            FeaturedHomePicture.objects.update_or_create(
                picture_id=picture_id,
                defaults={
                    "position": index,
                    "updated_by": request.user,
                    "created_by": request.user,
                },
            )
        return self.get(request)


class AdminFeaturedHomeTestimonyDeleteView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, testimony_id: int):
        FeaturedHomeTestimony.objects.filter(testimony_id=testimony_id).delete()
        return Response({"removed": testimony_id}, status=status.HTTP_200_OK)


class AdminFeaturedHomePictureDeleteView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, picture_id: int):
        FeaturedHomePicture.objects.filter(picture_id=picture_id).delete()
        return Response({"removed": picture_id}, status=status.HTTP_200_OK)


def _scripture_streak_payload(request) -> Optional[dict]:
    # Per-user, so only meaningful when the request actually carries a
    # recognized user -- deliberately not @authentication_classes([]) like
    # the rest of this view, since that would make the request's token
    # invisible even if one was sent (see permission_classes([]) below,
    # which still lets guests through with no streak data).
    if not request.user.is_authenticated:
        return None
    profile = Profile.objects.filter(user=request.user).first()
    if profile is None:
        return None
    today = timezone.localdate()
    recent_read_dates = list(
        ScriptureReadReceipt.objects.filter(
            user=request.user,
            read_date__gte=today - timedelta(days=6),
            read_date__lte=today,
        ).values_list("read_date", flat=True)
    )
    return {
        "streak_count": profile.scripture_streak_count,
        "last_read_date": profile.scripture_last_read_date,
        "freezes_remaining": scripture_streak_freezes_remaining(profile),
        "read_today": profile.scripture_last_read_date == today,
        "recent_read_dates": recent_read_dates,
    }


@api_view(["GET"])
@permission_classes([])
def mobile_home_feed_view(request):
    section_rows = list(HomeSectionOrder.objects.all().order_by("position", "id"))
    if not section_rows:
        section_rows = [
            HomeSectionOrder(section=HomeSectionKey.FEATURED_TESTIMONIES, position=0),
            HomeSectionOrder(section=HomeSectionKey.INSPIRATIONAL_PICTURE, position=1),
            HomeSectionOrder(section=HomeSectionKey.SCRIPTURE, position=2),
        ]
    section_order = [row.section for row in section_rows]

    featured = FeaturedHomeTestimony.objects.select_related("testimony", "testimony__category").order_by("position", "id")
    featured_payload = [
        {
            "id": row.testimony.id,
            "title": row.testimony.title,
            "category": row.testimony.category.name,
            "body": row.testimony.body,
            "testimony_type": row.testimony.testimony_type,
            "video_url": row.testimony.video_url,
            "thumbnail_url": row.testimony.thumbnail_url or build_cloudinary_video_thumbnail_url(row.testimony.video_url),
            "publish_at": row.testimony.publish_at,
            "created_at": row.testimony.created_at,
            "view_count": row.testimony.view_count,
            "comment_count": row.testimony.comment_count,
        }
        for row in featured
        if row.testimony.status == TestimonyStatus.APPROVED
    ]

    featured_pictures = (
        FeaturedHomePicture.objects.filter(picture__status=InspirationalPictureStatus.PUBLISHED)
        .select_related("picture", "picture__category")
        .order_by("position", "id")
    )
    featured_pictures_payload = FeaturedHomePictureSerializer(featured_pictures, many=True).data

    today = timezone.localdate()
    scripture = (
        ScriptureOfTheDay.objects.filter(status="published", date=today)
        .order_by("-updated_at")
        .first()
    )
    if scripture is None:
        scripture = ScriptureOfTheDay.objects.filter(status="published", date__lte=today).order_by("-date").first()

    return Response(
        {
            "section_order": section_order,
            "featured_testimonies": featured_payload,
            "inspirational_pictures": featured_pictures_payload,
            "scripture": ScriptureSerializer(scripture).data if scripture else None,
            "scripture_streak": _scripture_streak_payload(request),
        }
    )


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def mobile_home_carousel_view(request):
    return Response({"results": home_carousel_slides()})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def mobile_inspirational_pictures_list_view(request):
    now = timezone.now()
    queryset = (
        InspirationalPicture.objects.filter(status=InspirationalPictureStatus.PUBLISHED)
        .filter(models.Q(publish_at__isnull=True) | models.Q(publish_at__lte=now))
        .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
        .order_by("-updated_at")
    )
    return Response({"results": InspirationalPictureSerializer(queryset, many=True).data})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def mobile_scripture_today_view(request):
    today = timezone.localdate()
    entry = ScriptureOfTheDay.objects.filter(status="published", date=today).order_by("-updated_at").first()
    if entry is None:
        entry = ScriptureOfTheDay.objects.filter(status="published", date__lte=today).order_by("-date").first()
    return Response({"result": ScriptureSerializer(entry).data if entry else None})


class ScriptureReadView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ScriptureReadInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            profile = mark_scripture_read(
                user=request.user,
                read_date=serializer.validated_data["read_date"],
            )
        except ContentError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "streak_count": profile.scripture_streak_count,
                "last_read_date": profile.scripture_last_read_date,
                "freezes_remaining": scripture_streak_freezes_remaining(profile),
            },
            status=status.HTTP_200_OK,
        )
