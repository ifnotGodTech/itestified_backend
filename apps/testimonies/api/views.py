from rest_framework import generics
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from django.utils.dateparse import parse_date
from django.db.models import F
from django.db.models import Count
from django.db.models import Q
from django.db.models.functions import Greatest
from datetime import datetime
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.subscriptions.selectors import is_user_premium
from apps.testimonies.exceptions import (
    AIJobNotRetryableError,
    AudioUploadContractError,
    TestimonyTransitionNotAllowedError,
    TestimonyTranslationNotReadyError,
)
from apps.testimonies.models import (
    Testimony,
    AudioUploadPolicy,
    TestimonyCategory,
    TestimonyComment,
    TestimonyFavorite,
    TestimonyModerationHistory,
    TestimonyReaction,
    TestimonyStatus,
    TestimonyType,
    TestimonyWatch,
    TranscriptionJob,
    TranscriptionJobStatus,
    TranslationJob,
    TranslationJobStatus,
    UserFollowedCategory,
)
from apps.authn.api.permissions import IsActiveAdmin
from apps.testimonies.services.queries import home_feed_page
from apps.testimonies.validators import parse_future_publish_at
from apps.testimonies.services.commands import (
    approve_testimony,
    archive_testimony,
    issue_audio_upload_intent,
    enqueue_transcription_job,
    reject_testimony,
    remove_testimony_reaction,
    request_testimony_translation,
    retry_transcription_job,
    retry_translation_job,
    schedule_testimony,
    set_testimony_reaction,
    upload_now_video_testimony,
)
from apps.notifications.services import (
    notify_new_video_testimony_published,
    notify_testimony_comment,
    notify_testimony_submitted_to_admins,
)

from .serializers import (
    AdminTestimonyCategorySerializer,
    AdminTestimonyDetailSerializer,
    AdminTestimonyListSerializer,
    AdminTranscriptionJobSerializer,
    AdminTranslationJobSerializer,
    FavoriteSerializer,
    FavoriteTestimonySerializer,
    TestimonyCategorySerializer,
    TestimonyCommentCreateSerializer,
    TestimonyCommentSerializer,
    TestimonyCreateSerializer,
    TestimonyDetailSerializer,
    TestimonyListSerializer,
    TestimonyReactionInputSerializer,
    TestimonyModerationHistorySerializer,
    RejectedTestimonyResubmitSerializer,
    AdminVideoTestimonyUploadSerializer,
    AdminVideoTestimonyEditSerializer,
    AdminVideoTestimonyCreateFromUrlSerializer,
    AdminTestimonyPullQuoteSerializer,
    PublicTestimonyShareSerializer,
    TestimonyTranslationRequestSerializer,
    TestimonyTranslationSerializer,
    AudioTestimonyCreateSerializer,
    AudioUploadPolicySerializer,
    AdminAudioUploadPolicySerializer,
    normalize_video_source,
)
from apps.testimonies.services.media_uploads import CloudinaryUploadError, create_direct_upload_signature


class TestimonyPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_admin_filter_date(value: str):
    if not value:
        return None
    parsed = parse_date(value)
    if parsed is not None:
        return parsed
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


class PublicCategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyCategorySerializer
    queryset = TestimonyCategory.objects.filter(is_active=True).order_by("name")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        context["followed_category_ids"] = (
            set(user.followed_categories.values_list("category_id", flat=True))
            if user.is_authenticated
            else set()
        )
        return context


class CategoryFollowToggleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, category_id: int):
        category = TestimonyCategory.objects.filter(id=category_id, is_active=True).first()
        if category is None:
            return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
        UserFollowedCategory.objects.get_or_create(user=request.user, category=category)
        return Response({"message": "Following category."}, status=status.HTTP_201_CREATED)

    def delete(self, request, category_id: int):
        UserFollowedCategory.objects.filter(user=request.user, category_id=category_id).delete()
        return Response({"message": "Unfollowed category."}, status=status.HTTP_200_OK)


