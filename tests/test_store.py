"""Tests for leaf's SQLite store. Run with: python -m unittest discover tests"""

import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store  # noqa: E402

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="isbn">978-0-00-000000-0</dc:identifier>
    <dc:identifier id="uid">{uid}</dc:identifier>
    <dc:title>Test</dc:title>
  </metadata>
</package>"""


def make_epub(path, uid):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF.format(uid=uid))
    return path


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.store = store.Store(self.dir / "leaf.db")

    def tearDown(self):
        self.store.close()

    def test_schema_created_at_current_version(self):
        self.assertEqual(self.store.version(), store.SCHEMA_VERSION)
        tables = {r[0] for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"books", "settings", "annotations"} <= tables)

    def test_migrate_is_idempotent(self):
        self.store.migrate()
        again = store.Store(self.dir / "leaf.db")
        self.assertEqual(again.version(), store.SCHEMA_VERSION)
        again.close()

    def test_refuses_newer_schema(self):
        self.store.db.execute(f"PRAGMA user_version = {store.SCHEMA_VERSION + 1}")
        with self.assertRaises(RuntimeError):
            store.Store(self.dir / "leaf.db")

    def test_identity_uses_unique_identifier_not_first(self):
        book = make_epub(self.dir / "a.epub", "urn:uuid:1234")
        self.assertEqual(store.book_identity(book), "epub:urn:uuid:1234")

    def test_identity_falls_back_to_hash(self):
        f = self.dir / "not-an-epub.epub"
        f.write_bytes(b"plain bytes")
        self.assertTrue(store.book_identity(f).startswith("sha256:"))

    def test_progress_survives_moving_the_file(self):
        book = make_epub(self.dir / "a.epub", "urn:uuid:move")
        row = self.store.open_book(book)
        self.store.save_progress(row["id"], cfi="epubcfi(/6/4!/2)", fraction=0.5, title="T")
        moved = book.rename(self.dir / "renamed.epub")
        again = self.store.open_book(moved)
        self.assertEqual(again["id"], row["id"])
        self.assertEqual(again["cfi"], "epubcfi(/6/4!/2)")
        self.assertEqual(again["path"], str(moved.resolve()))

    def test_two_windows_do_not_overwrite_each_other(self):
        a = make_epub(self.dir / "a.epub", "urn:uuid:a")
        b = make_epub(self.dir / "b.epub", "urn:uuid:b")
        other = store.Store(self.dir / "leaf.db")          # a second leaf window
        ra, rb = self.store.open_book(a), other.open_book(b)
        self.store.save_progress(ra["id"], cfi="cfi-a", fraction=0.1)
        other.save_progress(rb["id"], cfi="cfi-b", fraction=0.9)
        self.assertEqual(self.store.book(ra["id"])["cfi"], "cfi-a")
        self.assertEqual(self.store.book(rb["id"])["cfi"], "cfi-b")
        other.close()

    def test_save_progress_keeps_fields_not_sent(self):
        row = self.store.open_book(make_epub(self.dir / "a.epub", "urn:uuid:keep"))
        self.store.save_progress(row["id"], cfi="c1", fraction=0.2, title="Title", author="Author")
        self.store.save_progress(row["id"], cfi="c2", fraction=0.3)
        got = self.store.book(row["id"])
        self.assertEqual((got["cfi"], got["title"], got["author"]), ("c2", "Title", "Author"))

    def test_recent_skips_missing_files_newest_first(self):
        a = make_epub(self.dir / "a.epub", "urn:uuid:ra")
        b = make_epub(self.dir / "b.epub", "urn:uuid:rb")
        self.store.open_book(a, now=100)
        self.store.open_book(b, now=200)
        self.assertEqual([r["id"] for r in self.store.recent()], ["epub:urn:uuid:rb", "epub:urn:uuid:ra"])
        b.unlink()
        self.assertEqual([r["id"] for r in self.store.recent()], ["epub:urn:uuid:ra"])

    def test_settings_defaults_and_updates(self):
        self.assertEqual(self.store.settings(), store.DEFAULT_SETTINGS)
        self.store.set_settings({"theme": "ink", "fontSize": 22, "bogus": 1})
        self.assertEqual(self.store.settings()["theme"], "ink")
        self.assertEqual(self.store.settings()["fontSize"], 22)
        self.assertNotIn("bogus", self.store.settings())

    def test_import_legacy_json_keeps_newer_position(self):
        book = make_epub(self.dir / "a.epub", "urn:uuid:legacy")
        legacy = self.dir / "library.json"
        legacy.write_text(json.dumps({
            "books": {str(book.resolve()): {"cfi": "old", "fraction": 0.4, "title": "L", "opened": 1000}},
            "settings": {"theme": "paper", "fontSize": 20, "pageSound": True}}))
        self.assertEqual(self.store.import_legacy_json(legacy), 1)
        self.assertFalse(legacy.exists())
        self.assertTrue((self.dir / "library.json.imported").exists())
        book_id = store.book_identity(book)
        self.assertEqual(self.store.book(book_id)["cfi"], "old")
        self.assertTrue(self.store.settings()["pageSound"])
        # an older leaf window writes an outdated library.json again: the newer DB row wins
        self.store.save_progress(book_id, cfi="newer", now=2000)
        legacy.write_text(json.dumps({"books": {str(book.resolve()): {"cfi": "stale", "opened": 1500}}}))
        self.store.import_legacy_json(legacy)
        self.assertEqual(self.store.book(book_id)["cfi"], "newer")

    def test_annotations_table_is_ready_and_cascades(self):
        row = self.store.open_book(make_epub(self.dir / "a.epub", "urn:uuid:ann"))
        self.store.db.execute(
            "INSERT INTO annotations (book_id, kind, cfi, created, updated) VALUES (?, 'bookmark', 'c', 0, 0)",
            (row["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute(
                "INSERT INTO annotations (book_id, kind, cfi, created, updated) VALUES (?, 'doodle', 'c', 0, 0)",
                (row["id"],))
        self.store.db.execute("DELETE FROM books WHERE id = ?", (row["id"],))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM annotations").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
