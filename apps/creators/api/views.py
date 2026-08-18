from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.creators.exceptions import (
    CannotFollowSelfError,
    CreatorProfileAlreadyExistsError,
    CreatorProfileNotEligibleError,
    CreatorProfileNotFoundError,
    PrayerReactionAlreadyRespondedError,
    PrayerReactionNotFoundError,
    PrayerReactionNotOwnedByCreatorError,
    PrayerReactionWrongTypeError,
)
from apps.creators.models import CreatorProfile
from apps.creators.selectors import (
    follower_count,
    get_creator_analytics,
    get_creator_profile,
    is_following,
    list_prayer_reactions_for_creator,
)
from apps.creators.services.commands import (
    create_creator_profile,
    follow_creator,
    respond_to_prayer_reaction,
    unfollow_creator,
    update_creator_profile,
    verify_creator_profile,
)

from .serializers import (
    AdminCreatorProfileSerializer,
    CreatorProfileSerializer,
    PrayerReactionInboxSerializer,
    PrayerResponseCreateSerializer,
    PublicCreatorProfileSerializer,
)


class CreatorProfileMeView(APIView):
    """Phase 23 Slice 1 -- the Premium subscriber's own Ministry profile."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_creator_profile(request.user)
        if profile is None:
            return Response({"message": "No Ministry profile exists for this account."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CreatorProfileSerializer(profile).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = CreatorProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = create_creator_profile(
                user=request.user,
                display_name=serializer.validated_data["display_name"],
                bio=serializer.validated_data.get("bio", ""),
            )
        except CreatorProfileNotEligibleError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except CreatorProfileAlreadyExistsError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CreatorProfileSerializer(profile).data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        serializer = CreatorProfileSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            profile = update_creator_profile(
                user=request.user,
                display_name=serializer.validated_data.get("display_name"),
                bio=serializer.validated_data.get("bio"),
            )
        except CreatorProfileNotEligibleError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except CreatorProfileNotFoundError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response(CreatorProfileSerializer(profile).data, status=status.HTTP_200_OK)


class PublicCreatorProfileDetailView(APIView):
    """Public-facing profile (Slice 1 read + Slice 2 follow-state) -- what a
    follower sees. Works whether or not the profile is verified; verification
    never gates visibility (see Phase 23's Background note)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id: int):
        profile = CreatorProfile.objects.filter(user_id=user_id).select_related("user").first()
        if profile is None:
            return Response({"message": "This account doesn't have a Ministry profile."}, status=status.HTTP_404_NOT_FOUND)

        profile.follower_count = follower_count(creator_user_id=user_id)
        profile.is_following = is_following(follower_user_id=request.user.id, creator_user_id=user_id)
        return Response(PublicCreatorProfileSerializer(profile).data, status=status.HTTP_200_OK)


class CreatorFollowToggleView(APIView):
    """Phase 23 Slice 2. Mirrors CategoryFollowToggleView's exact
    POST/DELETE toggle shape (Phase 16 precedent)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id: int):
        try:
            follow_creator(follower=request.user, creator_user_id=user_id)
        except CannotFollowSelfError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except CreatorProfileNotFoundError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response({"message": "Following creator."}, status=status.HTTP_201_CREATED)

    def delete(self, request, user_id: int):
        unfollow_creator(follower=request.user, creator_user_id=user_id)
        return Response({"message": "Unfollowed creator."}, status=status.HTTP_200_OK)


class CreatorAnalyticsView(APIView):
    """Phase 23 Slice 3 -- the creator's own aggregated stats."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not CreatorProfile.objects.filter(user=request.user).exists():
            return Response({"message": "No Ministry profile exists for this account."}, status=status.HTTP_404_NOT_FOUND)
        return Response(get_creator_analytics(creator_user_id=request.user.id), status=status.HTTP_200_OK)


class CreatorPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PrayerInboxView(generics.ListAPIView):
    """Phase 23 Slice 4 -- the creator's own inbox of praying_for_you
    reactions, paginated per backend/AGENTS.md's collection-endpoint rule."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = PrayerReactionInboxSerializer
    pagination_class = CreatorPagination

    def get_queryset(self):
        return list_prayer_reactions_for_creator(creator_user_id=self.request.user.id)


class PrayerReactionRespondView(APIView):
    """Phase 23 Slice 4."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, reaction_id: int):
        serializer = PrayerResponseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            respond_to_prayer_reaction(
                creator=request.user,
                reaction_id=reaction_id,
                response_text=serializer.validated_data["response_text"],
            )
        except PrayerReactionNotFoundError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except CreatorProfileNotFoundError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (PrayerReactionNotOwnedByCreatorError, PrayerReactionWrongTypeError, PrayerReactionAlreadyRespondedError) as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Response sent."}, status=status.HTTP_201_CREATED)


class AdminCreatorProfileListView(generics.ListAPIView):
    """Phase 23 Slice 5 (admin)."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]
    serializer_class = AdminCreatorProfileSerializer
    pagination_class = CreatorPagination

    def get_queryset(self):
        queryset = CreatorProfile.objects.select_related("user", "verified_by").order_by("-created_at")
        is_verified_param = self.request.query_params.get("is_verified")
        if is_verified_param in {"true", "false"}:
            queryset = queryset.filter(is_verified=(is_verified_param == "true"))
        return queryset


class AdminCreatorProfileVerifyView(APIView):
    """Phase 23 Slice 5 (admin). Depends only on Slice 1 (a profile must
    exist to verify) -- independent of Slices 2-4."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsActiveAdmin]

    def post(self, request, user_id: int):
        creator_profile = CreatorProfile.objects.filter(user_id=user_id).first()
        if creator_profile is None:
            return Response({"message": "This account doesn't have a Ministry profile."}, status=status.HTTP_404_NOT_FOUND)

        is_verified = bool(request.data.get("is_verified", True))
        verify_creator_profile(creator_profile=creator_profile, admin_user=request.user, is_verified=is_verified)
        return Response(AdminCreatorProfileSerializer(creator_profile).data, status=status.HTTP_200_OK)
