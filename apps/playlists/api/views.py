from rest_framework import generics, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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

from .serializers import (
    AddPlaylistItemSerializer,
    ClonePlaylistSerializer,
    CreatePlaylistSerializer,
    PlaylistSerializer,
    RenamePlaylistSerializer,
    ReorderPlaylistItemsSerializer,
    SetPlaylistShowOwnerNameSerializer,
    SetPlaylistVisibilitySerializer,
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
