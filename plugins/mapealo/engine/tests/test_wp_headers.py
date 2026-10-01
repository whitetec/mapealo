import unittest
from tests._fx import write_app  # asegura sys.path
from analyzer.wp.headers import parse_header


class TestParseHeader(unittest.TestCase):
    def test_plugin_header(self):
        text = (
            "<?php\n"
            "/*\n"
            " * Plugin Name: My Plugin\n"
            " * Version: 1.2.3\n"
            " * Description: Hace cosas.\n"
            " * Author: Jane Doe\n"
            " */\n"
            "function foo() {}\n"
        )
        h = parse_header(text)
        self.assertEqual(h["Plugin Name"], "My Plugin")
        self.assertEqual(h["Version"],     "1.2.3")
        self.assertEqual(h["Description"], "Hace cosas.")
        self.assertEqual(h["Author"],      "Jane Doe")

    def test_theme_header_with_template(self):
        text = (
            "/*\n"
            "Theme Name: Mi Child\n"
            "Template: parent-theme\n"
            "Version: 0.1\n"
            "*/\n"
        )
        h = parse_header(text)
        self.assertEqual(h["Theme Name"], "Mi Child")
        self.assertEqual(h["Template"],   "parent-theme")

    def test_unknown_fields_ignored(self):
        text = "/* Plugin Name: X\nFoo Bar: yes\n */\n"
        h = parse_header(text)
        self.assertIn("Plugin Name", h)
        self.assertNotIn("Foo Bar", h)

    def test_only_first_8k(self):
        big = "// padding\n" * 1000
        text = big + "/* Plugin Name: TooLate */\n"
        h = parse_header(text)
        self.assertNotIn("Plugin Name", h)


if __name__ == "__main__":
    unittest.main()
