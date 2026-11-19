"""Copy the tracker's data folder to a new place and prove the copy is complete.

    python copy_data.py <source data folder> <target data folder>

Used by move-data.ps1. It never changes or deletes anything in the source.
The database is copied with SQLite's backup API (safe even if a -wal file
exists), then checked: integrity check, and the same number of rows in every
table. Every photo is copied and compared by size and SHA-256. Exits with
code 1 and says why if anything doesn't match.
"""

import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def table_counts(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def fail(message):
    print(f"FAILED: {message}")
    sys.exit(1)


def main(src, dst):
    src, dst = Path(src).resolve(), Path(dst).resolve()
    src_db, dst_db = src / "db.sqlite3", dst / "db.sqlite3"
    if not src_db.is_file():
        fail(f"no database at {src_db}")
    if dst_db.exists():
        fail(f"{dst_db} already exists; refusing to overwrite it")
    dst.mkdir(parents=True, exist_ok=True)

    # 1. Database, via the backup API so pending WAL changes are included.
    source = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    target = sqlite3.connect(dst_db)
    with target:
        source.backup(target)
    source.close()
    target.execute("PRAGMA journal_mode=WAL")
    ok = target.execute("PRAGMA integrity_check").fetchone()[0]
    target.close()
    if ok != "ok":
        fail(f"integrity check on the copy said: {ok}")
    a, b = table_counts(src_db), table_counts(dst_db)
    if a != b:
        diff = {t: (a.get(t), b.get(t)) for t in set(a) | set(b) if a.get(t) != b.get(t)}
        fail(f"row counts differ: {diff}")
    print(f"Database copied: {len(a)} tables, {a.get('tracker_ticket', 0)} tickets, "
          f"{a.get('tracker_photo', 0)} photo records, {a.get('accounts_user', 0)} users. Integrity OK.")

    # 2. Secret key (keeps everyone logged in and signed links valid).
    key = src / "secret_key.txt"
    if key.is_file():
        shutil.copy2(key, dst / "secret_key.txt")
        if sha256(key) != sha256(dst / "secret_key.txt"):
            fail("secret key copy doesn't match")

    # 3. Photos and documents.
    for folder in ("photos", "documents"):
        src_dir, dst_dir = src / folder, dst / folder
        dst_dir.mkdir(exist_ok=True)
        files = [p for p in src_dir.rglob("*") if p.is_file()] if src_dir.is_dir() else []
        total = 0
        for p in files:
            out = dst_dir / p.relative_to(src_dir)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            if p.stat().st_size != out.stat().st_size or sha256(p) != sha256(out):
                fail(f"{folder} file {p.name} didn't copy correctly")
            total += p.stat().st_size
        print(f"{folder.capitalize()} copied and checked: {len(files)} files, {total / 1024 / 1024:.1f} MB.")
    print("COPY VERIFIED")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
