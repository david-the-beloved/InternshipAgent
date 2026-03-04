"""
Email sending and review system.
Handles Gmail SMTP delivery with rate limiting, and a CLI review interface
for approving/editing/rejecting AI-generated email drafts.
"""

import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from db.database import (
    approve_draft,
    get_approved_unsent,
    get_pending_drafts,
    mark_sent,
    update_contact_status,
)


# ── Rate Limiting ────────────────────────────────────────────

MAX_EMAILS_PER_DAY = 20
_sent_today = 0
_day_start = time.time()


def _check_daily_limit() -> bool:
    """Check if we've hit the daily send limit."""
    global _sent_today, _day_start
    now = time.time()
    # Reset counter after 24 hours
    if now - _day_start > 86400:
        _sent_today = 0
        _day_start = now
    return _sent_today < MAX_EMAILS_PER_DAY


# ── Gmail SMTP Sender ────────────────────────────────────────

def send_email(to_email: str, subject: str, body: str) -> bool:
    """
    Send an email via Gmail SMTP.
    Requires GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env.
    Returns True if sent successfully.
    """
    global _sent_today

    if not _check_daily_limit():
        print(
            f"  ✗ Daily send limit reached ({MAX_EMAILS_PER_DAY}/day). Try again tomorrow.")
        return False

    gmail_address = os.getenv("GMAIL_ADDRESS", "")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD", "")

    if not gmail_address or not gmail_password:
        print("  ✗ Gmail credentials not configured. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
        return False
    if gmail_address == "your.email@gmail.com":
        print("  ✗ Please update GMAIL_ADDRESS in .env with your real email.")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = gmail_address
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = gmail_address

    # Send as plain text (better deliverability for cold emails)
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, to_email, msg.as_string())

        _sent_today += 1
        return True

    except smtplib.SMTPAuthenticationError:
        print("  ✗ Gmail authentication failed. Check your App Password.")
        print("    → Enable 2FA: https://myaccount.google.com/security")
        print("    → Create App Password: https://myaccount.google.com/apppasswords")
        return False
    except smtplib.SMTPException as e:
        print(f"  ✗ SMTP error: {e}")
        return False


# ── Send All Approved Emails ─────────────────────────────────

def send_approved_emails():
    """Send all approved but unsent emails, with delays between each."""
    emails = get_approved_unsent()

    if not emails:
        print("No approved emails to send.")
        return

    print(f"\nSending {len(emails)} approved email(s)...\n")

    sent_count = 0
    for email_data in emails:
        to = email_data["contact_email"]
        subject = email_data["subject"]
        body = email_data["body"]
        name = email_data["contact_name"]
        company = email_data["company_name"]

        print(f"  → Sending to {name} ({to}) at {company}...")

        if send_email(to, subject, body):
            mark_sent(email_data["id"])
            sent_count += 1
            print(f"    ✓ Sent!")
        else:
            print(f"    ✗ Failed")

        # Delay between emails to avoid being flagged
        if email_data != emails[-1]:
            delay = 30  # 30 seconds between emails
            print(f"    Waiting {delay}s before next email...")
            time.sleep(delay)

    print(f"\n✓ Sent {sent_count}/{len(emails)} emails.")


# ── Review Interface ─────────────────────────────────────────

def review_drafts():
    """Interactive CLI to review pending email drafts."""
    drafts = get_pending_drafts()

    if not drafts:
        print("No pending drafts to review.")
        return

    print(f"\n{'='*60}")
    print(f"  DRAFT REVIEW — {len(drafts)} email(s) pending")
    print(f"{'='*60}\n")

    approved_count = 0
    skipped_count = 0

    for i, draft in enumerate(drafts, 1):
        print(f"── Draft {i}/{len(drafts)} ──")
        print(f"  To:      {draft['contact_name']} ({draft['contact_email']})")
        print(f"  Company: {draft['company_name']}")
        print(f"  Title:   {draft.get('contact_title', 'N/A')}")
        print(f"  Subject: {draft['subject']}")
        print(f"\n{'-'*40}")
        print(draft["body"])
        print(f"{'-'*40}")

        if draft.get("personalization_note"):
            print(f"\n  💡 Personalization: {draft['personalization_note']}")

        print(f"\n  Word count: {len(draft['body'].split())}")
        print()

        while True:
            action = input(
                "  [A]pprove / [S]kip / [Q]uit review? ").strip().lower()
            if action in ("a", "approve"):
                approve_draft(draft["id"])
                approved_count += 1
                print("  ✓ Approved!\n")
                break
            elif action in ("s", "skip"):
                skipped_count += 1
                print("  → Skipped\n")
                break
            elif action in ("q", "quit"):
                print(
                    f"\n✓ Review ended. Approved: {approved_count}, Skipped: {skipped_count}")
                return
            else:
                print("  Please enter A, S, or Q.")

    print(
        f"\n✓ Review complete. Approved: {approved_count}, Skipped: {skipped_count}")

    if approved_count > 0:
        send_now = input("\nSend approved emails now? [y/N] ").strip().lower()
        if send_now in ("y", "yes"):
            send_approved_emails()
