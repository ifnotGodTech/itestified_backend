from django.test import TestCase

from apps.playlists.choices import PlaylistVisibility
from apps.playlists.exceptions import (
    PlaylistItemAlreadyExistsError,
    PlaylistItemLimitExceededError,
    PlaylistLimitExceededError,
    PlaylistNotFoundError,
    PlaylistPremiumRequiredError,
    PlaylistReorderMismatchError,
    TestimonyNotFoundError,
)
from apps.playlists.models import Playlist, PlaylistItem
from apps.playlists.services import commands
from apps.playlists.tests.factories import approved_testimony, category, free_user, premium_user


class CreatePlaylistTests(TestCase):
    def test_free_user_cannot_create_a_playlist(self):
        user = free_user()
        testimony = approved_testimony()
        with self.assertRaises(PlaylistPremiumRequiredError):
            commands.create_playlist(owner=user, title="My List", testimony_id=testimony.id)

    def test_premium_user_creates_a_playlist_seeded_with_one_testimony(self):
        owner = premium_user()
        testimony = approved_testimony()

        playlist = commands.create_playlist(owner=owner, title="  Sunday Favorites  ", testimony_id=testimony.id)

        self.assertEqual(playlist.title, "Sunday Favorites")
        self.assertEqual(playlist.visibility, PlaylistVisibility.PRIVATE)
        self.assertEqual(PlaylistItem.objects.filter(playlist=playlist).count(), 1)
        self.assertEqual(PlaylistItem.objects.get(playlist=playlist).testimony_id, testimony.id)

    def test_cannot_create_a_playlist_from_a_missing_testimony(self):
        owner = premium_user()
        with self.assertRaises(TestimonyNotFoundError):
            commands.create_playlist(owner=owner, title="My List", testimony_id=999999)

    def test_cannot_exceed_the_playlists_per_owner_cap(self):
        owner = premium_user()
        testimony = approved_testimony()
        for _ in range(commands.MAX_PLAYLISTS_PER_OWNER):
            commands.create_playlist(owner=owner, title="List", testimony_id=testimony.id)

        with self.assertRaises(PlaylistLimitExceededError):
            commands.create_playlist(owner=owner, title="One too many", testimony_id=testimony.id)


class RenamePlaylistTests(TestCase):
    def test_renames_and_trims_the_title(self):
        owner = premium_user()
        playlist = Playlist.objects.create(owner=owner, title="Old Name")

        renamed = commands.rename_playlist(playlist=playlist, actor=owner, title="  New Name  ")

        self.assertEqual(renamed.title, "New Name")

    def test_lapsed_premium_cannot_rename(self):
        owner = free_user()
        playlist = Playlist.objects.create(owner=owner, title="Old Name")
        with self.assertRaises(PlaylistPremiumRequiredError):
            commands.rename_playlist(playlist=playlist, actor=owner, title="New Name")


class AddRemoveItemTests(TestCase):
    def setUp(self):
        self.owner = premium_user()
        self.testimony_category = category()
        self.testimony_a = approved_testimony(category_obj=self.testimony_category, title="A")
        self.playlist = commands.create_playlist(owner=self.owner, title="List", testimony_id=self.testimony_a.id)

    def test_adding_a_second_item_appends_at_the_next_position(self):
        testimony_b = approved_testimony(category_obj=self.testimony_category, title="B")
        commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=testimony_b.id)

        item_b = PlaylistItem.objects.get(playlist=self.playlist, testimony=testimony_b)
        self.assertEqual(item_b.position, 1)

    def test_cannot_add_the_same_testimony_twice(self):
        with self.assertRaises(PlaylistItemAlreadyExistsError):
            commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=self.testimony_a.id)

    def test_cannot_exceed_the_items_per_playlist_cap(self):
        for i in range(commands.MAX_ITEMS_PER_PLAYLIST - 1):
            testimony = approved_testimony(category_obj=self.testimony_category, title=f"T{i}")
            commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=testimony.id)

        one_more = approved_testimony(category_obj=self.testimony_category, title="one more")
        with self.assertRaises(PlaylistItemLimitExceededError):
            commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=one_more.id)

    def test_removing_the_last_item_leaves_an_empty_playlist_shell(self):
        commands.remove_item(playlist=self.playlist, actor=self.owner, testimony_id=self.testimony_a.id)

        self.assertFalse(PlaylistItem.objects.filter(playlist=self.playlist).exists())
        self.assertTrue(Playlist.objects.filter(id=self.playlist.id).exists())

    def test_removing_an_item_resequences_remaining_positions(self):
        testimony_b = approved_testimony(category_obj=self.testimony_category, title="B")
        testimony_c = approved_testimony(category_obj=self.testimony_category, title="C")
        commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=testimony_b.id)
        commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=testimony_c.id)

        commands.remove_item(playlist=self.playlist, actor=self.owner, testimony_id=testimony_b.id)

        remaining = list(PlaylistItem.objects.filter(playlist=self.playlist).order_by("position"))
        self.assertEqual([item.testimony_id for item in remaining], [self.testimony_a.id, testimony_c.id])
        self.assertEqual([item.position for item in remaining], [0, 1])

    def test_removing_a_testimony_not_in_the_playlist_raises(self):
        other = approved_testimony(category_obj=self.testimony_category, title="Not in playlist")
        with self.assertRaises(TestimonyNotFoundError):
            commands.remove_item(playlist=self.playlist, actor=self.owner, testimony_id=other.id)


