from rest_framework import serializers

from apps.playlists.choices import PlaylistVisibility
from apps.playlists.models import Playlist


def _validate_title(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise serializers.ValidationError("Title is required.")
    return trimmed


class PlaylistSerializer(serializers.ModelSerializer):
    """Phase 29 Slice 6 -- the owner-management shape (list/mutation
    responses). Never includes item contents; that's Slice 7's dedicated
    read path, which also has to resolve per-item availability and
    non-owner visibility rules this serializer doesn't need to know
    about."""

    item_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Playlist
        fields = ["id", "title", "visibility", "show_owner_name", "item_count", "created_at", "updated_at"]
        read_only_fields = fields


class CreatePlaylistSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=50)
    testimony_id = serializers.IntegerField(min_value=1)

    def validate_title(self, value: str) -> str:
        return _validate_title(value)


class RenamePlaylistSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=50)

    def validate_title(self, value: str) -> str:
        return _validate_title(value)


class AddPlaylistItemSerializer(serializers.Serializer):
    testimony_id = serializers.IntegerField(min_value=1)


class ReorderPlaylistItemsSerializer(serializers.Serializer):
    ordered_testimony_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)


class SetPlaylistVisibilitySerializer(serializers.Serializer):
    visibility = serializers.ChoiceField(choices=PlaylistVisibility.choices)


class SetPlaylistShowOwnerNameSerializer(serializers.Serializer):
    show_owner_name = serializers.BooleanField()


class ClonePlaylistSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")


class PlaylistItemViewSerializer(serializers.Serializer):
    """Phase 29 Slice 7 -- one rendered item. `is_available` is only ever
    present for the owner's own view (a distinct "no longer available"
    marker); a non-owner's items list never includes an unavailable one
    at all, so the field simply isn't there for them."""

    testimony_id = serializers.IntegerField()
    position = serializers.IntegerField()
    title = serializers.CharField()
    testimony_type = serializers.CharField()
    is_available = serializers.BooleanField(required=False)


class PlaylistPublicDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    is_owner = serializers.BooleanField()
    owner_name = serializers.CharField(allow_null=True)
    owner_avatar = serializers.CharField(allow_blank=True)
    item_count = serializers.IntegerField()
    items = PlaylistItemViewSerializer(many=True)


class LockedPlaylistPreviewSerializer(serializers.Serializer):
    """Phase 29 Slice 7 -- what a free/guest requester gets instead of
    the real contents, for a single playlist link. Never a bare 404 or
    an empty body -- always enough to render a locked-preview screen."""

    locked = serializers.BooleanField(default=True)
    code = serializers.CharField(default="premium_required")
    message = serializers.CharField()
    title = serializers.CharField()
    owner_name = serializers.CharField(allow_null=True)
    item_count = serializers.IntegerField()


class SharedPlaylistRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    item_count = serializers.IntegerField()


class LockedSharedPlaylistsSerializer(serializers.Serializer):
    """The same locked treatment as LockedPlaylistPreviewSerializer,
    applied to a profile's whole Playlists section instead of one
    playlist -- a count is shown, contents stay locked."""

    locked = serializers.BooleanField(default=True)
    code = serializers.CharField(default="premium_required")
    message = serializers.CharField()
    shared_playlist_count = serializers.IntegerField()


class AdminPlaylistListSerializer(serializers.ModelSerializer):
    """Phase 29 Slice 8 -- the platform-wide moderation list. Real owner
    identity always shown regardless of `show_owner_name` -- that flag
    only ever governs what a *visitor* sees, never what an admin sees."""

    owner_name = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    item_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Playlist
        fields = [
            "id",
            "title",
            "owner_name",
            "owner_email",
            "visibility",
            "item_count",
            "created_at",
        ]
        read_only_fields = fields

    def get_owner_name(self, playlist: Playlist) -> str:
        from apps.playlists.selectors import get_owner_display_name

        return get_owner_display_name(playlist.owner)


class AdminPlaylistDetailSerializer(serializers.Serializer):
    """The admin's own detail view -- complete, unfiltered ordered
    contents (Slice 8's own goal), reusing the exact same per-item
    availability marking the owner's own view gets (see
    `selectors.build_owner_playlist_view`), since an admin should see
    everything an owner would, including "no longer available" items."""

    id = serializers.IntegerField()
    title = serializers.CharField()
    owner_name = serializers.CharField()
    owner_email = serializers.EmailField()
    visibility = serializers.CharField()
    show_owner_name = serializers.BooleanField()
    item_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    items = PlaylistItemViewSerializer(many=True)


class AdminPlaylistTakedownSerializer(serializers.Serializer):
    """Phase 29 Slice 9 -- force-private and delete are different in
    kind (reversible correction vs. permanent removal), not two flags on
    one action, so this is a real choice field, not a boolean."""

    action = serializers.ChoiceField(choices=["force_private", "delete"])
    reason = serializers.CharField()

    def validate_reason(self, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError("A reason is required.")
        return trimmed
