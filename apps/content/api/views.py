from django.utils import timezone
from django.db import models
from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.content.models import (
    FeaturedHomeTestimony,
    HomeSectionKey,
    HomeSectionOrder,
    InspirationalPicture,
    InspirationalPictureStatus,
    ScriptureOfTheDay,
)
from apps.testimonies.models import Testimony, TestimonyStatus

from .serializers import (
    FeaturedHomeTestimonySerializer,
    HomeCurationUpdateSerializer,
    HomeSectionOrderSerializer,
    InspirationalPictureSerializer,
    ScriptureSerializer,
)


class ContentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


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
        entry.refresh_status_for_today()
        if entry.status == "published" and entry.published_at is None:
            entry.published_at = timezone.now()
            entry.save(update_fields=["status", "published_at", "updated_at"])


class AdminScriptureDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = ScriptureSerializer
    queryset = ScriptureOfTheDay.objects.all()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


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
                "thumbnail_url": row.thumbnail_url,
                "created_at": row.created_at,
                "author_name": row.author.get_full_name() or row.author.email,
            }
            for row in available_rows
        ]
        return Response(
            {
                "section_order": HomeSectionOrderSerializer(section_rows, many=True).data,
                "featured_testimonies": FeaturedHomeTestimonySerializer(featured_rows, many=True).data,
                "available_testimonies": available_payload,
            }
        )

    def put(self, request):
        serializer = HomeCurationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        section_order = serializer.validated_data["section_order"]
        featured_ids = serializer.validated_data["featured_testimony_ids"]

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
        return self.get(request)


class AdminFeaturedHomeTestimonyDeleteView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, testimony_id: int):
        FeaturedHomeTestimony.objects.filter(testimony_id=testimony_id).delete()
        return Response({"removed": testimony_id}, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([])
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
            "thumbnail_url": row.testimony.thumbnail_url,
            "publish_at": row.testimony.publish_at,
            "created_at": row.testimony.created_at,
            "view_count": row.testimony.view_count,
            "comment_count": row.testimony.comment_count,
        }
        for row in featured
        if row.testimony.status == TestimonyStatus.APPROVED
    ]

    now = timezone.now()
    current_picture = (
        InspirationalPicture.objects.filter(status=InspirationalPictureStatus.PUBLISHED)
        .filter(models.Q(publish_at__isnull=True) | models.Q(publish_at__lte=now))
        .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
        .order_by("-updated_at")
        .first()
    )
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
            "inspirational_picture": InspirationalPictureSerializer(current_picture).data if current_picture else None,
            "scripture": ScriptureSerializer(scripture).data if scripture else None,
        }
    )


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
