import unittest
from tests._fx import write_app
from analyzer import detect_kind, KIND_PYTHON, KIND_WORDPRESS, KIND_UNKNOWN
from analyzer.wp.detect import detect_plugins, detect_themes


class TestDetectKind(unittest.TestCase):
    def test_wordpress_via_wp_config(self):
        d = write_app({"wp-config.php": "<?php // ..."})
        self.assertEqual(detect_kind(d), KIND_WORDPRESS)

    def test_wordpress_via_wp_content(self):
        d = write_app({"wp-content/.gitkeep": ""})
        self.assertEqual(detect_kind(d), KIND_WORDPRESS)

    def test_python_via_requirements(self):
        d = write_app({"requirements.txt": "fastapi\n"})
        self.assertEqual(detect_kind(d), KIND_PYTHON)

    def test_python_via_pyproject(self):
        d = write_app({"pyproject.toml": "[project]\nname='x'\n"})
        self.assertEqual(detect_kind(d), KIND_PYTHON)

    def test_unknown_when_empty(self):
        d = write_app({"README.md": "x"})
        self.assertEqual(detect_kind(d), KIND_UNKNOWN)

    def test_wordpress_beats_python_when_both_markers(self):
        d = write_app({
            "wp-config.php":    "<?php",
            "requirements.txt": "x",
        })
        self.assertEqual(detect_kind(d), KIND_WORDPRESS)


class TestDetectPlugins(unittest.TestCase):
    def test_finds_plugin_with_main_file(self):
        d = write_app({
            "wp-config.php": "<?php",
            "wp-content/plugins/my-plugin/my-plugin.php":
                "<?php\n/*\nPlugin Name: My Plugin\nVersion: 1.0\n*/\n",
        })
        plugins = detect_plugins(d)
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["slug"], "my-plugin")
        self.assertEqual(plugins[0]["meta"]["Plugin Name"], "My Plugin")

    def test_skips_dir_without_plugin_header(self):
        d = write_app({
            "wp-config.php": "<?php",
            "wp-content/plugins/empty/.gitkeep": "",
            "wp-content/plugins/has-php-no-header/foo.php": "<?php // nada",
        })
        self.assertEqual(detect_plugins(d), [])

    def test_main_file_fallback_to_first_php(self):
        d = write_app({
            "wp-config.php": "<?php",
            "wp-content/plugins/weird/init.php":
                "<?php\n/* Plugin Name: Weird */\n",
        })
        plugins = detect_plugins(d)
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["meta"]["Plugin Name"], "Weird")


class TestDetectThemes(unittest.TestCase):
    def test_parent_and_child(self):
        d = write_app({
            "wp-config.php": "<?php",
            "wp-content/themes/parent/style.css":
                "/*\nTheme Name: Parent\nVersion: 1\n*/\n",
            "wp-content/themes/child/style.css":
                "/*\nTheme Name: Child\nTemplate: parent\n*/\n",
        })
        themes = detect_themes(d)
        slugs = {t["slug"] for t in themes}
        self.assertEqual(slugs, {"parent", "child"})
        child = next(t for t in themes if t["slug"] == "child")
        self.assertEqual(child["meta"]["Template"], "parent")


if __name__ == "__main__":
    unittest.main()
