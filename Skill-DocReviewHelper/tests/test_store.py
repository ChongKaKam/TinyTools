import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_store import Conflict, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace"
        self.root.mkdir()
        self.store = Store(self.root)
        self.draft = self.root / "draft.md"

    def test_revision_and_restore_keep_historical_asset_and_notes(self):
        image = self.root / "figure one.svg"
        original = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="2"/></svg>'
        image.write_bytes(original)
        markdown = '# Example\r\n\r\n![First](<figure one.svg> "Caption")\n'
        self.draft.write_bytes(markdown.encode())
        self.store.publish("demo", self.draft, base=0)
        figure = self.store.view("demo", 1)["blocks"][1]
        self.store.save_note("demo", 1, figure["id"], "Replace figure", rev=0)

        image.write_bytes(original.replace(b'r="2"', b'r="3"'))
        self.store.publish("demo", self.draft, base=1)
        self.assertNotEqual(self.store.view("demo", 2)["blocks"][1]["asset"], figure["asset"])
        self.assertEqual(self.store.notes("demo", 2), [])
        image.unlink()
        self.draft.unlink()
        self.assertEqual(self.store.restore("demo", 1, base=2), 3)
        self.assertEqual(self.store.source("demo", 3), markdown)
        self.assertEqual(self.store.notes("demo", 3), [])
        self.assertEqual(self.store.notes("demo", 1)[0]["note"], "Replace figure")

        pinned = self.store.source("demo", 3, pin_images=True)
        self.assertEqual(pinned, markdown.replace("figure one.svg", "dochelper-asset:" + figure["asset"]))
        self.draft.write_bytes(pinned.encode())
        self.store.publish("demo", self.draft, base=3)
        snapshot = self.store.view("demo", 4)["blocks"][1]["asset"]
        self.assertEqual(self.store.asset(snapshot), ("image/svg+xml", original))

    def test_concurrent_writes_and_stale_revisions(self):
        self.draft.write_text("One paragraph", encoding="utf-8")
        self.store.publish("demo", self.draft, base=0)

        def write(text):
            try:
                self.store.save_note("demo", 1, 1, text, rev=0)
                return text
            except Conflict:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = [text for text in pool.map(write, ("one", "two", "three", "four")) if text]
        self.assertEqual(winners, [self.store.notes("demo", 1)[0]["note"]])
        self.assertEqual(self.store.save_note("demo", 1, 1, "", rev=1), {"note": "", "rev": 2})
        with self.assertRaises(Conflict):
            self.store.save_note("demo", 1, 1, "Outdated", rev=0)
        with self.assertRaises(Conflict):
            self.store.publish("demo", self.draft, base=0)
        self.assertEqual(self.store.history("demo")[0]["version"], 1)

    def test_image_and_storage_paths_stay_in_workspace(self):
        outside = self.root.parent / "outside.svg"
        outside.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        (self.root / "link.svg").symlink_to(outside)
        for target in ("../outside.svg", "link.svg", "dochelper-asset:" + "0" * 64):
            with self.subTest(target=target):
                self.draft.write_text(f"![x]({target})", encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.store.publish("demo", self.draft)
                self.assertEqual(self.store.list_docs(), [])
        another = self.root.parent / "another"
        another.mkdir()
        (another / ".dochelper").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            Store(another)
        self.assertFalse((self.root.parent / "reviews.sqlite3").exists())
