"""Lưu CV và danh sách công ty theo dõi (SQLite, mỗi người dùng Discord một hồ sơ riêng)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from cv import Profile


class Store:
    def __init__(self, path: str):
        self.path = path
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS cv(user_id INTEGER PRIMARY KEY, filename TEXT, profile TEXT);
            CREATE TABLE IF NOT EXISTS company(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, careers_url TEXT,
              UNIQUE(user_id, name));
            CREATE TABLE IF NOT EXISTS feedback(
              user_id INTEGER, job_id TEXT, title TEXT, company TEXT, liked INTEGER,
              PRIMARY KEY(user_id, job_id));
            CREATE TABLE IF NOT EXISTS seen(company_id INTEGER, job_id TEXT, PRIMARY KEY(company_id, job_id));
            """)

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return closing_commit(db)

    def save_cv(self, user_id: int, filename: str, profile: Profile) -> None:
        with self._db() as db:
            db.execute("INSERT INTO cv VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                       "filename=excluded.filename, profile=excluded.profile",
                       (user_id, filename, json.dumps(profile.to_dict())))

    def get_cv(self, user_id: int) -> tuple[str, Profile] | None:
        with self._db() as db:
            r = db.execute("SELECT filename, profile FROM cv WHERE user_id=?", (user_id,)).fetchone()
        return (r["filename"], Profile.from_dict(json.loads(r["profile"]))) if r else None

    def delete_cv(self, user_id: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM cv WHERE user_id=?", (user_id,)).rowcount > 0

    def set_feedback(self, user_id: int, job_id: str, title: str, company: str, liked: bool) -> None:
        with self._db() as db:
            db.execute("INSERT INTO feedback VALUES(?,?,?,?,?) ON CONFLICT(user_id,job_id) "
                       "DO UPDATE SET liked=excluded.liked",
                       (user_id, job_id, title, company, int(liked)))

    def feedback(self, user_id: int, liked: bool, limit: int = 10) -> list[sqlite3.Row]:
        with self._db() as db:
            return db.execute("SELECT job_id, title, company FROM feedback WHERE user_id=? AND liked=? "
                              "ORDER BY rowid DESC LIMIT ?", (user_id, int(liked), limit)).fetchall()

    def disliked_ids(self, user_id: int) -> set[str]:
        with self._db() as db:
            return {r["job_id"] for r in db.execute(
                "SELECT job_id FROM feedback WHERE user_id=? AND liked=0", (user_id,))}

    def add_company(self, user_id: int, name: str, url: str | None) -> None:
        with self._db() as db:
            db.execute("INSERT INTO company(user_id,name,careers_url) VALUES(?,?,?) "
                       "ON CONFLICT(user_id,name) DO UPDATE SET careers_url=excluded.careers_url",
                       (user_id, name, url))

    def companies(self, user_id: int) -> list[sqlite3.Row]:
        with self._db() as db:
            return db.execute("SELECT * FROM company WHERE user_id=? ORDER BY name COLLATE NOCASE",
                              (user_id,)).fetchall()

    def remove_company(self, user_id: int, name: str) -> bool:
        with self._db() as db:
            r = db.execute("SELECT id FROM company WHERE user_id=? AND name=? COLLATE NOCASE",
                           (user_id, name)).fetchone()
            if not r:
                return False
            db.execute("DELETE FROM seen WHERE company_id=?", (r["id"],))
            db.execute("DELETE FROM company WHERE id=?", (r["id"],))
            return True

    def mark_seen(self, company_id: int, job_ids: list[str]) -> set[str]:
        """Ghi nhận các job đã thấy; trả về tập job MỚI (chưa từng thấy)."""
        with self._db() as db:
            old = {r["job_id"] for r in db.execute(
                "SELECT job_id FROM seen WHERE company_id=?", (company_id,))}
            new = set(job_ids) - old
            db.executemany("INSERT OR IGNORE INTO seen VALUES(?,?)", [(company_id, j) for j in new])
            return new

    def has_baseline(self, company_id: int) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM seen WHERE company_id=? LIMIT 1", (company_id,)).fetchone() is not None


class closing_commit:
    """Context manager: commit khi thành công rồi luôn đóng kết nối."""
    def __init__(self, db): self.db = db
    def __enter__(self): return self.db
    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                self.db.commit()
        finally:
            self.db.close()
        return False
