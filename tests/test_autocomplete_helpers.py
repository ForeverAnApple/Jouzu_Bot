import unittest

from lib.autocomplete_helpers import DISCORD_CHOICE_NAME_LIMIT, build_choice_name


class TestBuildChoiceName(unittest.TestCase):
    def test_short_title_without_label(self):
        self.assertEqual(
            build_choice_name("My Happy Marriage", 119713, "API"),
            "My Happy Marriage (ID: 119713) (API)",
        )

    def test_short_title_with_label(self):
        self.assertEqual(
            build_choice_name("My Happy Marriage", 108389, "Cached", label="Light Novel"),
            "[Light Novel] My Happy Marriage (ID: 108389) (Cached)",
        )

    def test_long_title_without_label_fits(self):
        name = build_choice_name("x" * 200, 123456, "API")
        self.assertLessEqual(len(name), DISCORD_CHOICE_NAME_LIMIT)
        self.assertTrue(name.endswith(" (ID: 123456) (API)"))

    def test_long_title_with_label_fits(self):
        name = build_choice_name("x" * 200, 123456, "Cached", label="Light Novel")
        self.assertLessEqual(len(name), DISCORD_CHOICE_NAME_LIMIT)
        self.assertTrue(name.startswith("[Light Novel] "))
        self.assertTrue(name.endswith(" (ID: 123456) (Cached)"))

    def test_suffix_intact_for_long_id(self):
        name = build_choice_name("y" * 200, "v" * 30, "Cached")
        self.assertLessEqual(len(name), DISCORD_CHOICE_NAME_LIMIT)
        self.assertTrue(name.endswith(f" (ID: {'v' * 30}) (Cached)"))


if __name__ == "__main__":
    unittest.main()
