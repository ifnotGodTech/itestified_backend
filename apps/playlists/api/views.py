from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.api.permissions import IsActiveAdmin
from apps.playlists import selectors
from apps.playlists.exceptions import (
    PlaylistError,
    PlaylistItemAlreadyExistsError,
    PlaylistItemLimitExceededError,
    PlaylistLimitExceededError,
    PlaylistNotFoundError,
    PlaylistPremiumRequiredError,
    PlaylistReorderMismatchError,
    TestimonyNotFoundError,
)
from apps.playlists.services import commands
from apps.subscriptions.selectors import is_user_premium
from apps.users.models import User

from .serializers import (
    AddPlaylistItemSerializer,
    AdminPlaylistDetailSerializer,
    AdminPlaylistListSerializer,
    AdminPlaylistTakedownSerializer,
    ClonePlaylistSerializer,
    CreatePlaylistSerializer,
    LockedPlaylistPreviewSerializer,
    LockedSharedPlaylistsSerializer,
    PlaylistPublicDetailSerializer,
    PlaylistSerializer,
    RenamePlaylistSerializer,
    ReorderPlaylistItemsSerializer,
    SetPlaylistShowOwnerNameSerializer,
    SetPlaylistVisibilitySerializer,
    SharedPlaylistRowSerializer,
)


def _error_response(exc: PlaylistError) -> Response:
    payload = {"message": str(exc)}
    code = getattr(exc, "code", None)
    if code:
        payload["code"] = code
    return Response(payload, status=getattr(exc, "http_status", status.HTTP_400_BAD_REQUEST))


def _not_found(message: str) -> Response:
    return Response({"message": message}, status=status.HTTP_404_NOT_FOUND)


class PlaylistCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreatePlaylistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            playlist = commands.create_playlist(owner=request.user, **serializer.validated_data)
        except (PlaylistPremiumRequiredError, PlaylistLimitExceededError) as exc:
            return _error_response(exc)
        except TestimonyNotFoundError:
            return _not_found("Testimony not found.")
        return Response(PlaylistSerializer(playlist).data, status=status.HTTP_201_CREATED)


class PlaylistMineListView(generics.ListAPIView):
    """Phase 29 Slice 1/6 -- backs the mobile "My Playlists" library
    screen: every playlist the requester owns, private and shared both."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = PlaylistSerializer
    # Unpaginated deliberately: MAX_PLAYLISTS_PER_OWNER (commands.py) caps
    # this at 50 rows, never large enough to need it -- same reasoning as
    # AdminPremiumPricingListView's own pagination_class = None.
    pagination_class = None

    def get_queryset(self):
        return selectors.list_owned_playlists(owner=self.request.user)


class PlaylistDetailView(APIView):
    """Owner-only for now (Phase 29 Slice 6) -- viewing someone else's
    playlist, with its paywall/visibility/availability rules, is Slice 7's
    separate read path, deliberately left off this "mine/" URL."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, playlist_id: int):
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        return Response(PlaylistSerializer(playlist).data)

    def delete(self, request, playlist_id: int):
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
            commands.delete_playlist(playlist=playlist, actor=request.user)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except PlaylistPremiumRequiredError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlaylistRenameView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id: int):
        serializer = RenamePlaylistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
            playlist = commands.rename_playlist(playlist=playlist, actor=request.user, **serializer.validated_data)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except PlaylistPremiumRequiredError as exc:
            return _error_response(exc)
        return Response(PlaylistSerializer(playlist).data)


class PlaylistItemListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id: int):
        serializer = AddPlaylistItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
            playlist = commands.add_item(playlist=playlist, actor=request.user, **serializer.validated_data)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except TestimonyNotFoundError:
            return _not_found("Testimony not found.")
        except (PlaylistPremiumRequiredError, PlaylistItemLimitExceededError, PlaylistItemAlreadyExistsError) as exc:
            return _error_response(exc)
        return Response(PlaylistSerializer(playlist).data, status=status.HTTP_201_CREATED)


class PlaylistItemDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, playlist_id: int, testimony_id: int):
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
            playlist = commands.remove_item(playlist=playlist, actor=request.user, testimony_id=testimony_id)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except TestimonyNotFoundError:
            return _not_found("This testimony isn't in the playlist.")
        except PlaylistPremiumRequiredError as exc:
            return _error_response(exc)
        return Response(PlaylistSerializer(playlist).data)


class PlaylistReorderView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id: int):
        serializer = ReorderPlaylistItemsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
            playlist = commands.reorder_items(playlist=playlist, actor=request.user, **serializer.validated_data)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except (PlaylistPremiumRequiredError, PlaylistReorderMismatchError) as exc:
            return _error_response(exc)
        return Response(PlaylistSerializer(playlist).data)


class PlaylistVisibilityView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id: int):
        serializer = SetPlaylistVisibilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
            playlist = commands.set_visibility(playlist=playlist, actor=request.user, **serializer.validated_data)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except PlaylistPremiumRequiredError as exc:
            return _error_response(exc)
        return Response(PlaylistSerializer(playlist).data)


class PlaylistShowOwnerNameView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id: int):
        serializer = SetPlaylistShowOwnerNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            playlist = selectors.get_owned_playlist(owner=request.user, playlist_id=playlist_id)
            playlist = commands.set_show_owner_name(
                playlist=playlist, actor=request.user, **serializer.validated_data
            )
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except PlaylistPremiumRequiredError as exc:
            return _error_response(exc)
        return Response(PlaylistSerializer(playlist).data)


class PlaylistCloneView(APIView):
    """Phase 29 Slice 4/6 -- the source playlist is deliberately not
    owner-scoped: any Premium user may clone any playlist they can
    already open by id (see choices.py's own note on private vs. shared
    being a discoverability setting, not an access-control one)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, playlist_id: int):
        serializer = ClonePlaylistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data["title"] or None
        try:
            clone = commands.clone_playlist(source_playlist_id=playlist_id, actor=request.user, title=title)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")
        except (PlaylistPremiumRequiredError, PlaylistLimitExceededError) as exc:
            return _error_response(exc)
        return Response(PlaylistSerializer(clone).data, status=status.HTTP_201_CREATED)


class PlaylistPublicDetailView(APIView):
    """Phase 29 Slice 7 -- the general-purpose read path: owner, Premium
    visitor (private or shared, doesn't matter -- see choices.py), and
    free/guest all resolve through this one bare `/playlists/<id>/` URL,
    exactly where Slice 6 deliberately left it free for this.

    Deliberately does not override `authentication_classes` -- leaving
    the project default (Session + Token) in place with only
    `permission_classes = [AllowAny]` overridden is what makes
    `request.user` resolve to the real user for a valid token and to
    AnonymousUser for a guest with no special-casing needed, the same
    pattern `HomeFeedView` uses and the same authentication-override bug
    this codebase has hit twice before (Phase 17/18) that this avoids by
    not repeating it."""

    permission_classes = [AllowAny]

    def get(self, request, playlist_id: int):
        try:
            playlist = selectors.get_playlist(playlist_id=playlist_id)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")

        user = request.user if request.user.is_authenticated else None
        is_owner = user is not None and playlist.owner_id == user.id
        show_name = playlist.show_owner_name or is_owner
        owner_name = selectors.get_owner_display_name(playlist.owner) if show_name else None

        if not is_owner and not (user is not None and is_user_premium(user)):
            payload = {
                "message": "Subscribe to Premium to view this playlist.",
                "title": playlist.title,
                "owner_name": owner_name,
                "item_count": playlist.item_count,
            }
            return Response(LockedPlaylistPreviewSerializer(payload).data, status=status.HTTP_403_FORBIDDEN)

        if is_owner:
            items = selectors.build_owner_playlist_view(playlist)
            item_count = playlist.item_count
        else:
            items = selectors.build_visitor_playlist_view(playlist)
            item_count = len(items)

        payload = {
            "id": playlist.id,
            "title": playlist.title,
            "is_owner": is_owner,
            "owner_name": owner_name,
            "owner_avatar": selectors.get_owner_avatar(playlist.owner) if show_name else "",
            "item_count": item_count,
            "items": items,
        }
        return Response(PlaylistPublicDetailSerializer(payload).data)


class UserSharedPlaylistsView(APIView):
    """Phase 29 Slice 7 -- a profile's Playlists section, viewed by
    someone who isn't its owner (the owner's own full library, private
    and shared both, is `PlaylistMineListView`, a completely different
    endpoint -- this one only ever returns shared playlists)."""

    permission_classes = [AllowAny]

    def get(self, request, user_id: int):
        target_user = User.objects.filter(id=user_id).first()
        if target_user is None:
            return _not_found("User not found.")

        user = request.user if request.user.is_authenticated else None
        if user is not None and is_user_premium(user):
            playlists = selectors.list_shared_playlists_for_user(target_user=target_user)
            return Response(SharedPlaylistRowSerializer(playlists, many=True).data)

        payload = {
            "message": "Subscribe to Premium to view this profile's playlists.",
            "shared_playlist_count": selectors.count_shared_playlists_for_user(target_user=target_user),
        }
        return Response(LockedSharedPlaylistsSerializer(payload).data, status=status.HTTP_403_FORBIDDEN)


class AdminPlaylistPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminPlaylistListView(generics.ListAPIView):
    """Phase 29 Slice 8 -- platform-wide visibility into user-generated
    playlists, which otherwise has zero admin surface despite being
    Premium-community-facing UGC."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]
    serializer_class = AdminPlaylistListSerializer
    pagination_class = AdminPlaylistPagination

    def get_queryset(self):
        return selectors.list_all_playlists_for_admin(
            search=self.request.query_params.get("q") or "",
            visibility=self.request.query_params.get("visibility") or "",
        )


