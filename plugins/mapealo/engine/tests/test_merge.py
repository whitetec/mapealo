import unittest
from tests._fx import write_app  # asegura sys.path
from mapealo import _merge_layout


def _g(pillars, children):
    return {"pillars": pillars, "children": children}


class TestMergeLayout(unittest.TestCase):
    def test_preserves_existing_position(self):
        old = _g(
            [{"id": "backbone", "label": "Old Label", "position": {"x": 100, "y": 200}}],
            [{"id": "core",     "label": "Old Core",  "position": {"x": 50,  "y": 60}}],
        )
        fresh = _g(
            [{"id": "backbone", "label": "New Label", "color": "#fff", "position": {"x": 999, "y": 999}}],
            [{"id": "core",     "label": "New Core",  "parent": "backbone", "position": {"x": 999, "y": 999}}],
        )
        merged = _merge_layout(old, fresh)
        # posiciones se preservan
        self.assertEqual(merged["pillars"][0]["position"],  {"x": 100, "y": 200})
        self.assertEqual(merged["children"][0]["position"], {"x": 50,  "y": 60})
        # label/color se recomputan
        self.assertEqual(merged["pillars"][0]["label"], "New Label")
        self.assertEqual(merged["pillars"][0]["color"], "#fff")

    def test_drops_orphan_child_and_adds_new(self):
        old = _g(
            [{"id": "backbone", "position": {"x": 100, "y": 200}}],
            [
                {"id": "old_mod", "position": {"x": 10, "y": 20}},   # ya no existe
                {"id": "core",    "position": {"x": 30, "y": 40}},
            ],
        )
        fresh = _g(
            [{"id": "backbone", "position": {"x": 999, "y": 999}}],
            [
                {"id": "core",    "parent": "backbone", "position": {"x": 999, "y": 999}},
                {"id": "new_mod", "parent": "backbone", "position": {"x": 555, "y": 666}},
            ],
        )
        merged = _merge_layout(old, fresh)
        ids = [c["id"] for c in merged["children"]]
        self.assertEqual(set(ids), {"core", "new_mod"})       # huérfano eliminado
        # core preserva posición vieja
        core = next(c for c in merged["children"] if c["id"] == "core")
        self.assertEqual(core["position"], {"x": 30, "y": 40})
        # new_mod usa posición fresca (orbital)
        new_mod = next(c for c in merged["children"] if c["id"] == "new_mod")
        self.assertEqual(new_mod["position"], {"x": 555, "y": 666})


if __name__ == "__main__":
    unittest.main()
