import unittest
from unittest.mock import patch

from tests._fx import write_app
from analyzer.wp_remote import inventory


CFG = {"ssh": {"host": "x", "user": "y", "key": "z", "wp_path": "/p"}}


class TestListPlugins(unittest.TestCase):
    @patch("analyzer.wp_remote.inventory.run_wp_cli")
    def test_normalizes_records(self, mock_run):
        mock_run.return_value = [
            {"name": "akismet", "title": "Akismet", "status": "active",
             "version": "5.3.1", "update": "available"},
            {"name": "hello", "title": "", "status": "inactive",
             "version": "1.7.2", "update": "none"},
        ]
        plugins = inventory.list_plugins(CFG)
        self.assertEqual(plugins[0]["title"], "Akismet")
        self.assertEqual(plugins[0]["update"], "available")
        # title vacío cae al name
        self.assertEqual(plugins[1]["title"], "hello")

    @patch("analyzer.wp_remote.inventory.run_wp_cli")
    def test_active_plugins_filter(self, mock_run):
        mock_run.return_value = [
            {"name": "a", "status": "active",   "title": "A", "version": "1", "update": "none"},
            {"name": "b", "status": "must-use", "title": "B", "version": "1", "update": "none"},
            {"name": "c", "status": "inactive", "title": "C", "version": "1", "update": "none"},
        ]
        active = inventory.get_active_plugins(CFG)
        self.assertEqual(active, {"a", "b"})


class TestListPostTypes(unittest.TestCase):
    @patch("analyzer.wp_remote.inventory.run_wp_cli")
    def test_filters_core(self, mock_run):
        mock_run.return_value = [
            {"name": "post",       "label": "Posts",  "public": "1", "hierarchical": ""},
            {"name": "page",       "label": "Pages",  "public": "1", "hierarchical": "1"},
            {"name": "tour",       "label": "Tours",  "public": "1", "hierarchical": ""},
            {"name": "event",      "label": "Events", "public": "1", "hierarchical": ""},
            {"name": "wp_block",   "label": "Blocks", "public": "",  "hierarchical": ""},
        ]
        cpts = inventory.list_post_types(CFG)
        names = {c["name"] for c in cpts}
        self.assertEqual(names, {"tour", "event"})


class TestListTaxonomies(unittest.TestCase):
    @patch("analyzer.wp_remote.inventory.run_wp_cli")
    def test_object_types_string_split(self, mock_run):
        mock_run.return_value = [
            {"name": "category", "label": "Categories", "object_type": "post", "hierarchical": "1"},
            {"name": "destino",  "label": "Destinos",   "object_type": "tour,event", "hierarchical": "1"},
            {"name": "actividad","label": "Actividades","object_type": ["tour", "itinerario"], "hierarchical": ""},
        ]
        tax = inventory.list_taxonomies(CFG)
        names = [t["name"] for t in tax]
        self.assertEqual(names, ["destino", "actividad"])  # category filtrada
        destino = next(t for t in tax if t["name"] == "destino")
        self.assertEqual(destino["object_types"], ["tour", "event"])
        actividad = next(t for t in tax if t["name"] == "actividad")
        self.assertEqual(actividad["object_types"], ["tour", "itinerario"])


class TestTruthy(unittest.TestCase):
    def test_strings(self):
        self.assertTrue(inventory._truthy("1"))
        self.assertTrue(inventory._truthy("true"))
        self.assertTrue(inventory._truthy("YES"))
        self.assertFalse(inventory._truthy(""))
        self.assertFalse(inventory._truthy("0"))


if __name__ == "__main__":
    unittest.main()
