"""
Database operations for the Internship Outreach Agent.
Handles all SQLite interactions for companies, contacts, and outreach tracking.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional


DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "outreach.db"
SCHEMA_PATH = DB_DIR / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """Get a database connection, creating the DB + tables if needed."""
    db_exists = DB_PATH.exists()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not db_exists:
        with open(SCHEMA_PATH, "r") as f:
            conn.executescript(f.read())
        conn.commit()
    return conn


# ── Companies ────────────────────────────────────────────────

def add_company(name: str, domain: str = None, notes: str = None) -> int:
    """Insert a company. Returns the company ID."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO companies (name, domain, notes) VALUES (?, ?, ?)",
            (name, domain, notes),
        )
        conn.commit()
        if cur.lastrowid == 0:
            row = conn.execute(
                "SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
            return row["id"]
        return cur.lastrowid
    finally:
        conn.close()


def get_company(name: str) -> Optional[dict]:
    """Get a company by name."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM companies WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_companies() -> list[dict]:
    """Get all companies."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM companies ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_company_processed(company_id: int):
    """Mark a company as fully processed."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE companies SET processed = 1 WHERE id = ?", (company_id,))
        conn.commit()
    finally:
        conn.close()


# ── Contacts ─────────────────────────────────────────────────

def add_contact(
    company_id: int,
    name: str,
    title: str = None,
    linkedin_url: str = None,
    personalization_hooks: list[str] = None,
    research_notes: str = None,
) -> int:
    """Insert a contact. Returns the contact ID."""
    conn = get_connection()
    try:
        hooks_json = json.dumps(
            personalization_hooks) if personalization_hooks else None
        cur = conn.execute(
            """INSERT INTO contacts
               (company_id, name, title, linkedin_url, personalization_hooks, research_notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company_id, name, title, linkedin_url, hooks_json, research_notes),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_contact_email(
    contact_id: int, email: str, confidence: float = None, source: str = None
):
    """Update a contact's email after discovery."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE contacts
               SET email = ?, email_confidence = ?, email_source = ?, status = 'email_found'
               WHERE id = ?""",
            (email, confidence, source, contact_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_contact_status(contact_id: int, status: str):
    """Update a contact's pipeline status."""
    conn = get_connection()
    try:
        conn.execute("UPDATE contacts SET status = ? WHERE id = ?",
                     (status, contact_id))
        conn.commit()
    finally:
        conn.close()


def get_contacts_by_status(status: str) -> list[dict]:
    """Get all contacts with a given status."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT c.*, comp.name as company_name, comp.domain as company_domain
               FROM contacts c
               JOIN companies comp ON c.company_id = comp.id
               WHERE c.status = ?
               ORDER BY c.created_at""",
            (status,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("personalization_hooks"):
                d["personalization_hooks"] = json.loads(
                    d["personalization_hooks"])
            results.append(d)
        return results
    finally:
        conn.close()


def get_contacts_by_company(company_id: int) -> list[dict]:
    """Get all contacts for a company."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE company_id = ? ORDER BY created_at",
            (company_id,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("personalization_hooks"):
                d["personalization_hooks"] = json.loads(
                    d["personalization_hooks"])
            results.append(d)
        return results
    finally:
        conn.close()


def contact_exists(name: str, company_id: int) -> bool:
    """Check if a contact already exists for a given company."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM contacts WHERE name = ? AND company_id = ?",
            (name, company_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ── Outreach ─────────────────────────────────────────────────

def save_draft(contact_id: int, subject: str, body: str, personalization_note: str = None) -> int:
    """Save an email draft. Returns the outreach ID."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT OR REPLACE INTO outreach
               (contact_id, subject, body, personalization_note)
               VALUES (?, ?, ?, ?)""",
            (contact_id, subject, body, personalization_note),
        )
        conn.execute(
            "UPDATE contacts SET status = 'drafted' WHERE id = ?", (contact_id,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def approve_draft(outreach_id: int):
    """Mark a draft as approved for sending."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE outreach SET approved = 1 WHERE id = ?", (outreach_id,))
        row = conn.execute(
            "SELECT contact_id FROM outreach WHERE id = ?", (outreach_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE contacts SET status = 'approved' WHERE id = ?", (row["contact_id"],))
        conn.commit()
    finally:
        conn.close()


def mark_sent(outreach_id: int):
    """Mark an email as sent."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE outreach SET sent_at = datetime('now') WHERE id = ?",
            (outreach_id,),
        )
        row = conn.execute(
            "SELECT contact_id FROM outreach WHERE id = ?", (outreach_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE contacts SET status = 'sent' WHERE id = ?", (row["contact_id"],))
        conn.commit()
    finally:
        conn.close()


def get_pending_drafts() -> list[dict]:
    """Get all drafts awaiting review (not yet approved)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT o.*, c.name as contact_name, c.title as contact_title,
                      c.email as contact_email, comp.name as company_name
               FROM outreach o
               JOIN contacts c ON o.contact_id = c.id
               JOIN companies comp ON c.company_id = comp.id
               WHERE o.approved = 0 AND o.sent_at IS NULL
               ORDER BY o.created_at""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_approved_unsent() -> list[dict]:
    """Get all approved drafts not yet sent."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT o.*, c.name as contact_name, c.title as contact_title,
                      c.email as contact_email, comp.name as company_name
               FROM outreach o
               JOIN contacts c ON o.contact_id = c.id
               JOIN companies comp ON c.company_id = comp.id
               WHERE o.approved = 1 AND o.sent_at IS NULL
               ORDER BY o.created_at""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pipeline_stats() -> dict:
    """Get counts for each pipeline stage."""
    conn = get_connection()
    try:
        stats = {}
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM contacts GROUP BY status"
        ).fetchall()
        for r in rows:
            stats[r["status"]] = r["count"]
        stats["total_companies"] = conn.execute(
            "SELECT COUNT(*) FROM companies").fetchone()[0]
        stats["pending_drafts"] = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE approved = 0 AND sent_at IS NULL"
        ).fetchone()[0]
        stats["approved_unsent"] = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE approved = 1 AND sent_at IS NULL"
        ).fetchone()[0]
        stats["total_sent"] = conn.execute(
            "SELECT COUNT(*) FROM outreach WHERE sent_at IS NOT NULL"
        ).fetchone()[0]
        return stats
    finally:
        conn.close()
