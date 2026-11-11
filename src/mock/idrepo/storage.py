"""
Storage backend for Mock MOSIP IDRepo.

Connects to PostgreSQL (mosip_idrepo schema) when available,
with automatic SQLite fallback for offline environments.
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

    def _init_backend(self):
        conn = self._get_pg_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE SCHEMA IF NOT EXISTS mosip_idrepo;
                        CREATE TABLE IF NOT EXISTS mosip_idrepo.citizen_identity (
                            uin VARCHAR(32) PRIMARY KEY,
                            full_name VARCHAR(128) NOT NULL,
                            email VARCHAR(128),
                            face_image TEXT,
                            face_embedding TEXT,
                            cbeff_xml TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

        # Fallback to SQLite
        conn = self._get_sqlite_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS citizen_identity (
                    uin TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    email TEXT,
                    face_image TEXT,
                    face_embedding TEXT,
                    cbeff_xml TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.close()
        self.active_backend = "sqlite"
        logger.info(f"IDRepo storage initialized on SQLite fallback: {_SQLITE_PATH}")

    def save_identity(
        self,
        uin: str,
        full_name: str,
        email: str | None,
        face_image: str | None,
        face_embedding: list[float] | None,
        cbeff_xml: str | None,
    ) -> bool:
        embedding_json = json.dumps(face_embedding) if face_embedding is not None else None

        if self.active_backend == "postgres":
            conn = self._get_pg_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO mosip_idrepo.citizen_identity
                                (uin, full_name, email, face_image, face_embedding, cbeff_xml)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (uin) DO UPDATE
                            SET full_name = EXCLUDED.full_name,
                                email = EXCLUDED.email,
                                face_image = EXCLUDED.face_image,
                                face_embedding = EXCLUDED.face_embedding,
                                cbeff_xml = EXCLUDED.cbeff_xml;
                        """, (uin, full_name, email, face_image, embedding_json, cbeff_xml))
                        conn.commit()
                    return True
                except Exception as e:
                    logger.error(f"PostgreSQL insert failed: {e}")
                finally:
                    conn.close()

        # SQLite fallback
        conn = self._get_sqlite_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO citizen_identity
                        (uin, full_name, email, face_image, face_embedding, cbeff_xml)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (uin) DO UPDATE
                    SET full_name = excluded.full_name,
                        email = excluded.email,
                        face_image = excluded.face_image,
                        face_embedding = excluded.face_embedding,
                        cbeff_xml = excluded.cbeff_xml;
                """, (uin, full_name, email, face_image, embedding_json, cbeff_xml))
            return True
        except Exception as e:
            logger.error(f"SQLite insert failed: {e}")
            return False
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
                            SELECT uin, full_name, email, face_embedding, face_image, cbeff_xml, created_at
                            FROM mosip_idrepo.citizen_identity WHERE uin = %s;
                        """, (uin,))
                        row = cur.fetchone()
                        if row:
                            return dict(row)
                except Exception as e:
                    logger.error(f"PostgreSQL select failed: {e}")
                finally:
                    conn.close()

        # SQLite fallback
        conn = self._get_sqlite_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT uin, full_name, email, face_embedding, face_image, cbeff_xml, created_at
                FROM citizen_identity WHERE uin = ?;
            """, (uin,))
            row = cur.fetchone()
            if row:
                return dict(row)
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
                            SELECT uin, full_name, email, created_at
                            FROM mosip_idrepo.citizen_identity
                            ORDER BY created_at DESC LIMIT %s;
                        """, (limit,))
                        return [dict(r) for r in cur.fetchall()]
                except Exception as e:
                    logger.error(f"PostgreSQL list failed: {e}")
                finally:
                    conn.close()

        # SQLite fallback
        conn = self._get_sqlite_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT uin, full_name, email, created_at
                FROM citizen_identity
                ORDER BY created_at DESC LIMIT ?;
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
