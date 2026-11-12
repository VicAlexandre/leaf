"""leaf's persistent state: reading progress, settings, and (later) annotations.

One SQLite database, ~/.local/state/leaf/leaf.db, in WAL mode so several leaf
windows can read and write at once. Every save touches a single row inside a
transaction, so windows never overwrite each other's progress.

Books are keyed by identity, not path: the EPUB's unique identifier
("epub:<id>"), or a SHA-256 of the file when it has none ("sha256:<hex>").
Moving or renaming a book keeps its progress; the stored path just follows it.

Schema changes are numbered migrations tracked in PRAGMA user_version. To add
a feature, append a migration to MIGRATIONS; never edit an applied one.
"""

import hashlib
import json
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

DEFAULT_SETTINGS = {"theme": "paper", "fontSize": 19, "pageSound": False}

MIGRATIONS = [
    # 1: books and settings; annotations is prepared for future highlights,
    #    notes and bookmarks but nothing uses it yet.
    """
    CREATE TABLE books (
        id       TEXT PRIMARY KEY,           -- epub:<identifier> or sha256:<hex>
        path     TEXT NOT NULL,              -- last known location
        title    TEXT,
        author   TEXT,
        cfi      TEXT,                       -- exact reading position (EPUB CFI)
        fraction REAL NOT NULL DEFAULT 0,    -- 0..1, for progress bars
        added    REAL NOT NULL,              -- unix time
        opened   REAL NOT NULL               -- unix time, last opened or read
    );
    CREATE INDEX books_opened ON books (opened DESC);

    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL                  -- JSON
    );

    CREATE TABLE annotations (
        id      INTEGER PRIMARY KEY,
        book_id TEXT NOT NULL REFERENCES books (id) ON DELETE CASCADE,
        kind    TEXT NOT NULL CHECK (kind IN ('highlight', 'note', 'bookmark')),
        cfi     TEXT NOT NULL,               -- position or range
        text    TEXT,                        -- quoted passage
        note    TEXT,                        -- the reader's note
        color   TEXT,
        created REAL NOT NULL,
        updated REAL NOT NULL
    );
    CREATE INDEX annotations_book ON annotations (book_id, kind);
    """,
]
SCHEMA_VERSION = len(MIGRATIONS)

OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


def book_identity(path):
    """Stable id for a book file: its EPUB unique identifier, else a hash of the file."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile").get("full-path")
            opf = ET.fromstring(z.read(rootfile))
            uid = opf.get("unique-identifier")
            ids = opf.findall(".//dc:identifier", OPF_NS)
            chosen = next((i for i in ids if uid and i.get("id") == uid), ids[0] if ids else None)
            if chosen is not None and (chosen.text or "").strip():
                return "epub:" + chosen.text.strip()
    except (OSError, KeyError, AttributeError, IndexError, zipfile.BadZipFile, ET.ParseError):
        pass
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    # ── schema ───────────────────────────────────────────────────────────────
    def version(self):
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self):
        current = self.version()
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"{self.path} has schema {current}; this leaf knows up to {SCHEMA_VERSION}")
        for n in range(current, SCHEMA_VERSION):
            self.db.executescript(f"BEGIN IMMEDIATE; {MIGRATIONS[n]}; PRAGMA user_version = {n + 1}; COMMIT;")

    # ── books ────────────────────────────────────────────────────────────────
    def open_book(self, path, now=None):
        """Register (or re-find) a book file and mark it opened. Returns its row."""
        path = Path(path).resolve()
        book_id, now = book_identity(path), now or time.time()
        self.db.execute(
            """INSERT INTO books (id, path, added, opened) VALUES (?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET path = excluded.path, opened = excluded.opened""",
            (book_id, str(path), now, now))
        return self.book(book_id)

    def book(self, book_id):
        row = self.db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return dict(row) if row else None

    def save_progress(self, book_id, cfi=None, fraction=None, title=None, author=None, now=None):
        self.db.execute(
            """UPDATE books SET cfi = coalesce(?, cfi), fraction = coalesce(?, fraction),
                                title = coalesce(?, title), author = coalesce(?, author), opened = ?
               WHERE id = ?""",
            (cfi, fraction, title, author, now or time.time(), book_id))

    def recent(self, limit=30):
        """Recently opened books whose files still exist, newest first."""
        rows = self.db.execute("SELECT * FROM books ORDER BY opened DESC").fetchall()
        out = [dict(r) for r in rows if Path(r["path"]).exists()]
        return out[:limit]

    # ── settings ─────────────────────────────────────────────────────────────
    def settings(self):
        stored = {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT key, value FROM settings")}
        return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}

    def set_settings(self, values):
        rows = [(k, json.dumps(v)) for k, v in values.items() if k in DEFAULT_SETTINGS]
        with self.db:
            self.db.execute("BEGIN")
            self.db.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value", rows)

    # ── import from leaf's first, JSON-based format ──────────────────────────
    def import_legacy_json(self, json_path):
        """Import library.json (positions keyed by path), keeping whichever position is newer,
        then rename it to library.json.imported. Returns the number of books imported."""
        json_path = Path(json_path)
        try:
            data = json.loads(json_path.read_text())
        except (OSError, ValueError):
            return 0
        count = 0
        for path, e in data.get("books", {}).items():
            p = Path(path)
            book_id = book_identity(p) if p.is_file() else f"path:{path}"
            opened = float(e.get("opened") or 0)
            existing = self.book(book_id)
            if existing and existing["opened"] >= opened:
                continue
            self.db.execute(
                """INSERT INTO books (id, path, title, author, cfi, fraction, added, opened)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET path = excluded.path, title = excluded.title,
                       author = excluded.author, cfi = excluded.cfi, fraction = excluded.fraction,
                       opened = excluded.opened""",
                (book_id, path, e.get("title"), e.get("author"), e.get("cfi"),
                 float(e.get("fraction") or 0), opened or time.time(), opened or time.time()))
            count += 1
        if data.get("settings"):
            self.set_settings(data["settings"])
        json_path.replace(json_path.with_name(json_path.name + ".imported"))
        return count

    def close(self):
        self.db.close()
