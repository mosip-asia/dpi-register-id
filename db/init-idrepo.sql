-- ==============================================================================
-- MOSIP IDRepo Database Schema Initialization
-- Executed automatically on first container startup of PostgreSQL
-- ==============================================================================

CREATE SCHEMA IF NOT EXISTS mosip_idrepo;

CREATE TABLE IF NOT EXISTS mosip_idrepo.citizen_identity (
    uin VARCHAR(32) PRIMARY KEY,
    full_name VARCHAR(128) NOT NULL,
    email VARCHAR(128),
    face_image TEXT,
    cbeff_xml TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_citizen_created_at
    ON mosip_idrepo.citizen_identity (created_at DESC);

-- Match vectors live outside the identity row. IDA reads this table only.
-- slot is the row's position in the saved list; engine is NULL for hash rows
-- written before engines were recorded.
CREATE SCHEMA IF NOT EXISTS mosip_ida;

CREATE TABLE IF NOT EXISTS mosip_ida.face_template (
    uin VARCHAR(32) NOT NULL,
    sector VARCHAR(16) NOT NULL,
    slot INTEGER NOT NULL DEFAULT 0,
    engine VARCHAR(32),
    embedding TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uin, sector, slot)
);