class ForYouTestimonyListView(generics.ListAPIView):
    """Personalized feed: approved testimonies from categories the user
    follows, blended with categories they've favorited or reacted to (no
    cold-start problem for existing users -- see Phase 16 background). A
    user with no signal at all gets an ordinary empty paginated result, not
    an error, so the mobile client knows to hide the "For You" section
    rather than treat it as a failure."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyListSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        user = self.request.user
        category_ids = (
            set(user.followed_categories.values_list("category_id", flat=True))
            | set(
                TestimonyFavorite.objects.filter(user=user).values_list(
                    "testimony__category_id", flat=True
                )
            )
            | set(
                TestimonyReaction.objects.filter(user=user).values_list(
                    "testimony__category_id", flat=True
                )
            )
        )
        if not category_ids:
            return Testimony.objects.none()
        return (
            Testimony.objects.select_related("author", "author__profile", "author__creator_profile", "category")
            .filter(
                status=TestimonyStatus.APPROVED,
                category__is_active=True,
                category_id__in=category_ids,
            )
            .order_by("-created_at", "-id")
        )


class PublicTestimonyListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyListSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        queryset = Testimony.objects.select_related(
            "author", "author__profile", "author__creator_profile", "category"
        ).filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )
        category_slug = (self.request.query_params.get("category") or "").strip()
        search_text = (self.request.query_params.get("search") or "").strip()
        ministry_only = (self.request.query_params.get("ministry_only") or "").strip().lower() == "true"
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        if search_text:
            queryset = queryset.filter(title__icontains=search_text)
        if ministry_only:
            # Phase 23 Slice 11 -- lets a user discover Ministries through
            # their content directly, rather than only stumbling into one
            # via a random testimony. Not gated on is_verified: per this
            # phase's own Background note, verification only decides
            # whether the badge renders, never who's discoverable.
            queryset = queryset.filter(author__creator_profile__isnull=False)
        return queryset


class HomeFeedView(APIView):
    """The immersive Home feed (Phase 20 Slice 3) -- one continuous, ranked
    stream of approved testimonies (video and text mixed together) that
    never dead-ends. Deliberately left un-authenticated (default auth
    classes, AllowAny) rather than overridden, so `request.user` is the
    real user for a valid token and AnonymousUser for a guest without
    needing any special-casing -- the same authentication-override bug
    this codebase has hit twice before (Phase 17/18) doesn't apply here."""

    permission_classes = [AllowAny]

    # Mobile-minted, so cap the length rather than trust it -- only ever
    # used as a random.Random() seed, never interpolated into a query or
    # displayed, but an unbounded client-supplied string is still not
    # something to pass through unchecked.
    MAX_SEED_LENGTH = 64

    def get(self, request):
        try:
            page = int(request.query_params.get("page", "1"))
        except (TypeError, ValueError):
            page = 1
        page = max(page, 1)

        seed = request.query_params.get("seed") or None
        if seed is not None:
            seed = seed[: self.MAX_SEED_LENGTH]

        page_data = home_feed_page(
            user=request.user,
            page=page,
            page_size=TestimonyPagination.page_size,
            seed=seed,
        )
        return Response(
            {
                "results": TestimonyListSerializer(page_data["results"], many=True).data,
                "next_page": page_data["next_page"],
            }
        )


class PublicTestimonyDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = TestimonyDetailSerializer

    def get_queryset(self):
        return Testimony.objects.select_related(
            "author", "author__profile", "author__creator_profile", "category", "transcription_job"
        ).filter(
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        )


