from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.playlists.models import Playlist, PlaylistItem
from apps.playlists.services import commands
from apps.playlists.tests.factories import approved_testimony, category, free_user, premium_user


def _token_header(user) -> dict:
    token, _ = Token.objects.get_or_create(user=user)
    return {"HTTP_AUTHORIZATION": f"Token {token.key}"}


class PlaylistCreateApiTests(TestCase):
    def test_requires_authentication(self):
        response = self.client.post(reverse("playlist-create"), {}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_free_user_gets_stable_premium_required_response(self):
        user = free_user()
        testimony = approved_testimony()
        response = self.client.post(
            reverse("playlist-create"),
            {"title": "My List", "testimony_id": testimony.id},
            content_type="application/json",
            **_token_header(user),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "premium_required")

    def test_premium_user_creates_a_playlist(self):
        user = premium_user()
        testimony = approved_testimony()
        response = self.client.post(
            reverse("playlist-create"),
            {"title": "Sunday Favorites", "testimony_id": testimony.id},
            content_type="application/json",
            **_token_header(user),
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["title"], "Sunday Favorites")
        self.assertEqual(body["visibility"], "private")
        self.assertEqual(body["item_count"], 1)

    def test_blank_title_is_rejected(self):
        user = premium_user()
        testimony = approved_testimony()
        response = self.client.post(
            reverse("playlist-create"),
            {"title": "   ", "testimony_id": testimony.id},
            content_type="application/json",
            **_token_header(user),
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_testimony_returns_404(self):
        user = premium_user()
        response = self.client.post(
            reverse("playlist-create"),
            {"title": "My List", "testimony_id": 999999},
            content_type="application/json",
            **_token_header(user),
        )
        self.assertEqual(response.status_code, 404)


class PlaylistMineListApiTests(TestCase):
    def test_lists_only_the_requesters_own_playlists(self):
        owner = premium_user(email="owner@example.com")
        someone_else = premium_user(email="someone@example.com")
        testimony = approved_testimony()
        commands.create_playlist(owner=owner, title="Mine", testimony_id=testimony.id)
        commands.create_playlist(owner=someone_else, title="Not Mine", testimony_id=testimony.id)

        response = self.client.get(reverse("playlist-mine-list"), **_token_header(owner))

        self.assertEqual(response.status_code, 200)
        titles = [row["title"] for row in response.json()]
        self.assertEqual(titles, ["Mine"])


class PlaylistDetailApiTests(TestCase):
    def test_owner_can_view_and_a_non_owner_gets_404(self):
        owner = premium_user(email="owner@example.com")
        other = premium_user(email="other@example.com")
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="Mine", testimony_id=testimony.id)

        own_response = self.client.get(
            reverse("playlist-mine-detail", kwargs={"playlist_id": playlist.id}), **_token_header(owner)
        )
        self.assertEqual(own_response.status_code, 200)

        other_response = self.client.get(
            reverse("playlist-mine-detail", kwargs={"playlist_id": playlist.id}), **_token_header(other)
        )
        self.assertEqual(other_response.status_code, 404)

    def test_owner_can_delete_their_playlist(self):
        owner = premium_user()
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="Mine", testimony_id=testimony.id)

        response = self.client.delete(
            reverse("playlist-mine-detail", kwargs={"playlist_id": playlist.id}), **_token_header(owner)
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Playlist.objects.filter(id=playlist.id).exists())


class PlaylistRenameApiTests(TestCase):
    def test_renames_the_playlist(self):
        owner = premium_user()
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="Old", testimony_id=testimony.id)

        response = self.client.post(
            reverse("playlist-rename", kwargs={"playlist_id": playlist.id}),
            {"title": "New"},
            content_type="application/json",
            **_token_header(owner),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "New")


