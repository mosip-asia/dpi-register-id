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
    face_embedding TEXT,
    cbeff_xml TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_citizen_created_at
    ON mosip_idrepo.citizen_identity (created_at DESC);