class AdminPlaylistDetailView(APIView):
    """Ownership-blind by design -- an admin looking into a report needs
    the complete, unfiltered ordered contents (Slice 8's own goal), the
    same shape the owner's own manage screen gets, never the
    non-owner-filtered or locked-preview shapes the public read path
    (Slice 7) resolves to for everyone else."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def get(self, request, playlist_id: int):
        try:
            playlist = selectors.get_playlist(playlist_id=playlist_id)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")

        payload = {
            "id": playlist.id,
            "title": playlist.title,
            "owner_name": selectors.get_owner_display_name(playlist.owner),
            "owner_email": playlist.owner.email,
            "visibility": playlist.visibility,
            "show_owner_name": playlist.show_owner_name,
            "item_count": playlist.item_count,
            "created_at": playlist.created_at,
            "updated_at": playlist.updated_at,
            "items": selectors.build_owner_playlist_view(playlist),
        }
        return Response(AdminPlaylistDetailSerializer(payload).data)


class AdminPlaylistTakedownView(APIView):
    """Phase 29 Slice 9 -- force the playlist private (a quiet
    correction) or delete it outright, a reason required every time,
    never a silent takedown. The owner is notified either way, matching
    the same non-generic-error/never-silent principle used everywhere
    else in this app's moderation flows."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsActiveAdmin]

    def post(self, request, playlist_id: int):
        serializer = AdminPlaylistTakedownSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            playlist = selectors.get_playlist(playlist_id=playlist_id)
        except PlaylistNotFoundError:
            return _not_found("Playlist not found.")

        action = serializer.validated_data["action"]
        reason = serializer.validated_data["reason"]
        if action == "force_private":
            playlist = commands.admin_force_private(playlist=playlist, actor=request.user, reason=reason)
            return Response(PlaylistSerializer(playlist).data)

        commands.admin_delete_playlist(playlist=playlist, actor=request.user, reason=reason)
        return Response(status=status.HTTP_204_NO_CONTENT)