class PlaylistItemApiTests(TestCase):
    def test_add_and_remove_item(self):
        owner = premium_user()
        testimony_category = category()
        testimony_a = approved_testimony(category_obj=testimony_category, title="A")
        testimony_b = approved_testimony(category_obj=testimony_category, title="B")
        playlist = commands.create_playlist(owner=owner, title="List", testimony_id=testimony_a.id)

        add_response = self.client.post(
            reverse("playlist-item-add", kwargs={"playlist_id": playlist.id}),
            {"testimony_id": testimony_b.id},
            content_type="application/json",
            **_token_header(owner),
        )
        self.assertEqual(add_response.status_code, 201)
        self.assertEqual(add_response.json()["item_count"], 2)

        remove_response = self.client.delete(
            reverse("playlist-item-remove", kwargs={"playlist_id": playlist.id, "testimony_id": testimony_a.id}),
            **_token_header(owner),
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertEqual(remove_response.json()["item_count"], 1)

    def test_adding_a_duplicate_returns_400_with_a_stable_code(self):
        owner = premium_user()
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="List", testimony_id=testimony.id)

        response = self.client.post(
            reverse("playlist-item-add", kwargs={"playlist_id": playlist.id}),
            {"testimony_id": testimony.id},
            content_type="application/json",
            **_token_header(owner),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "playlist_item_already_exists")


class PlaylistReorderApiTests(TestCase):
    def test_reorders_items(self):
        owner = premium_user()
        testimony_category = category()
        testimony_a = approved_testimony(category_obj=testimony_category, title="A")
        testimony_b = approved_testimony(category_obj=testimony_category, title="B")
        playlist = commands.create_playlist(owner=owner, title="List", testimony_id=testimony_a.id)
        commands.add_item(playlist=playlist, actor=owner, testimony_id=testimony_b.id)

        response = self.client.post(
            reverse("playlist-reorder", kwargs={"playlist_id": playlist.id}),
            {"ordered_testimony_ids": [testimony_b.id, testimony_a.id]},
            content_type="application/json",
            **_token_header(owner),
        )
        self.assertEqual(response.status_code, 200)
        items = list(PlaylistItem.objects.filter(playlist=playlist).order_by("position"))
        self.assertEqual([item.testimony_id for item in items], [testimony_b.id, testimony_a.id])

    def test_mismatched_reorder_returns_400_with_a_stable_code(self):
        owner = premium_user()
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="List", testimony_id=testimony.id)

        response = self.client.post(
            reverse("playlist-reorder", kwargs={"playlist_id": playlist.id}),
            {"ordered_testimony_ids": [999999]},
            content_type="application/json",
            **_token_header(owner),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "playlist_reorder_mismatch")


class PlaylistVisibilityAndNameApiTests(TestCase):
    def test_set_visibility(self):
        owner = premium_user()
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="List", testimony_id=testimony.id)

        response = self.client.post(
            reverse("playlist-visibility", kwargs={"playlist_id": playlist.id}),
            {"visibility": "shared"},
            content_type="application/json",
            **_token_header(owner),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["visibility"], "shared")

    def test_set_show_owner_name(self):
        owner = premium_user()
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="List", testimony_id=testimony.id)

        response = self.client.post(
            reverse("playlist-show-owner-name", kwargs={"playlist_id": playlist.id}),
            {"show_owner_name": False},
            content_type="application/json",
            **_token_header(owner),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["show_owner_name"])


class PlaylistCloneApiTests(TestCase):
    def test_a_different_premium_user_can_clone_by_id(self):
        owner = premium_user(email="owner@example.com")
        cloner = premium_user(email="cloner@example.com")
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="Original", testimony_id=testimony.id)

        response = self.client.post(
            reverse("playlist-clone", kwargs={"playlist_id": playlist.id}),
            {},
            content_type="application/json",
            **_token_header(cloner),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["title"], "Original")
        clone_id = response.json()["id"]
        self.assertEqual(Playlist.objects.get(id=clone_id).owner_id, cloner.id)

    def test_free_user_gets_premium_required_cloning(self):
        owner = premium_user(email="owner2@example.com")
        cloner = free_user(email="cloner2@example.com")
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="Original", testimony_id=testimony.id)

        response = self.client.post(
            reverse("playlist-clone", kwargs={"playlist_id": playlist.id}),
            {},
            content_type="application/json",
            **_token_header(cloner),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "premium_required")
