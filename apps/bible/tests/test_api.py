from django.test import TestCase
from django.urls import reverse

from apps.bible.choices import BiblePackKind
from apps.bible.models import BiblePack


def _pack(code: str, **overrides) -> BiblePack:
    fields = dict(
        code=code, kind=BiblePackKind.VERSION, name=code.upper(), abbreviation=code.upper(),
        attribution="Public domain", file_url=f"https://cdn.example.com/{code}.sqlite.gz",
        size_bytes=1234, sha256="f" * 64, is_enabled=True,
    )
    fields.update(overrides)
    return BiblePack.objects.create(**fields)


class BiblePackListApiTests(TestCase):
    url = reverse("bible-pack-list")

    def test_guests_can_list_packs_without_logging_in(self):
        _pack("bsb", is_default=True)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_lists_only_enabled_packs_in_display_order_with_the_download_contract(self):
        _pack("kjv", sort_order=20)
        _pack("bsb", sort_order=10, is_default=True, description="Modern English", data_version=3)
        _pack("hidden", is_enabled=False)
        _pack("study", kind=BiblePackKind.STUDY, supports_word_study=True)

        body = self.client.get(self.url).json()

        self.assertEqual(body["count"], 3)
        self.assertEqual([item["code"] for item in body["results"]], ["study", "bsb", "kjv"])
        bsb = body["results"][1]
        self.assertEqual(
            bsb,
            {
                "code": "bsb",
                "kind": "version",
                "name": "BSB",
                "abbreviation": "BSB",
                "description": "Modern English",
                "attribution": "Public domain",
                "supports_word_study": False,
                "is_online_only": False,
                "file_url": "https://cdn.example.com/bsb.sqlite.gz",
                "size_bytes": 1234,
                "sha256": "f" * 64,
                "data_version": 3,
                "is_default": True,
            },
        )

    def test_response_is_publicly_cacheable(self):
        response = self.client.get(self.url)
        self.assertIn("public", response["Cache-Control"])
        self.assertIn("max-age=300", response["Cache-Control"])

    def test_is_read_only(self):
        response = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 405)
