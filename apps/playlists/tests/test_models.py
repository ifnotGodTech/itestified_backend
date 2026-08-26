from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.playlists.choices import PlaylistVisibility
from apps.playlists.models import Playlist, PlaylistItem
from apps.playlists.tests.factories import approved_testimony, premium_user


class PlaylistModelTests(TestCase):
    def test_defaults_to_private_and_shows_owner_name(self):
        owner = premium_user()
        playlist = Playlist.objects.create(owner=owner, title="Sunday Favorites")
        self.assertEqual(playlist.visibility, PlaylistVisibility.PRIVATE)
        self.assertTrue(playlist.show_owner_name)

    def test_a_testimony_can_only_appear_once_per_playlist(self):
        owner = premium_user()
        playlist = Playlist.objects.create(owner=owner, title="Sunday Favorites")
        testimony = approved_testimony()
        PlaylistItem.objects.create(playlist=playlist, testimony=testimony, position=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlaylistItem.objects.create(playlist=playlist, testimony=testimony, position=1)

    def test_deleting_a_playlist_deletes_its_items_not_the_testimony(self):
        owner = premium_user()
        playlist = Playlist.objects.create(owner=owner, title="Sunday Favorites")
        testimony = approved_testimony()
        PlaylistItem.objects.create(playlist=playlist, testimony=testimony, position=0)

        playlist.delete()

        self.assertFalse(PlaylistItem.objects.exists())
        testimony.refresh_from_db()

    def test_deleting_a_testimony_removes_it_from_every_playlist(self):
        owner = premium_user()
        playlist = Playlist.objects.create(owner=owner, title="Sunday Favorites")
        testimony = approved_testimony()
        PlaylistItem.objects.create(playlist=playlist, testimony=testimony, position=0)

        testimony.delete()

        self.assertFalse(PlaylistItem.objects.exists())
        self.assertTrue(Playlist.objects.filter(id=playlist.id).exists())
