from rest_framework import generics
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from django.utils import timezone
from django.db.models import F
from django.db.models import Count
from django.db.models.functions import Greatest
from datetime import datetime
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.testimonies.models import (
    Testimony,
    TestimonyCategory,
    TestimonyComment,
    TestimonyFavorite,
    TestimonyModerationHistory,
    TestimonyStatus,
)
from apps.authn.api.permissions import IsActiveAdmin
from apps.testimonies.services.commands import (
    approve_testimony,
    archive_testimony,
    reject_testimony,
    schedule_testimony,
)
from apps.notifications.services import notify_testimony_comment

from .serializers import (
    AdminTestimonyCategorySerializer,
    AdminTestimonyDetailSerializer,
    AdminTestimonyListSerializer,
    FavoriteSerializer,
    FavoriteTestimonySerializer,
    TestimonyCategorySerializer,
    TestimonyCommentCreateSerializer,
    TestimonyCommentSerializer,
    TestimonyCreateSerializer,
    TestimonyDetailSerializer,
    TestimonyListSerializer,
    TestimonyModerationHistorySerializer,
    TestimonyVideoCreateSerializer,
)


class TestimonyPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PublicCategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyCategorySerializer
    queryset = TestimonyCategory.objects.filter(is_active=True).order_by("name")


class PublicTestimonyListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyListSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        queryset = Testimony.objects.select_related("author", "author__profile", "category").filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )
        category_slug = (self.request.query_params.get("category") or "").strip()
        search_text = (self.request.query_params.get("search") or "").strip()
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        if search_text:
            queryset = queryset.filter(title__icontains=search_text)
        return queryset


class PublicTestimonyDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyDetailSerializer

    def get_queryset(self):
        return Testimony.objects.select_related("author", "author__profile", "category").filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )


class PublicTestimonyViewIncrementView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, testimony_id: int):
        updated = Testimony.objects.filter(
            id=testimony_id,
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        ).update(view_count=F("view_count") + 1)
        if updated == 0:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        row = Testimony.objects.filter(id=testimony_id).values("id", "view_count").first()
        return Response(row, status=status.HTTP_200_OK)