class PublicTestimonyShareView(generics.RetrieveAPIView):
    """Phase 11 Slice 1's public share page endpoint -- deliberately its own
    view rather than reusing PublicTestimonyDetailView above. That view's
    serializer carries an author_name field that falls back to the author's
    email when no profile full_name is set; fine for mobile's own in-app
    guest testimony viewing, not safe for a page search engines crawl and
    WhatsApp/Facebook/Twitter cache link previews from. select_related
    doesn't include "author"/"author__profile" here since
    PublicTestimonyShareSerializer never reads either."""

    permission_classes = [AllowAny]
    serializer_class = PublicTestimonyShareSerializer

    def get_queryset(self):
        return Testimony.objects.select_related("category").filter(
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
        if request.user.is_authenticated:
            # get_or_create, not create -- once per distinct testimony no
            # matter how many times this user replays/reopens it (Phase 18
            # Slice 1's own definition of "Watched").
            TestimonyWatch.objects.get_or_create(user=request.user, testimony_id=testimony_id)
        row = Testimony.objects.filter(id=testimony_id).values("id", "view_count").first()
        return Response(row, status=status.HTTP_200_OK)


class TestimonyTranslationView(APIView):
    """Phase 22 Slice 2. POST is deliberately idempotent and safe to call
    repeatedly for the same (testimony, language) -- mobile uses this both
    to *request* a translation the first time and to *poll* for its result
    afterward, rather than needing a separate GET endpoint."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.select_related("transcription_job").filter(
            id=testimony_id,
            status=TestimonyStatus.APPROVED,
        ).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if not is_user_premium(request.user):
            return Response(
                {"message": "Translations are a Premium feature."},
                status=status.HTTP_403_FORBIDDEN,
            )
        request_serializer = TestimonyTranslationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        language = request_serializer.validated_data["language"].strip().lower()
        try:
            job = request_testimony_translation(testimony=testimony, language=language)
        except TestimonyTranslationNotReadyError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(TestimonyTranslationSerializer(job).data, status=status.HTTP_200_OK)


class AuthenticatedWrittenTestimonyCreateView(generics.CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyCreateSerializer


class AudioUploadPolicyView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        policy, _ = AudioUploadPolicy.objects.get_or_create(pk=1)
        return Response(AudioUploadPolicySerializer(policy).data)


class AuthenticatedAudioUploadSignatureView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            intent, signature = issue_audio_upload_intent(user=request.user)
        except AudioUploadContractError as exc:
            return Response(
                {"code": exc.code, "message": str(exc)},
                status=exc.http_status,
            )
        except CloudinaryUploadError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "cloud_name": signature.cloud_name, "api_key": signature.api_key,
            "timestamp": signature.timestamp, "folder": signature.folder,
            "public_id": signature.public_id,
            "signature": signature.signature,
            "resource_type": "video",
            "upload_resource_type": "video",
            "upload_intent_id": str(intent.id),
            "expires_at": intent.expires_at,
            "policy": {
                "max_file_size_bytes": intent.max_file_size_bytes,
                "max_duration_ms": intent.max_duration_ms,
                "allowed_content_types": intent.allowed_content_types,
            },
        })


class AuthenticatedAudioTestimonyCreateView(generics.CreateAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = AudioTestimonyCreateSerializer

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except AudioUploadContractError as exc:
            return Response(
                {"code": exc.code, "message": str(exc)},
                status=exc.http_status,
            )


class AdminAudioUploadPolicyView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminAudioUploadPolicySerializer

    def get_object(self):
        policy, _ = AudioUploadPolicy.objects.select_related(
            "updated_by", "updated_by__profile"
        ).get_or_create(pk=1)
        return policy

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class AuthenticatedMyTestimonyListView(generics.ListAPIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TestimonyDetailSerializer
    pagination_class = TestimonyPagination

    def get_queryset(self):
        return Testimony.objects.select_related(
            "author", "author__profile", "author__creator_profile", "category", "transcription_job"
        ).filter(author=self.request.user).order_by("-created_at", "-id")


class AuthenticatedRejectedTestimonyResubmitView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id, author=request.user).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if testimony.testimony_type != TestimonyType.WRITTEN:
            return Response({"message": "Only written testimonies can be edited here."}, status=status.HTTP_400_BAD_REQUEST)
        if testimony.status != TestimonyStatus.REJECTED:
            return Response(
                {"message": "Only rejected testimonies can be resubmitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RejectedTestimonyResubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        testimony.title = serializer.validated_data["title"]
        testimony.body = serializer.validated_data["body"]
        testimony.category = serializer.validated_data["category"]
        testimony.status = TestimonyStatus.PENDING_REVIEW
        testimony.rejection_reason = ""
        testimony.save(update_fields=["title", "body", "category", "status", "rejection_reason", "updated_at"])

        notify_testimony_submitted_to_admins(
            testimony_title=testimony.title,
            testimony_type=testimony.testimony_type,
            actor=request.user,
            testimony_id=testimony.id,
        )

        return Response(TestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AuthenticatedMyTestimonyDeleteView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id, author=request.user).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if testimony.status not in (TestimonyStatus.PENDING_REVIEW, TestimonyStatus.REJECTED):
            return Response(
                {"message": "Only pending or rejected testimonies can be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        testimony.delete()
        return Response({"message": "Testimony deleted."}, status=status.HTTP_200_OK)


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
        return Testimony.objects.select_related(
            "author", "author__profile", "author__creator_profile", "category"
        ).filter(
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


def _reaction_state(testimony: Testimony, user) -> dict:
    my_reaction = (
        TestimonyReaction.objects.filter(user=user, testimony=testimony)
        .values_list("reaction_type", flat=True)
        .first()
    )
    return {
        "reaction_counts": {
            "praying_for_you": testimony.praying_for_you_count,
            "amen": testimony.amen_count,
            "gives_me_hope": testimony.gives_me_hope_count,
        },
        "my_reaction": my_reaction,
    }


class TestimonyReactionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, testimony_id: int):
        serializer = TestimonyReactionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        testimony = Testimony.objects.filter(
            id=testimony_id,
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        ).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        testimony = set_testimony_reaction(
            testimony=testimony,
            user=request.user,
            reaction_type=serializer.validated_data["reaction_type"],
        )
        return Response(_reaction_state(testimony, request.user), status=status.HTTP_200_OK)

    def delete(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(
            id=testimony_id,
            status=TestimonyStatus.APPROVED,
            category__is_active=True,
        ).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        testimony = remove_testimony_reaction(testimony=testimony, user=request.user)
        return Response(_reaction_state(testimony, request.user), status=status.HTTP_200_OK)


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
        deleted_comment_count = TestimonyComment.objects.filter(
            Q(id=comment.id) | Q(parent_comment_id=comment.id)
        ).count()
        comment.delete()
        Testimony.objects.filter(id=testimony_id).update(
            comment_count=Greatest(F("comment_count") - deleted_comment_count, 0)
        )
        return Response({"message": "Comment deleted."}, status=status.HTTP_200_OK)


class AdminCategoryListCreateView(generics.ListCreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyCategorySerializer
    # One annotated query for the whole list rather than one .count() per
    # category row (see AdminTestimonyCategorySerializer.get_follower_count).
    queryset = (
        TestimonyCategory.objects.annotate(follower_count=Count("followed_by", distinct=True))
        .order_by("name")
    )
    pagination_class = None


class AdminCategoryDetailView(generics.RetrieveUpdateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyCategorySerializer
    queryset = TestimonyCategory.objects.annotate(
        follower_count=Count("followed_by", distinct=True)
    )


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
            Testimony.objects.select_related("author", "author__profile", "category", "transcription_job")
            .annotate(comment_count_total=Count("comments"))
            .all()
        )
        status_value = (self.request.query_params.get("status") or "").strip()
        category_slug = (self.request.query_params.get("category") or "").strip()
        search_text = (self.request.query_params.get("search") or "").strip()
        testimony_type = (self.request.query_params.get("testimony_type") or "").strip()
        date_from = _parse_admin_filter_date((self.request.query_params.get("date_from") or "").strip())
        date_to = _parse_admin_filter_date((self.request.query_params.get("date_to") or "").strip())
        source_text = normalize_video_source(self.request.query_params.get("source") or "")
        if status_value:
            queryset = queryset.filter(status=status_value)
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        if testimony_type in TestimonyType.values:
            queryset = queryset.filter(testimony_type=testimony_type)
        if search_text:
            queryset = queryset.filter(title__icontains=search_text)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        if source_text:
            queryset = queryset.filter(body__icontains=f"Source: {source_text}")
        if status_value == TestimonyStatus.PENDING_REVIEW:
            return queryset.order_by("created_at", "id")
        return queryset.order_by("-created_at", "-id")


class AdminTestimonyDetailView(generics.RetrieveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTestimonyDetailSerializer

    def get_queryset(self):
        return (
            Testimony.objects.select_related("author", "author__profile", "category", "transcription_job")
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
            Testimony.objects.select_related("author", "author__profile", "category", "transcription_job")
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
        try:
            approve_testimony(testimony=testimony, actor=request.user)
        except TestimonyTransitionNotAllowedError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminRejectTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"message": "Rejection reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            reject_testimony(testimony=testimony, actor=request.user, reason=reason)
        except TestimonyTransitionNotAllowedError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminScheduleTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            publish_at = parse_future_publish_at(request.data.get("publish_at", ""))
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            schedule_testimony(testimony=testimony, actor=request.user, publish_at=publish_at)
        except TestimonyTransitionNotAllowedError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminArchiveTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        reason = str(request.data.get("reason", "")).strip()
        try:
            archive_testimony(testimony=testimony, actor=request.user, reason=reason)
        except TestimonyTransitionNotAllowedError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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


class AdminVideoTestimonyUploadView(generics.CreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = AdminVideoTestimonyUploadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        testimony = serializer.save()
        enqueue_transcription_job(testimony=testimony)
        if testimony.status == TestimonyStatus.APPROVED:
            notify_new_video_testimony_published(testimony=testimony, actor=request.user)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_201_CREATED)


class AdminVideoTestimonyUploadSignatureView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request):
        resource_type = str(request.data.get("resource_type") or "video").strip().lower()
        try:
            upload_signature = create_direct_upload_signature(resource_type=resource_type)
        except CloudinaryUploadError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "cloud_name": upload_signature.cloud_name,
                "api_key": upload_signature.api_key,
                "timestamp": upload_signature.timestamp,
                "folder": upload_signature.folder,
                "signature": upload_signature.signature,
                "resource_type": resource_type,
            },
            status=status.HTTP_200_OK,
        )


class AdminVideoTestimonyCreateFromUrlView(generics.CreateAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminVideoTestimonyCreateFromUrlSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        testimony = serializer.save()
        enqueue_transcription_job(testimony=testimony)
        if testimony.status == TestimonyStatus.APPROVED:
            notify_new_video_testimony_published(testimony=testimony, actor=request.user)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_201_CREATED)


class AdminDeleteTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def delete(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        testimony.delete()
        return Response({"message": "Testimony deleted."}, status=status.HTTP_200_OK)


class AdminUpdateVideoTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def patch(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        if testimony.testimony_type != TestimonyType.VIDEO:
            return Response({"message": "Only video testimonies can be edited here."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AdminVideoTestimonyEditSerializer(testimony, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminTestimonyPullQuoteView(APIView):
    """Phase 19 Slice 2: lets a moderator set or clear a testimony's
    pull-quote any time, independent of the approve/reject decision itself
    -- no automatic sentence-extraction fallback, see the phase
    background."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def patch(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AdminTestimonyPullQuoteSerializer(testimony, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AdminUploadNowVideoTestimonyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, testimony_id: int):
        testimony = Testimony.objects.filter(id=testimony_id).first()
        if testimony is None:
            return Response({"message": "Testimony not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            upload_now_video_testimony(testimony=testimony, actor=request.user)
        except TestimonyTransitionNotAllowedError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        notify_new_video_testimony_published(testimony=testimony, actor=request.user)
        return Response(AdminTestimonyDetailSerializer(testimony).data, status=status.HTTP_200_OK)


class AIJobPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminTranscriptionJobListView(generics.ListAPIView):
    """Phase 22 Slice 5. Defaults to no status filter (admin sees the
    whole queue) but supports ?status=failed so the dashboard can surface
    "stuck" jobs specifically, per this slice's own requirement that a
    failure is never silently stuck in processing."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTranscriptionJobSerializer
    pagination_class = AIJobPagination

    def get_queryset(self):
        queryset = TranscriptionJob.objects.select_related("testimony")
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        if status_filter in TranscriptionJobStatus.values:
            queryset = queryset.filter(status=status_filter)
        return queryset.order_by("-updated_at")


class AdminTranscriptionJobRetryView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, job_id: int):
        try:
            job = retry_transcription_job(job_id=job_id)
        except TranscriptionJob.DoesNotExist:
            return Response({"message": "Transcription job not found."}, status=status.HTTP_404_NOT_FOUND)
        except AIJobNotRetryableError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AdminTranscriptionJobSerializer(job).data, status=status.HTTP_200_OK)


class AdminTranslationJobListView(generics.ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminTranslationJobSerializer
    pagination_class = AIJobPagination

    def get_queryset(self):
        queryset = TranslationJob.objects.select_related("testimony")
        status_filter = (self.request.query_params.get("status") or "").strip().lower()
        if status_filter in TranslationJobStatus.values:
            queryset = queryset.filter(status=status_filter)
        return queryset.order_by("-updated_at")


class AdminTranslationJobRetryView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, job_id: int):
        try:
            job = retry_translation_job(job_id=job_id)
        except TranslationJob.DoesNotExist:
            return Response({"message": "Translation job not found."}, status=status.HTTP_404_NOT_FOUND)
        except AIJobNotRetryableError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AdminTranslationJobSerializer(job).data, status=status.HTTP_200_OK)
