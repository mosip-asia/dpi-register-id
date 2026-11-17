"""
Storage backend for Mock MOSIP IDRepo.

Connects to PostgreSQL (mosip_idrepo schema) when available,
with automatic SQLite fallback for offline environments.

Identity rows store demographics, record status, the login-disabled flag,
the face image, and CBEFF only. Match vectors live in face_template
(mosip_ida on PostgreSQL). The gateway reaches this store through HTTP.
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "MosipPostgresPass123!")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

_DATA_DIR = Path("data")
_SQLITE_PATH = _DATA_DIR / "idrepo.db"

_LEGACY_BIOMETRIC_COLUMNS = ("face_embedding", "face_views")


def _coerce_embedding(raw: Any) -> list[float]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        raise ValueError("stored embedding is not a list")
    return [float(value) for value in raw]


def _embedding_text(embedding: Any) -> str:
    if isinstance(embedding, str):
        return embedding
    return json.dumps(embedding)


def _normalize_identity(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    record["status"] = record.get("status") or "draft"
    record["login_disabled"] = bool(record.get("login_disabled"))
    return record


_RECORD_STATUSES = frozenset({"draft", "biometric"})


class IDRepoStorage:
    """
    Direct storage backend for the MOSIP IDRepo service (PostgreSQL + SQLite fallback).
    """

    def __init__(self):
        self.active_backend: str = "uninitialized"
        self._init_backend()

    def _get_pg_connection(self):
        try:
            import psycopg2
            return psycopg2.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_DB,
                connect_timeout=2,
            )
        except Exception as e:
            logger.debug(f"PostgreSQL connection to {POSTGRES_HOST}:{POSTGRES_PORT} failed: {e}")
            return None

    def _get_sqlite_connection(self):
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_SQLITE_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        conn = self._get_sqlite_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS citizen_identity (
                        uin TEXT PRIMARY KEY,
                        full_name TEXT NOT NULL,
                        email TEXT,
                        face_image TEXT,
                        cbeff_xml TEXT,
                        status TEXT NOT NULL DEFAULT 'draft',
                        login_disabled INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                self._migrate_sqlite(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS face_template (
                        uin TEXT NOT NULL,
                        sector TEXT NOT NULL,
                        embedding TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (uin, sector)
                    );
                """)
        finally:
            conn.close()

    def _init_backend(self):
        # SQLite is always prepared so a Postgres miss or outage has a schema to fall back to.
        self._init_sqlite()

        conn = self._get_pg_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA IF NOT EXISTS mosip_idrepo;")
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS mosip_idrepo.citizen_identity (
                            uin VARCHAR(32) PRIMARY KEY,
                            full_name VARCHAR(128) NOT NULL,
                            email VARCHAR(128),
                            face_image TEXT,
                            cbeff_xml TEXT,
                            status VARCHAR(16) NOT NULL DEFAULT 'draft',
                            login_disabled BOOLEAN NOT NULL DEFAULT FALSE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    cur.execute("""
                        ALTER TABLE mosip_idrepo.citizen_identity
                        ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'draft';
                    """)
                    cur.execute("""
                        ALTER TABLE mosip_idrepo.citizen_identity
                        ADD COLUMN IF NOT EXISTS login_disabled BOOLEAN NOT NULL DEFAULT FALSE;
                    """)
                    cur.execute("CREATE SCHEMA IF NOT EXISTS mosip_ida;")
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS mosip_ida.face_template (
                            uin VARCHAR(32) NOT NULL,
                            sector VARCHAR(16) NOT NULL,
                            embedding TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (uin, sector)
                        );
                    """)
                    conn.commit()
                self.active_backend = "postgres"
                logger.info("IDRepo storage initialized on PostgreSQL backend.")
                return
            except Exception as e:
                logger.warning(f"Failed to initialize PostgreSQL schema: {e}")
            finally:
                conn.close()

        self.active_backend = "sqlite"
        logger.info(f"IDRepo storage initialized on SQLite fallback: {_SQLITE_PATH}")

    def _migrate_sqlite(self, conn) -> None:
        info = conn.execute("PRAGMA table_info(citizen_identity)").fetchall()
        present = {row[1] for row in info}
        if "status" not in present:
            conn.execute(
                "ALTER TABLE citizen_identity ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'"
            )
        if "login_disabled" not in present:
            conn.execute(
                "ALTER TABLE citizen_identity "
                "ADD COLUMN login_disabled INTEGER NOT NULL DEFAULT 0"
            )

    def _clear_legacy_pg(self, cur, uin: str) -> None:
        """Null leftover template columns on databases created before the split."""
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'mosip_idrepo'
              AND table_name = 'citizen_identity'
              AND column_name IN ('face_embedding', 'face_views');
        """)
        columns = [row[0] for row in cur.fetchall() if row[0] in _LEGACY_BIOMETRIC_COLUMNS]
        if not columns:
            return
        assignments = ", ".join(f"{column} = NULL" for column in columns)
        cur.execute(
            f"UPDATE mosip_idrepo.citizen_identity SET {assignments} WHERE uin = %s",
            (uin,),
        )

    def _clear_legacy_sqlite(self, conn, uin: str) -> None:
        info = conn.execute("PRAGMA table_info(citizen_identity)").fetchall()
        present = {row[1] for row in info}
        columns = [name for name in _LEGACY_BIOMETRIC_COLUMNS if name in present]
        if not columns:
            return
        assignments = ", ".join(f"{column} = NULL" for column in columns)
        conn.execute(
            f"UPDATE citizen_identity SET {assignments} WHERE uin = ?",
            (uin,),
        )

    def save_identity(
        self,
        uin: str,
        full_name: str,
        email: str | None,
        face_image: str | None,
        cbeff_xml: str | None,
        status: str = "draft",
    ) -> bool:
        # Callers that omit status stay draft. A face on the row is not a match.
        if status not in _RECORD_STATUSES:
            logger.error(f"Refusing identity save with status '{status}'")
            return False

        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO mosip_idrepo.citizen_identity
                                (uin, full_name, email, face_image, cbeff_xml, status)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (uin) DO UPDATE
                            SET full_name = EXCLUDED.full_name,
                                email = EXCLUDED.email,
                                face_image = EXCLUDED.face_image,
                                cbeff_xml = EXCLUDED.cbeff_xml,
                                status = EXCLUDED.status;
                        """, (uin, full_name, email, face_image, cbeff_xml, status))
                        self._clear_legacy_pg(cur, uin)
                    conn.commit()
                    return True
                except Exception as e:
                    logger.error(f"PostgreSQL insert failed: {e}")
                    conn.rollback()
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO citizen_identity
                        (uin, full_name, email, face_image, cbeff_xml, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (uin) DO UPDATE
                    SET full_name = excluded.full_name,
                        email = excluded.email,
                        face_image = excluded.face_image,
                        cbeff_xml = excluded.cbeff_xml,
                        status = excluded.status;
                """, (uin, full_name, email, face_image, cbeff_xml, status))
                self._clear_legacy_sqlite(conn, uin)
            return True
        except Exception as e:
            logger.error(f"SQLite insert failed: {e}")
            return False
        finally:
            conn.close()

    def _sqlite_has_uin(self, conn, uin: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM citizen_identity WHERE uin = ?",
            (uin,),
        ).fetchone()
        return row is not None

    def update_demographics(self, uin: str, full_name: str, email: str | None) -> bool:
        """Correct name and email. Face bytes, templates, status, and login flag stay."""
        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE mosip_idrepo.citizen_identity
                            SET full_name = %s, email = %s
                            WHERE uin = %s;
                        """, (full_name, email, uin))
                        cur.execute(
                            "SELECT 1 FROM mosip_idrepo.citizen_identity WHERE uin = %s;",
                            (uin,),
                        )
                        updated = cur.fetchone() is not None
                    conn.commit()
                    return updated
                except Exception as e:
                    logger.error(f"PostgreSQL demographic update failed: {e}")
                    conn.rollback()
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE citizen_identity
                    SET full_name = ?, email = ?
                    WHERE uin = ?;
                """, (full_name, email, uin))
                return self._sqlite_has_uin(conn, uin)
        except Exception as e:
            logger.error(f"SQLite demographic update failed: {e}")
            return False
        finally:
            conn.close()

    def set_login_disabled(self, uin: str, disabled: bool) -> bool:
        """Operator flag stored on the identity. This does not call Keycloak."""
        flag = bool(disabled)
        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE mosip_idrepo.citizen_identity
                            SET login_disabled = %s
                            WHERE uin = %s;
                        """, (flag, uin))
                        cur.execute(
                            "SELECT 1 FROM mosip_idrepo.citizen_identity WHERE uin = %s;",
                            (uin,),
                        )
                        updated = cur.fetchone() is not None
                    conn.commit()
                    return updated
                except Exception as e:
                    logger.error(f"PostgreSQL login flag update failed: {e}")
                    conn.rollback()
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE citizen_identity
                    SET login_disabled = ?
                    WHERE uin = ?;
                """, (1 if flag else 0, uin))
                return self._sqlite_has_uin(conn, uin)
        except Exception as e:
            logger.error(f"SQLite login flag update failed: {e}")
            return False
        finally:
            conn.close()

    def delete_face(self, uin: str) -> bool:
        """Remove the face image, CBEFF document, and face templates for one UIN."""
        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM mosip_idrepo.citizen_identity WHERE uin = %s;",
                            (uin,),
                        )
                        if cur.fetchone() is None:
                            conn.rollback()
                            return False
                        cur.execute("""
                            UPDATE mosip_idrepo.citizen_identity
                            SET face_image = NULL, cbeff_xml = NULL
                            WHERE uin = %s;
                        """, (uin,))
                        cur.execute(
                            "DELETE FROM mosip_ida.face_template WHERE uin = %s;",
                            (uin,),
                        )
                        self._clear_legacy_pg(cur, uin)
                    conn.commit()
                    return True
                except Exception as e:
                    logger.error(f"PostgreSQL face delete failed: {e}")
                    conn.rollback()
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            with conn:
                if not self._sqlite_has_uin(conn, uin):
                    return False
                conn.execute("""
                    UPDATE citizen_identity
                    SET face_image = NULL, cbeff_xml = NULL
                    WHERE uin = ?;
                """, (uin,))
                conn.execute("DELETE FROM face_template WHERE uin = ?;", (uin,))
                self._clear_legacy_sqlite(conn, uin)
            return True
        except Exception as e:
            logger.error(f"SQLite face delete failed: {e}")
            return False
        finally:
            conn.close()

    def save_face_templates(self, uin: str, templates: list[dict]) -> bool:
        """Replace every stored sector for this UIN in one transaction."""
        rows = [
            (uin, item["sector"], _embedding_text(item["embedding"]))
            for item in templates
        ]

        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "DELETE FROM mosip_ida.face_template WHERE uin = %s",
                            (uin,),
                        )
                        cur.executemany("""
                            INSERT INTO mosip_ida.face_template (uin, sector, embedding)
                            VALUES (%s, %s, %s)
                        """, rows)
                    conn.commit()
                    return True
                except Exception as e:
                    logger.error(f"PostgreSQL template replace failed: {e}")
                    conn.rollback()
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            with conn:
                conn.execute("DELETE FROM face_template WHERE uin = ?", (uin,))
                conn.executemany("""
                    INSERT INTO face_template (uin, sector, embedding)
                    VALUES (?, ?, ?)
                """, rows)
            return True
        except Exception as e:
            logger.error(f"SQLite template replace failed: {e}")
            return False
        finally:
            conn.close()

    def _rows_to_templates(self, rows: list) -> list[dict[str, Any]]:
        templates = []
        for row in rows:
            record = dict(row)
            templates.append({
                "sector": record["sector"],
                "embedding": _coerce_embedding(record["embedding"]),
            })
        return templates

    def get_face_templates(self, uin: str) -> list[dict[str, Any]]:
        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    from psycopg2.extras import RealDictCursor
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT sector, embedding
                            FROM mosip_ida.face_template
                            WHERE uin = %s
                            ORDER BY sector;
                        """, (uin,))
                        return self._rows_to_templates(cur.fetchall())
                except Exception as e:
                    logger.error(f"PostgreSQL template select failed: {e}")
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT sector, embedding
                FROM face_template
                WHERE uin = ?
                ORDER BY sector;
            """, (uin,))
            return self._rows_to_templates(cur.fetchall())
        finally:
            conn.close()

    def get_identity(self, uin: str) -> dict[str, Any] | None:
        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    from psycopg2.extras import RealDictCursor
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT uin, full_name, email, face_image, cbeff_xml,
                                   status, login_disabled, created_at
                            FROM mosip_idrepo.citizen_identity WHERE uin = %s;
                        """, (uin,))
                        row = cur.fetchone()
                        return _normalize_identity(dict(row)) if row else None
                except Exception as e:
                    logger.error(f"PostgreSQL select failed: {e}")
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT uin, full_name, email, face_image, cbeff_xml,
                       status, login_disabled, created_at
                FROM citizen_identity WHERE uin = ?;
            """, (uin,))
            row = cur.fetchone()
            if row:
                return _normalize_identity(dict(row))
            return None
        finally:
            conn.close()

    def list_identities(self, limit: int = 50) -> list[dict[str, Any]]:
        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    from psycopg2.extras import RealDictCursor
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT uin, full_name, email, status, login_disabled, created_at
                            FROM mosip_idrepo.citizen_identity
                            ORDER BY created_at DESC LIMIT %s;
                        """, (limit,))
                        return [_normalize_identity(dict(r)) for r in cur.fetchall()]
                except Exception as e:
                    logger.error(f"PostgreSQL list failed: {e}")
                finally:
                    conn.close()

        conn = self._get_sqlite_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT uin, full_name, email, status, login_disabled, created_at
                FROM citizen_identity
                ORDER BY created_at DESC LIMIT ?;
            """, (limit,))
            return [_normalize_identity(dict(r)) for r in cur.fetchall()]
        finally:
            conn.close()