class AuthenticatedWrittenTestimonyCreateView(generics.CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyCreateSerializer


class AuthenticatedVideoTestimonyCreateView(generics.CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyVideoCreateSerializer


class AuthenticatedMyTestimonyListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyDetailSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        return Testimony.objects.select_related("author", "author__profile", "category").filter(
            author=self.request.user
        )


class FavoriteListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = FavoriteSerializer
    pagination_class = None

    def get_queryset(self):
        return TestimonyFavorite.objects.filter(user=self.request.user).order_by("-created_at")


class FavoriteTestimonyListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = FavoriteTestimonySerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        return Testimony.objects.select_related("author", "author__profile", "category").filter(
            favorited_by__user=self.request.user,
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )


class FavoriteToggleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(
            id=testimony_id,
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        ).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        TestimonyFavorite.objects.get_or_create(user=request.user, testimony=testimony)
        return Response({"message": "Added to favorites."}, status=status.HTTP_201_CREATED)

    def delete(self, request, testimony_id: int):
        TestimonyFavorite.objects.filter(user=request.user, testimony_id=testimony_id).delete()
        return Response({"message": "Removed from favorites."}, status=status.HTTP_200_OK)


class TestimonyCommentListCreateView(generics.ListCreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = TestimonyPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [permission() for permission in self.permission_classes]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TestimonyCommentCreateSerializer
        return TestimonyCommentSerializer

    def get_queryset(self):
        testimony_id = self.kwargs["testimony_id"]
        return TestimonyComment.objects.select_related("author", "author__profile", "testimony").filter(
            testimony_id=testimony_id,
            testimony__status=TestimonyStatus.APPROVED,
            testimony__category__is_active=True,
            parent_comment__isnull=True,
        )

    def perform_create(self, serializer):
        testimony_id = self.kwargs["testimony_id"]
        testimony = Testimony.objects.filter(
            id=testimony_id,
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        ).first()
        if testimony is None:
            raise ValueError("Testimony not found.")
        parent_comment_id = serializer.validated_data.get("parent_comment_id")
        parent_comment = None
        if parent_comment_id is not None:
            parent_comment = TestimonyComment.objects.filter(
                id=parent_comment_id,
                testimony_id=testimony.id,
            ).first()
            if parent_comment is None:
                raise ValueError("Parent comment not found.")
            if parent_comment.parent_comment_id is not None:
                raise ValueError("Only one reply level is allowed.")

        comment = serializer.save(
            author=self.request.user,
            testimony=testimony,
            parent_comment=parent_comment,
        )
        Testimony.objects.filter(id=testimony.id).update(comment_count=F("comment_count") + 1)
        if testimony.author_id != self.request.user.id:
            notify_testimony_comment(
                recipient=testimony.author,
                actor=self.request.user,
                testimony_title=testimony.title,
            )
        return comment

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except ValueError as exc:
            message = str(exc)
            if message in {"Parent comment not found.", "Testimony not found."}:
                return Response({"message": message}, status=status.HTTP_404_NOT_FOUND)
            return Response({"message": message}, status=status.HTTP_400_BAD_REQUEST)


class TestimonyCommentDeleteView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, comment_id: int):
        comment = TestimonyComment.objects.select_related("testimony").filter(id=comment_id).first()
        if comment is None:
            return Response({"message": "Comment not found."}, status=status.HTTP_404_NOT_FOUND)
        if comment.author_id != request.user.id:
            return Response({"message": "You can only delete your own comment."}, status=status.HTTP_403_FORBIDDEN)
        testimony_id = comment.testimony_id
        comment.delete()
        Testimony.objects.filter(id=testimony_id).update(comment_count=Greatest(F("comment_count") - 1, 0))
        return Response({"message": "Comment deleted."}, status=status.HTTP_200_OK)


class AdminCategoryListCreateView(generics.ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyCategorySerializer
    queryset = TestimonyCategory.objects.all().order_by("name")
    pagination_class = None


class AdminCategoryDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyCategorySerializer
    queryset = TestimonyCategory.objects.all()


class AdminCategoryActivationView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, category_id: int):
        category = TestimonyCategory.objects.filter(id=category_id).first()
        if category is None:
            return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AdminTestimonyCategorySerializer(category, data={"is_active": True}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, category_id: int):
        category = TestimonyCategory.objects.filter(id=category_id).first()
        if category is None:
            return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AdminTestimonyCategorySerializer(category, data={"is_active": False}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminTestimonyListView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyListSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        queryset = (
            Testimony.objects.select_related("author", "author__profile", "category")
            .annotate(comment_count_total=Count("comments"))
            .all()
        )
        status_value = (self.request.query_params.get("status") or "").strip()
        category_slug = (self.request.query_params.get("category") or "").strip()
        search_text = (self.request.query_params.get("search") or "").strip()
        if status_value:
            queryset = queryset.filter(status=status_value)
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        if search_text:
            queryset = queryset.filter(title__icontains=search_text)
        if status_value == TestimonyStatus.PENDING_REVIEW:
            return queryset.order_by("created_at")
        return queryset


class AdminTestimonyDetailView(generics.RetrieveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyDetailSerializer

    def get_queryset(self):
        return (
            Testimony.objects.select_related("author", "author__profile", "category")
            .annotate(comment_count_total=Count("comments"))
            .all()
        )


class AdminPendingModerationQueueView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyListSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        return (
            Testimony.objects.select_related("author", "author__profile", "category")
            .annotate(comment_count_total=Count("comments"))
            .filter(status=TestimonyStatus.PENDING_REVIEW)
            .order_by("created_at")
        )


class AdminApproveTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if testimony.status != TestimonyStatus.PENDING_REVIEW:
            return Response(
                {"message": "Only pending testimonies can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        approve_testimony(testimony=testimony, actor=request.user)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminRejectTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if testimony.status != TestimonyStatus.PENDING_REVIEW:
            return Response(
                {"message": "Only pending testimonies can be rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"message": "Rejection reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        reject_testimony(testimony=testimony, actor=request.user, reason=reason)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminScheduleTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if testimony.status != TestimonyStatus.PENDING_REVIEW:
            return Response(
                {"message": "Only pending testimonies can be scheduled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_publish_at = str(request.data.get("publish_at", "")).strip()
        if not raw_publish_at:
            return Response({"message": "publish_at is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            publish_at = datetime.fromisoformat(raw_publish_at.replace("Z", "+00:00"))
        except ValueError:
            return Response({"message": "publish_at must be a valid ISO datetime."}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(publish_at):
            publish_at = timezone.make_aware(publish_at, timezone.get_current_timezone())
        if publish_at <= timezone.now():
            return Response({"message": "publish_at must be in the future."}, status=status.HTTP_400_BAD_REQUEST)
        schedule_testimony(testimony=testimony, actor=request.user, publish_at=publish_at)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminArchiveTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if testimony.status not in (TestimonyStatus.APPROVED, TestimonyStatus.SCHEDULED):
            return Response(
                {"message": "Only approved or scheduled testimonies can be archived."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reason = str(request.data.get("reason", "")).strip()
        archive_testimony(testimony=testimony, actor=request.user, reason=reason)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminTestimonyModerationHistoryView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = TestimonyModerationHistorySerializer
    pagination_class = None

    def get_queryset(self):
        return TestimonyModerationHistory.objects.select_related("actor").filter(
            testimony_id=self.kwargs["testimony_id"]
        )
