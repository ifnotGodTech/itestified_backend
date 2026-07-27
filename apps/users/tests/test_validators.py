from django.test import TestCase

from apps.users.validators import normalize_full_name


class NormalizeFullNameTests(TestCase):
    def test_titlecases_an_all_caps_name(self) -> None:
        self.assertEqual(normalize_full_name("AIGUOSATILE AISOSA"), "Aiguosatile Aisosa")

    def test_titlecases_a_lowercase_name(self) -> None:
        self.assertEqual(normalize_full_name("john doe"), "John Doe")

    def test_leaves_an_already_normalized_name_unchanged(self) -> None:
        self.assertEqual(normalize_full_name("Jane Smith"), "Jane Smith")

    def test_collapses_repeated_whitespace(self) -> None:
        self.assertEqual(normalize_full_name("  John   Doe  "), "John Doe")

    def test_blank_input_returns_blank(self) -> None:
        self.assertEqual(normalize_full_name(""), "")
        self.assertEqual(normalize_full_name("   "), "")
