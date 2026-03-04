-- ============================================================
-- Internship Outreach Agent — Database Schema
-- ============================================================

CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    domain      TEXT,
    notes       TEXT,
    created_at  TEXT    DEFAULT (datetime('now')),
    processed   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contacts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id          INTEGER NOT NULL,
    name                TEXT    NOT NULL,
    title               TEXT,
    linkedin_url        TEXT,
    email               TEXT,
    email_confidence     REAL,
    email_source        TEXT,
    personalization_hooks TEXT,          -- JSON array of hooks
    research_notes      TEXT,
    status              TEXT    DEFAULT 'researched',   -- researched | email_found | drafted | approved | sent | replied | opted_out
    created_at          TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS outreach (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL UNIQUE,
    subject     TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    personalization_note TEXT,
    approved    INTEGER DEFAULT 0,
    sent_at     TEXT,
    opened_at   TEXT,
    replied_at  TEXT,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (contact_id) REFERENCES contacts(id)
);

CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_outreach_approved ON outreach(approved);