class ReorderItemsTests(TestCase):
    def setUp(self):
        self.owner = premium_user()
        self.testimony_category = category()
        self.testimony_a = approved_testimony(category_obj=self.testimony_category, title="A")
        self.playlist = commands.create_playlist(owner=self.owner, title="List", testimony_id=self.testimony_a.id)
        self.testimony_b = approved_testimony(category_obj=self.testimony_category, title="B")
        self.testimony_c = approved_testimony(category_obj=self.testimony_category, title="C")
        commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=self.testimony_b.id)
        commands.add_item(playlist=self.playlist, actor=self.owner, testimony_id=self.testimony_c.id)

    def test_reorders_to_the_given_sequence(self):
        new_order = [self.testimony_c.id, self.testimony_a.id, self.testimony_b.id]
        commands.reorder_items(playlist=self.playlist, actor=self.owner, ordered_testimony_ids=new_order)

        items = list(PlaylistItem.objects.filter(playlist=self.playlist).order_by("position"))
        self.assertEqual([item.testimony_id for item in items], new_order)

    def test_rejects_a_list_missing_an_existing_item(self):
        incomplete = [self.testimony_a.id, self.testimony_b.id]
        with self.assertRaises(PlaylistReorderMismatchError):
            commands.reorder_items(playlist=self.playlist, actor=self.owner, ordered_testimony_ids=incomplete)

    def test_rejects_a_list_with_an_id_not_in_the_playlist(self):
        foreign = approved_testimony(category_obj=self.testimony_category, title="Foreign")
        bad_order = [self.testimony_a.id, self.testimony_b.id, foreign.id]
        with self.assertRaises(PlaylistReorderMismatchError):
            commands.reorder_items(playlist=self.playlist, actor=self.owner, ordered_testimony_ids=bad_order)


class VisibilityAndNameSettingTests(TestCase):
    def test_set_visibility_to_shared_and_back(self):
        owner = premium_user()
        playlist = Playlist.objects.create(owner=owner, title="List")

        commands.set_visibility(playlist=playlist, actor=owner, visibility=PlaylistVisibility.SHARED)
        playlist.refresh_from_db()
        self.assertEqual(playlist.visibility, PlaylistVisibility.SHARED)

        commands.set_visibility(playlist=playlist, actor=owner, visibility=PlaylistVisibility.PRIVATE)
        playlist.refresh_from_db()
        self.assertEqual(playlist.visibility, PlaylistVisibility.PRIVATE)

    def test_set_show_owner_name(self):
        owner = premium_user()
        playlist = Playlist.objects.create(owner=owner, title="List")

        commands.set_show_owner_name(playlist=playlist, actor=owner, show_owner_name=False)
        playlist.refresh_from_db()
        self.assertFalse(playlist.show_owner_name)


class DeletePlaylistTests(TestCase):
    def test_deleting_removes_the_playlist_and_its_items_only(self):
        owner = premium_user()
        testimony = approved_testimony()
        playlist = commands.create_playlist(owner=owner, title="List", testimony_id=testimony.id)

        commands.delete_playlist(playlist=playlist, actor=owner)

        self.assertFalse(Playlist.objects.filter(id=playlist.id).exists())
        testimony.refresh_from_db()


class ClonePlaylistTests(TestCase):
    def test_any_premium_user_can_clone_any_playlist_by_id(self):
        owner = premium_user(email="owner@example.com")
        cloner = premium_user(email="cloner@example.com")
        testimony_category = category()
        testimony_a = approved_testimony(category_obj=testimony_category, title="A")
        testimony_b = approved_testimony(category_obj=testimony_category, title="B")
        source = commands.create_playlist(owner=owner, title="Original", testimony_id=testimony_a.id)
        commands.add_item(playlist=source, actor=owner, testimony_id=testimony_b.id)

        clone = commands.clone_playlist(source_playlist_id=source.id, actor=cloner)

        self.assertEqual(clone.owner_id, cloner.id)
        self.assertEqual(clone.title, "Original")
        cloned_testimony_ids = set(PlaylistItem.objects.filter(playlist=clone).values_list("testimony_id", flat=True))
        self.assertEqual(cloned_testimony_ids, {testimony_a.id, testimony_b.id})
        # The original is untouched -- a clone is an independent copy.
        self.assertEqual(PlaylistItem.objects.filter(playlist=source).count(), 2)

    def test_clone_can_use_a_custom_title(self):
        owner = premium_user(email="owner2@example.com")
        cloner = premium_user(email="cloner2@example.com")
        testimony = approved_testimony()
        source = commands.create_playlist(owner=owner, title="Original", testimony_id=testimony.id)

        clone = commands.clone_playlist(source_playlist_id=source.id, actor=cloner, title="My Copy")

        self.assertEqual(clone.title, "My Copy")

    def test_free_user_cannot_clone(self):
        owner = premium_user(email="owner3@example.com")
        cloner = free_user(email="cloner3@example.com")
        testimony = approved_testimony()
        source = commands.create_playlist(owner=owner, title="Original", testimony_id=testimony.id)

        with self.assertRaises(PlaylistPremiumRequiredError):
            commands.clone_playlist(source_playlist_id=source.id, actor=cloner)

    def test_cloning_a_missing_playlist_raises(self):
        cloner = premium_user()
        with self.assertRaises(PlaylistNotFoundError):
            commands.clone_playlist(source_playlist_id=999999, actor=cloner)

    def test_cannot_clone_past_the_playlists_per_owner_cap(self):
        owner = premium_user(email="owner4@example.com")
        cloner = premium_user(email="cloner4@example.com")
        testimony = approved_testimony()
        source = commands.create_playlist(owner=owner, title="Original", testimony_id=testimony.id)
        for _ in range(commands.MAX_PLAYLISTS_PER_OWNER):
            commands.create_playlist(owner=cloner, title="List", testimony_id=testimony.id)

        with self.assertRaises(PlaylistLimitExceededError):
            commands.clone_playlist(source_playlist_id=source.id, actor=cloner)
