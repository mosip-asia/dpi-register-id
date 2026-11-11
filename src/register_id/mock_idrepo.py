"""
MOSIP Identity Repository (IDRepo) Mock Service.

Implements the official MOSIP IDRepo REST API specifications:
- POST /idrepository/v1/identity/ : Add or update identity and CBEFF biometrics
- GET /idrepository/v1/identity/uin/{uin} : Retrieve identity and biometrics by UIN
- GET /idrepository/v1/identity/ : List recently enrolled identities
- GET /v1/idgenerator/uin : Generate a unique sovereign citizen UIN
- POST /v1/authmanager/authenticate/clientidsecretkey : Service token acquisition
- GET /health : Service health check

Persists into PostgreSQL (mosip_idrepo.citizen_identity table) with SQLite fallback.
"""

import base64
import json
import logging
import os
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

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


storage = IDRepoStorage()

# FastAPI application exposing the official MOSIP IDRepo REST API
idrepo_app = FastAPI(title="MOSIP Identity Repository (IDRepo) Service")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@idrepo_app.get("/health")
def health_check():
    return {
        "status": "UP",
        "service": "mosip-id-repository",
        "backend": storage.active_backend,
        "timestamp": _now_iso(),
    }


@idrepo_app.get("/v1/idgenerator/uin")
def generate_uin():
    """
    Generates a fresh 10-digit citizen UIN conforming to MOSIP specifications.
    """
    # 10-digit number not starting with 0 or 1
    uin = str(random.randint(2000000000, 9999999999))
    return {
        "id": "mosip.idgenerator.uin",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {
            "uin": uin,
        },
        "errors": None,
    }


@idrepo_app.post("/v1/authmanager/authenticate/clientidsecretkey")
def authenticate_service_client(payload: dict):
    """
    MOSIP Auth Manager: clientidsecretkey authentication.
    Issues service token for mosip-idrepo-client.
    """
    return {
        "id": "io.mosip.auth",
        "version": "1.0",
        "responsetime": _now_iso(),
        "response": {
            "status": "SUCCESS",
            "token": "mock-mosip-service-token-" + str(random.randint(100000, 999999)),
            "message": "Authenticated successfully",
        },
        "errors": None,
    }


@idrepo_app.post("/idrepository/v1/identity/")
@idrepo_app.post("/idrepository/v1/identity")
def add_identity(payload: dict):
    """
    MOSIP IDRepo AddIdentity endpoint.
    Expects standard MOSIP envelope:
    {
      "id": "mosip.id.create",
      "version": "v1",
      "request": {
         "registrationId": "...",
         "status": "ACTIVATED",
         "identity": { "UIN": "...", "fullName": [...], "email": "...", "faceEmbedding": [...], "faceImage": "..." },
         "documents": [ { "category": "individualBiometrics", "value": "base64url..." } ]
      }
    }
    """
    req = payload.get("request", {})
    identity = req.get("identity", {})
    documents = req.get("documents", [])

    uin = identity.get("UIN")
    if not uin:
        raise HTTPException(
            status_code=400,
            detail={
                "id": "mosip.id.create",
                "version": "v1",
                "errors": [{"errorCode": "IDR-IDC-001", "message": "Missing mandatory field 'UIN'"}],
            },
        )

    # Extract full name (can be string or localized array [{"language":"eng", "value":"..."}])
    full_name_raw = identity.get("fullName")
    if isinstance(full_name_raw, list) and len(full_name_raw) > 0:
        full_name = full_name_raw[0].get("value", "")
    elif isinstance(full_name_raw, str):
        full_name = full_name_raw
    else:
        full_name = "Unknown Citizen"

    email = identity.get("email")
    face_image = identity.get("faceImage")
    face_embedding = identity.get("faceEmbedding")

    # Extract CBEFF XML from individualBiometrics document
    cbeff_xml = None
    for doc in documents:
        if doc.get("category") == "individualBiometrics":
            raw_val = doc.get("value", "")
            try:
                # Handle base64url or standard base64
                padded = raw_val + "=" * (-len(raw_val) % 4)
                decoded_bytes = base64.urlsafe_b64decode(padded)
                cbeff_xml = decoded_bytes.decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"Failed to decode CBEFF document: {e}")
                cbeff_xml = raw_val

    saved = storage.save_identity(
        uin=str(uin),
        full_name=full_name,
        email=email,
        face_image=face_image,
        face_embedding=face_embedding,
        cbeff_xml=cbeff_xml,
    )

    if not saved:
        raise HTTPException(
            status_code=500,
            detail={
                "id": "mosip.id.create",
                "version": "v1",
                "errors": [{"errorCode": "IDR-IDC-500", "message": "Failed to persist identity record"}],
            },
        )

    return {
        "id": "mosip.id.create",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {
            "status": req.get("status", "ACTIVATED"),
            "entity": "identity",
        },
        "errors": None,
    }


@idrepo_app.get("/idrepository/v1/identity/uin/{uin}")
def get_identity_by_uin(uin: str):
    """
    MOSIP IDRepo GetIdentity endpoint.
    Retrieves citizen demographics and CBEFF individualBiometrics.
    """
    record = storage.get_identity(uin)
    if not record:
        raise HTTPException(
            status_code=404,
            detail={
                "id": "mosip.id.read",
                "version": "v1",
                "response": None,
                "errors": [
                    {
                        "errorCode": "IDR-IDC-002",
                        "message": f"Identity record not found for UIN '{uin}'",
                    }
                ],
            },
        )

    # Format CBEFF as URL-safe base64
    cbeff_xml = record.get("cbeff_xml")
    documents = []
    if cbeff_xml:
        cbeff_b64url = base64.urlsafe_b64encode(cbeff_xml.encode("utf-8")).decode("utf-8")
        documents.append({
            "category": "individualBiometrics",
            "value": cbeff_b64url,
        })

    face_embedding = record.get("face_embedding")
    if isinstance(face_embedding, str):
        try:
            face_embedding = json.loads(face_embedding)
        except Exception:
            pass

    return {
        "id": "mosip.id.read",
        "version": "v1",
        "responsetime": _now_iso(),
        "metadata": None,
        "response": {
            "status": "ACTIVATED",
            "identity": {
                "UIN": record["uin"],
                "fullName": [{"language": "eng", "value": record["full_name"]}],
                "email": record.get("email"),
                "faceImage": record.get("face_image"),
                "faceEmbedding": face_embedding,
                "createdAt": str(record.get("created_at")),
            },
            "documents": documents,
        },
        "errors": None,
    }


@idrepo_app.get("/idrepository/v1/identity/")
@idrepo_app.get("/idrepository/v1/identity")
def list_identities(limit: int = 50):
    """
    Returns list of recently registered identities.
    """
    rows = storage.list_identities(limit=limit)
    return {
        "id": "mosip.id.list",
        "version": "v1",
        "responsetime": _now_iso(),
        "response": [
            {
                "uin": r["uin"],
                "fullName": r["full_name"],
                "email": r.get("email"),
                "createdAt": str(r.get("created_at")),
            }
            for r in rows
        ],
        "errors": None,
    }


def run_idrepo_server(host: str = "0.0.0.0", port: int = 8080):
    import uvicorn
    uvicorn.run(idrepo_app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    run_idrepo_server(host="0.0.0.0", port=port)
