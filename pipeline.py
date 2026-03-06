"""
pipeline.py — Lean outreach automation (NO LLM API needed).

Flow:
  1. `python pipeline.py research --company Busha`
     → Searches DuckDuckGo for prospects, finds emails via Hunter.io
     → Generates a ready-to-paste Gemini Pro prompt → saves to drafts/

  2. YOU copy the prompt from `drafts/busha_prompt.txt`
     → Paste into Gemini Pro (gemini.google.com)
     → Copy Gemini's reply
     → Paste into `drafts/busha_drafts.txt`

  3. `python pipeline.py send --company Busha`
     → Parses drafts from the txt file
     → Sends each email via Gmail SMTP

Commands:
    python pipeline.py research --company Busha       # Stage 1+2: research + prompt
    python pipeline.py research --all                 # Research all target companies
    python pipeline.py send --company Busha           # Stage 3: parse drafts + send
    python pipeline.py send --company Busha --dry-run # Preview without sending
"""

import json
import os
import re
import ssl
import time
from pathlib import Path

import httpx
from ddgs import DDGS
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Fix SSL on Python 3.13 + Windows
_ssl_ctx = ssl.create_default_context()
_OrigClient = httpx.Client
_OrigAsyncClient = httpx.AsyncClient


class _PatchedClient(_OrigClient):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("verify", _ssl_ctx)
        super().__init__(*args, **kwargs)


class _PatchedAsyncClient(_OrigAsyncClient):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("verify", _ssl_ctx)
        super().__init__(*args, **kwargs)


httpx.Client = _PatchedClient
httpx.AsyncClient = _PatchedAsyncClient

ROOT = Path(__file__).parent
KNOWLEDGE_DIR = ROOT / "knowledge"

# ── Config ────────────────────────────────────────────────────

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
ABSTRACT_API_KEY = os.getenv("ABSTRACT_API_KEY", "")
SEARCH_DELAY = 8  # seconds between DuckDuckGo searches
HUNTER_BASE = "https://api.hunter.io/v2"
PROGRESS_FILE = ROOT / "progress.json"
MAX_EMAILS_PER_DAY = 18  # Gmail safe limit (official is ~20, leave headroom)
SEND_LOG_FILE = ROOT / "send_log.json"  # tracks daily sends + all recipients


# ── Progress Tracking ─────────────────────────────────────────

def load_progress() -> dict:
    """Load progress tracker. Tracks which companies are done."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "researched": [], "current": None}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def mark_researched(company_name: str):
    """Mark a company as researched (prompt generated, waiting for drafts)."""
    prog = load_progress()
    if company_name not in prog["researched"]:
        prog["researched"].append(company_name)
    prog["current"] = company_name
    save_progress(prog)


def mark_completed(company_name: str):
    """Mark a company as fully done (emails sent)."""
    prog = load_progress()
    if company_name not in prog["completed"]:
        prog["completed"].append(company_name)
    if company_name in prog["researched"]:
        prog["researched"].remove(company_name)
    prog["current"] = None
    save_progress(prog)


# ── Send Log (daily limit + duplicate tracking) ──────────────

def load_send_log() -> dict:
    """Load send log tracking daily counts and all-time recipients."""
    if SEND_LOG_FILE.exists():
        try:
            with open(SEND_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"today": _today_str(), "sent_today": 0, "all_recipients": []}


def _today_str() -> str:
    return time.strftime("%Y-%m-%d")


def save_send_log(log: dict):
    with open(SEND_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def record_send(email: str):
    """Record an email send. Resets daily counter if day changed."""
    log = load_send_log()
    today = _today_str()
    if log.get("today") != today:
        log["today"] = today
        log["sent_today"] = 0
    log["sent_today"] += 1
    if email.lower() not in [e.lower() for e in log.get("all_recipients", [])]:
        log.setdefault("all_recipients", []).append(email.lower())
    save_send_log(log)


def can_send_today() -> tuple[bool, int]:
    """Check if we can send more emails today. Returns (allowed, remaining)."""
    log = load_send_log()
    today = _today_str()
    if log.get("today") != today:
        return True, MAX_EMAILS_PER_DAY
    remaining = MAX_EMAILS_PER_DAY - log.get("sent_today", 0)
    return remaining > 0, max(0, remaining)


def is_duplicate_recipient(email: str) -> bool:
    """Check if we've already emailed this address."""
    log = load_send_log()
    return email.lower() in [e.lower() for e in log.get("all_recipients", [])]


def get_next_company() -> dict | None:
    """Get the next company that hasn't been completed yet."""
    prog = load_progress()
    companies = load_companies()
    for c in companies:
        if c["name"] not in prog["completed"]:
            return c
    return None


def show_status():
    """Print the current progress status."""
    prog = load_progress()
    companies = load_companies()
    total = len(companies)
    done = len(prog["completed"])
    pending = [c["name"]
               for c in companies if c["name"] not in prog["completed"]]

    print(f"\n{'='*60}")
    print(f"  OUTREACH PROGRESS: {done}/{total} companies done")
    print(f"{'='*60}")
    print(f"\n  ✓ Completed ({done}):")
    for name in prog["completed"]:
        print(f"    - {name}")
    if prog.get("researched"):
        print(f"\n  ⏳ Researched (waiting for drafts):")
        for name in prog["researched"]:
            slug = name.lower().replace(' ', '_')
            print(
                f"    - {name}  →  paste drafts into drafts/{slug}_drafts.txt")
    if pending:
        print(f"\n  ⬜ Pending ({len(pending)}):")
        for name in pending[:10]:
            print(f"    - {name}")
        if len(pending) > 10:
            print(f"    ... and {len(pending)-10} more")
    if prog.get("current"):
        print(f"\n  Current: {prog['current']}")
    print()


# ── Load Knowledge ────────────────────────────────────────────

def load_profile() -> dict:
    """Load applicant profile."""
    path = KNOWLEDGE_DIR / "my_profile.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_companies() -> list[dict]:
    """Load all target companies."""
    path = KNOWLEDGE_DIR / "target_companies.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("companies", [])


def get_company(name: str) -> dict | None:
    """Get a specific company by name (case-insensitive)."""
    for c in load_companies():
        if c["name"].lower() == name.lower():
            return c
    return None


# ── Stage 1: Research (DuckDuckGo — no LLM needed) ───────────

def search_ddg(query: str, max_results: int = 8) -> list[dict]:
    """Search DuckDuckGo with rate limiting. Returns list of {title, url, snippet}."""
    for attempt in range(2):
        if attempt == 0:
            time.sleep(SEARCH_DELAY)
        else:
            time.sleep(60)

        try:
            results = DDGS().text(query, max_results=max_results)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("link", "")),
                    "snippet": r.get("body", r.get("snippet", "")),
                }
                for r in (results or [])
            ]
        except Exception as e:
            err_str = str(e).lower()
            if ("ratelimit" in err_str or "429" in err_str) and attempt == 0:
                print("  [search] Rate limited — waiting 60s then retrying once...")
                continue
            print(f"  [search] Error: {e}")
            return []

    return []


def extract_linkedin_names(results: list[dict], company: str = "") -> list[dict]:
    """Extract names and titles from LinkedIn search results.

    Filters out prospects whose name matches the company name
    unless their LinkedIn title confirms they actually work there.
    """
    prospects = []
    seen_names = set()
    company_lower = company.lower().strip()
    # Words from the company name used for collision detection
    company_words = {w for w in company_lower.split() if len(w) > 2}

    for r in results:
        url = r.get("url", "")
        title = r.get("title", "")
        snippet = r.get("snippet", "")

        # Skip non-LinkedIn or non-person results
        if "linkedin.com/in/" not in url.lower():
            continue

        # Parse "First Last - Title at Company | LinkedIn" pattern
        match = re.match(
            r"^(.+?)\s*[-–—]\s*(.+?)(?:\s*\|\s*LinkedIn)?$", title)
        if not match:
            continue

        name = match.group(1).strip()
        title_role = match.group(2).strip()

        # Skip if already seen or if it's a company page
        if name.lower() in seen_names or len(name.split()) < 2:
            continue

        # Name-collision filter: if any part of the person's name matches
        # a word in the company name, their title MUST mention the company.
        name_parts = {w.lower() for w in name.split()}
        if company_words and (company_words & name_parts):
            if company_lower not in title_role.lower():
                print(f"    Skipping '{name}' -- name overlaps company name "
                      f"and title ('{title_role}') doesn't confirm employment")
                continue

        seen_names.add(name.lower())

        prospects.append({
            "name": name,
            "title": title_role,
            "linkedin_url": url,
            "snippet": snippet,
            "personalization_hooks": [],
            "research_notes": "",
        })

    return prospects


def research_person(name: str, company: str) -> list[str]:
    """Search for personalization hooks for a specific person."""
    hooks = []

    # Search for blog posts, talks, GitHub
    queries = [
        f'"{name}" blog OR talk OR github OR conference',
        f'"{name}" {company} engineering OR developer',
    ]

    for q in queries:
        results = search_ddg(q, max_results=5)
        for r in results:
            snippet = r.get("snippet", "")
            url = r.get("url", "")
            title = r.get("title", "")

            # Filter out noise
            if not snippet or "linkedin.com" in url.lower():
                continue

            # Create a hook from the finding
            hook = f"{title} — {snippet[:150]}"
            if hook not in hooks:
                hooks.append(hook)

    return hooks[:3]  # Top 3 hooks per person


def scrape_page_text(url: str, max_chars: int = 2000) -> str:
    """Lightweight scrape of a URL for text content."""
    if "linkedin.com" in url.lower():
        return ""
    try:
        from bs4 import BeautifulSoup
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        }
        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.find("body")
        text = main.get_text(separator=" ", strip=True) if main else ""
        return text[:max_chars]
    except Exception:
        return ""


def research_prospects(company: str, role: str = "Software Engineer", max_prospects: int = 5) -> list[dict]:
    """
    Stage 1: Find prospects at a company using DuckDuckGo.

    Returns list of prospect dicts with name, title, LinkedIn URL,
    personalization hooks, and research notes.
    """
    company_data = get_company(company)
    domain = company_data["domain"] if company_data else f"{company.lower()}.com"

    print(f"\n{'='*60}")
    print(f"  STAGE 1: Researching {company} for {role} prospects")
    print(f"{'='*60}")

    # Search LinkedIn for people
    print(f"\n  [1/3] Searching LinkedIn for {role}s at {company}...")
    linkedin_results = search_ddg(
        f'site:linkedin.com/in/ "{company}" "{role}"', max_results=10
    )
    prospects = extract_linkedin_names(linkedin_results, company)

    # Also try broader engineering search
    if len(prospects) < 3:
        print(f"  [1/3] Broadening search to engineering roles...")
        more = search_ddg(
            f'site:linkedin.com/in/ "{company}" engineer OR developer', max_results=10
        )
        for p in extract_linkedin_names(more, company):
            if p["name"].lower() not in {x["name"].lower() for x in prospects}:
                prospects.append(p)

    prospects = prospects[:max_prospects]
    print(f"  [1/3] Found {len(prospects)} prospects")

    # Research each person for personalization hooks
    print(f"\n  [2/3] Researching personalization hooks...")
    for i, p in enumerate(prospects):
        print(f"    ({i+1}/{len(prospects)}) {p['name']}...")
        hooks = research_person(p["name"], company)
        p["personalization_hooks"] = hooks
        p["research_notes"] = f"Found via LinkedIn search for {role} at {company}"
        if hooks:
            print(f"      Found {len(hooks)} hooks")
        else:
            # Use LinkedIn snippet as fallback hook
            if p.get("snippet"):
                p["personalization_hooks"] = [p["snippet"][:200]]
                print(f"      Using LinkedIn snippet as hook")
            else:
                print(f"      No hooks found")

    # Filter out prospects with zero hooks
    prospects = [p for p in prospects if p.get("personalization_hooks")]

    print(f"\n  [3/3] Final prospect count: {len(prospects)}")
    for p in prospects:
        print(f"    - {p['name']} ({p['title']})")
        for h in p["personalization_hooks"]:
            print(f"      Hook: {h[:80]}...")

    return prospects


# ── Stage 2: Email Finding (Hunter.io — no LLM needed) ───────

def hunter_find_email(first_name: str, last_name: str, domain: str) -> dict | None:
    """Call Hunter.io email-finder API. Returns {email, confidence, source} or None."""
    if not HUNTER_API_KEY or HUNTER_API_KEY == "your-hunter-api-key-here":
        print(f"    [hunter] ⚠ API key not configured")
        return None

    try:
        resp = httpx.get(
            f"{HUNTER_BASE}/email-finder",
            params={
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": HUNTER_API_KEY,
            },
            timeout=30,
        )
        if resp.status_code == 429:
            print(f"    [hunter] ⚠ Rate limit hit")
            return None
        if resp.status_code != 200:
            print(f"    [hunter] ⚠ HTTP {resp.status_code}")
            return None

        data = resp.json().get("data", {})
        email = data.get("email")
        confidence = data.get("score", 0)
        if email:
            return {"email": email, "confidence": confidence, "source": "hunter"}
        return None
    except Exception as e:
        print(f"    [hunter] ⚠ Error: {e}")
        return None


def hunter_verify_email(email: str) -> dict:
    """
    Call Hunter.io email-verifier API.

    Returns {status, score, result} where:
      status: 'valid', 'invalid', 'accept_all', 'webmail', 'disposable', 'unknown'
      score: 0-100
      result: 'deliverable', 'undeliverable', 'risky', 'unknown'
    """
    if not HUNTER_API_KEY or HUNTER_API_KEY == "your-hunter-api-key-here":
        return {"status": "unknown", "score": 0, "result": "unknown"}

    try:
        resp = httpx.get(
            f"{HUNTER_BASE}/email-verifier",
            params={"email": email, "api_key": HUNTER_API_KEY},
            timeout=30,
        )
        if resp.status_code == 429:
            print(f"    [verify] ⚠ Rate limit hit")
            return {"status": "unknown", "score": 0, "result": "unknown"}
        if resp.status_code != 200:
            print(f"    [verify] ⚠ HTTP {resp.status_code}")
            return {"status": "unknown", "score": 0, "result": "unknown"}

        data = resp.json().get("data", {})
        return {
            "status": data.get("status", "unknown"),
            "score": data.get("score", 0),
            "result": data.get("result", "unknown"),
        }
    except Exception as e:
        print(f"    [verify] ⚠ Error: {e}")
        return {"status": "unknown", "score": 0, "result": "unknown"}


def abstract_verify_email(email: str) -> dict:
    """Fallback email verifier using Abstract API (100 free/month)."""
    if not ABSTRACT_API_KEY or ABSTRACT_API_KEY == "your-abstract-api-key-here":
        print(f"    [abstract] ⚠ API key not configured")
        return {"status": "unknown", "score": 0, "result": "unknown"}

    try:
        resp = httpx.get(
            "https://emailvalidation.abstractapi.com/v1/",
            params={"api_key": ABSTRACT_API_KEY, "email": email},
            timeout=30,
        )
        if resp.status_code == 429:
            print(f"    [abstract] ⚠ Rate limit hit")
            return {"status": "unknown", "score": 0, "result": "unknown"}
        if resp.status_code != 200:
            print(f"    [abstract] ⚠ HTTP {resp.status_code}")
            return {"status": "unknown", "score": 0, "result": "unknown"}

        data = resp.json()
        deliverability = data.get("deliverability", "UNKNOWN")
        is_smtp_valid = data.get("is_smtp_valid", {}).get("value", False)
        quality_score = float(data.get("quality_score", 0) or 0)

        result_map = {
            "DELIVERABLE": "deliverable",
            "UNDELIVERABLE": "undeliverable",
            "UNKNOWN": "risky" if is_smtp_valid else "unknown",
        }
        status_map = {
            "DELIVERABLE": "valid",
            "UNDELIVERABLE": "invalid",
            "UNKNOWN": "unknown",
        }

        return {
            "status": status_map.get(deliverability, "unknown"),
            "score": int(quality_score * 100) if quality_score <= 1 else int(quality_score),
            "result": result_map.get(deliverability, "unknown"),
        }
    except Exception as e:
        print(f"    [abstract] ⚠ Error: {e}")
        return {"status": "unknown", "score": 0, "result": "unknown"}


def verify_email(email: str) -> dict:
    """Try Hunter.io first, fall back to Abstract API if rate-limited."""
    result = hunter_verify_email(email)
    if result["result"] != "unknown" or result["score"] > 0:
        return result
    # Hunter returned unknown (likely rate-limited) — try Abstract
    if ABSTRACT_API_KEY:
        print(f"    [fallback] Trying Abstract API...")
        return abstract_verify_email(email)
    return result


def find_emails(prospects: list[dict], domain: str) -> list[dict]:
    """
    Stage 2: Find emails for all prospects via Hunter.io.
    Verifies ALL emails (found + guessed) before including them.

    Returns enriched prospect dicts (only those with deliverable emails).
    """
    print(f"\n{'='*60}")
    print(
        f"  STAGE 2: Finding emails for {len(prospects)} prospects at {domain}")
    print(f"{'='*60}")

    candidates = []
    for p in prospects:
        name = p.get("name", "")
        parts = name.strip().split()
        if len(parts) < 2:
            print(f"\n  Skipping '{name}' — need first+last name")
            continue

        first_name, last_name = parts[0].strip(), parts[-1].strip()
        if not first_name or not last_name:
            print(f"\n  Skipping '{name}' — invalid name")
            continue
        print(f"\n  Looking up: {first_name} {last_name} @ {domain}")

        result = hunter_find_email(first_name, last_name, domain)
        if result:
            print(
                f"    ✓ Found: {result['email']} (confidence: {result['confidence']}%)")
            candidates.append({
                **p,
                "email": result["email"],
                "email_confidence": result["confidence"],
                "email_source": result["source"],
            })
        else:
            # Try common email patterns (two most common formats)
            patterns = [
                f"{first_name.lower()}@{domain}",
                f"{first_name.lower()}.{last_name.lower()}@{domain}",
            ]
            print(
                f"    ✗ Not found via finder. Will try patterns: {', '.join(patterns)}")
            candidates.append({
                **p,
                # placeholder, will be replaced by verification
                "email": patterns[0],
                "email_confidence": 0,
                "email_source": "pattern_guess",
                "_patterns_to_try": patterns,
            })

    # ── Verify all emails ──
    print(f"\n  {'─'*50}")
    print(f"  Verifying emails via Hunter.io...")
    print(f"  {'─'*50}")

    enriched = []
    for c in candidates:
        name = c.get("name", "")

        if c.get("_patterns_to_try"):
            # Try each pattern until one verifies
            patterns = c.pop("_patterns_to_try")
            found_valid = False
            for pat in patterns:
                print(f"\n    Verifying {pat} ({name})...")
                vr = verify_email(pat)
                status_icon = {
                    "deliverable": "✓", "risky": "⚠", "undeliverable": "✗"
                }.get(vr["result"], "?")
                print(
                    f"      {status_icon} {vr['result']} (score: {vr['score']}, status: {vr['status']})")

                if vr["result"] == "deliverable" or (vr["result"] == "risky" and vr["score"] >= 50):
                    c["email"] = pat
                    c["email_confidence"] = vr["score"]
                    c["email_source"] = f"pattern_verified ({vr['result']})"
                    c["verification"] = vr
                    enriched.append(c)
                    found_valid = True
                    print(f"      → Using this email")
                    break

            if not found_valid:
                print(f"    ✗ No valid email found for {name} — skipping")
        else:
            # Verify the Hunter-found email too
            email = c["email"]
            print(f"\n    Verifying {email} ({name})...")
            vr = verify_email(email)
            status_icon = {
                "deliverable": "✓", "risky": "⚠", "undeliverable": "✗"
            }.get(vr["result"], "?")
            print(
                f"      {status_icon} {vr['result']} (score: {vr['score']}, status: {vr['status']})")

            c["verification"] = vr
            if vr["result"] != "undeliverable":
                enriched.append(c)
            else:
                print(f"    ✗ Email undeliverable for {name} — skipping")

    print(f"\n  {'─'*50}")
    print(
        f"  Results: {len(enriched)}/{len(candidates)} prospects with verified emails")

    # ── Deduplicate emails: keep only the first prospect per address ──
    seen_emails = set()
    unique_enriched = []
    for e in enriched:
        addr = e["email"].lower()
        if addr in seen_emails:
            print(f"    ✗ Duplicate email {addr} for {e['name']} — skipping")
            continue
        seen_emails.add(addr)
        unique_enriched.append(e)
    enriched = unique_enriched

    for e in enriched:
        v = e.get('verification', {})
        print(
            f"    ✓ {e['name']}: {e['email']} ({v.get('result', '?')}, score {v.get('score', 0)})")

    skipped = len(candidates) - len(enriched)
    if skipped:
        print(
            f"    ✗ {skipped} prospect(s) dropped (undeliverable/invalid email)")

    return enriched


# ── Stage 3: Generate Gemini Prompt + Save ───────────────────

DRAFTS_DIR = ROOT / "drafts"


def generate_gemini_prompt(
    company_data: dict,
    enriched_prospects: list[dict],
    profile: dict,
) -> str:
    """Build a copy-paste prompt for Gemini Pro web UI."""
    company = company_data.get("name", "Unknown")
    why = company_data.get("why", "")
    notes = company_data.get("notes", "")

    prompt_parts = [
        "You are an expert cold email writer for internship outreach.",
        "Write short, personalized, genuine cold emails that reference specific details about each recipient.",
        "",
        "RULES:",
        "- Keep each email under 180 words",
        "- Reference a specific personalization hook about the recipient",
        "- Be genuine and enthusiastic, not salesy or generic",
        "- Ask for a 10-minute chat, not a job directly",
        "- End with: \"If you'd prefer not to receive messages like this, just let me know and I won't reach out again.\"",
        "- Sign off as the applicant below",
        "- Add my number,linkedIn link and github link at the bottom",
        "",
        "=== APPLICANT INFO ===",
        f"Name: {profile.get('name', '')}",
        f"Email: {profile.get('email', '')}",
        f"University: {profile.get('university', '')} ({profile.get('degree', '')}, graduating {profile.get('graduation_year', '')})",
        f"Skills: {', '.join(profile.get('skills', []))}",
        f"GitHub: {profile.get('links', {}).get('github', '')}",
        f"LinkedIn: {profile.get('links', {}).get('linkedin', '')}",
        f"Phone: {profile.get('links', {}).get('number', '')}",
        f"Looking for: {profile.get('looking_for', '')}",
        "",
        "Projects:",
    ]

    for proj in profile.get("projects", []):
        prompt_parts.append(f"  - {proj['name']}: {proj['description']}")

    prompt_parts.extend([
        "",
        f"=== TARGET COMPANY: {company} ===",
        f"Why this company: {why}",
        f"Notes: {notes}",
        "",
        "=== PROSPECTS (write one email per person) ===",
    ])

    for i, p in enumerate(enriched_prospects, 1):
        hooks_text = "\n".join(
            f"    - {h}" for h in p.get("personalization_hooks", []))
        prompt_parts.extend([
            "",
            f"--- Prospect {i} ---",
            f"  Name: {p.get('name', '')}",
            f"  Title: {p.get('title', '')}",
            f"  Email: {p.get('email', '')}",
            f"  LinkedIn: {p.get('linkedin_url', '')}",
            f"  Personalization hooks:",
            hooks_text,
        ])

    prompt_parts.extend([
        "",
        "=== OUTPUT FORMAT ===",
        "For EACH prospect, respond in EXACTLY this format (I will parse this programmatically):",
        "",
        "---EMAIL---",
        "TO: recipient@email.com",
        "NAME: Recipient Name",
        "SUBJECT: Your subject line here",
        "BODY:",
        "The email body goes here.",
        "Multiple lines are fine.",
        "---END---",
        "",
        "Write one ---EMAIL--- block per prospect. Do NOT add any other text outside the blocks.",
    ])

    return "\n".join(prompt_parts)


def save_prompt(company_name: str, prompt: str, enriched: list[dict]) -> Path:
    """Save the Gemini prompt and create an empty drafts file."""
    DRAFTS_DIR.mkdir(exist_ok=True)
    slug = company_name.lower().replace(" ", "_")

    # Save the prompt
    prompt_path = DRAFTS_DIR / f"{slug}_prompt.txt"
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Create empty drafts file with instructions
    drafts_path = DRAFTS_DIR / f"{slug}_drafts.txt"
    if not drafts_path.exists():
        with open(drafts_path, "w", encoding="utf-8") as f:
            f.write(f"# Paste Gemini Pro's reply below this line.\n")
            f.write(f"# It should contain ---EMAIL--- blocks.\n")
            f.write(
                f"# Then run: python pipeline.py send --company {company_name}\n\n")

    # Save prospect data for the send step
    data_path = DRAFTS_DIR / f"{slug}_data.json"
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2)

    return prompt_path


# ── Draft Parser ──────────────────────────────────────────────

def parse_drafts(company_name: str) -> list[dict]:
    """
    Parse the drafts txt file for ---EMAIL--- blocks.

    Expected format:
        ---EMAIL---
        TO: person@company.com
        NAME: Person Name
        SUBJECT: Subject line
        BODY:
        Email body here...
        ---END---
    """
    slug = company_name.lower().replace(" ", "_")
    drafts_path = DRAFTS_DIR / f"{slug}_drafts.txt"

    if not drafts_path.exists():
        print(f"  ✗ File not found: {drafts_path}")
        print(
            f"    Run 'python pipeline.py research --company {company_name}' first.")
        return []

    content = drafts_path.read_text(encoding="utf-8")

    # Remove comment lines
    lines = [l for l in content.split("\n") if not l.strip().startswith("#")]
    content = "\n".join(lines)

    # Split on ---EMAIL--- markers
    blocks = re.split(r"---\s*EMAIL\s*---", content, flags=re.IGNORECASE)

    drafts = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Remove trailing ---END---
        block = re.sub(r"---\s*END\s*---.*", "", block,
                       flags=re.IGNORECASE | re.DOTALL).strip()

        # Parse fields
        to_match = re.search(r"^TO:\s*(.+)$", block,
                             re.MULTILINE | re.IGNORECASE)
        name_match = re.search(r"^NAME:\s*(.+)$", block,
                               re.MULTILINE | re.IGNORECASE)
        subject_match = re.search(
            r"^SUBJECT:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
        body_match = re.search(r"^BODY:\s*\n(.*)", block,
                               re.MULTILINE | re.IGNORECASE | re.DOTALL)

        if not subject_match or not body_match:
            print(f"  ⚠ Skipping malformed block (missing SUBJECT or BODY)")
            continue

        draft = {
            "to_email": to_match.group(1).strip() if to_match else "",
            "to_name": name_match.group(1).strip() if name_match else "",
            "subject": subject_match.group(1).strip(),
            "body": body_match.group(1).strip(),
        }

        # If no TO field, try to find email from data file
        if not draft["to_email"] and draft["to_name"]:
            draft["to_email"] = _lookup_email(company_name, draft["to_name"])

        drafts.append(draft)

    return drafts


def _lookup_email(company_name: str, name: str) -> str:
    """Look up a prospect's email from the saved data JSON."""
    slug = company_name.lower().replace(" ", "_")
    data_path = DRAFTS_DIR / f"{slug}_data.json"
    if not data_path.exists():
        return ""
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            prospects = json.load(f)
        for p in prospects:
            if p.get("name", "").lower() == name.lower():
                return p.get("email", "")
    except (json.JSONDecodeError, OSError):
        pass
    return ""


# ── Gmail Sender ──────────────────────────────────────────────

def _validate_email_format(email: str) -> bool:
    """Basic email format validation."""
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))


def send_gmail(to_email: str, subject: str, body: str) -> bool:
    """Send one email via Gmail SMTP with validation."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    # Validate email format
    if not _validate_email_format(to_email):
        print(f"  ✗ Invalid email format: {to_email}")
        return False

    # Check daily limit
    allowed, remaining = can_send_today()
    if not allowed:
        print(
            f"  ✗ Daily send limit reached ({MAX_EMAILS_PER_DAY}/day). Try again tomorrow.")
        return False

    # Check duplicate
    if is_duplicate_recipient(to_email):
        print(
            f"  ⚠ Already emailed {to_email} before — skipping to avoid spam")
        return False

    gmail_address = os.getenv("GMAIL_ADDRESS", "")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD", "")

    if not gmail_address or not gmail_password:
        print("  ✗ Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"David Ihegaranya <{gmail_address}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = gmail_address
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, to_email, msg.as_string())
        record_send(to_email)
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ✗ Gmail auth failed. Check your App Password.")
        return False
    except smtplib.SMTPRecipientsRefused:
        print(f"  ✗ Recipient rejected: {to_email}")
        return False
    except smtplib.SMTPException as e:
        print(f"  ✗ SMTP error: {e}")
        return False
    except OSError as e:
        print(f"  ✗ Network error: {e}")
        return False


def cmd_send(company_name: str, dry_run: bool = False):
    """Parse drafts file and send emails."""
    print(f"\n{'='*60}")
    print(f"  STAGE 3: Sending emails for {company_name}")
    print(f"{'='*60}")

    # Check if already sent
    slug = company_name.lower().replace(" ", "_")
    sent_path = DRAFTS_DIR / f"{slug}_drafts_sent.txt"
    if sent_path.exists():
        print(f"\n  ⚠ Emails for {company_name} were already sent.")
        print(f"    (file renamed to {sent_path.name})")
        print(f"    To re-send, rename it back to {slug}_drafts.txt")
        return

    # Check daily limit
    allowed, remaining = can_send_today()
    if not allowed:
        print(
            f"\n  ✗ Daily send limit reached ({MAX_EMAILS_PER_DAY}/day). Try again tomorrow.")
        return

    drafts = parse_drafts(company_name)
    if not drafts:
        print("\n  No valid email drafts found.")
        slug = company_name.lower().replace(" ", "_")
        print(f"  1. Open drafts/{slug}_prompt.txt")
        print(f"  2. Copy the entire prompt → paste into Gemini Pro")
        print(
            f"  3. Copy Gemini's reply → paste into drafts/{slug}_drafts.txt")
        print(f"  4. Run this command again")
        return

    print(f"\n  Found {len(drafts)} email draft(s):\n")

    for i, d in enumerate(drafts, 1):
        print(f"  {'─'*50}")
        print(f"  Draft {i}:")
        print(f"    To:      {d['to_name']} <{d['to_email']}>")
        print(f"    Subject: {d['subject']}")
        print(f"    Words:   {len(d['body'].split())}")
        print(f"    Preview: {d['body'][:120]}...")
        print()

    if dry_run:
        print("  [DRY RUN] No emails sent. Remove --dry-run to send for real.")
        return

    confirm = input(f"\n  Send {len(drafts)} email(s)? [y/N] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("  Cancelled.")
        return

    sent = 0
    for i, d in enumerate(drafts, 1):
        if not d["to_email"] or "@" not in d["to_email"]:
            print(f"\n  [{i}] ✗ Skipping {d['to_name']} — no valid email")
            continue

        print(f"\n  [{i}] Sending to {d['to_name']} <{d['to_email']}>...")
        if send_gmail(d["to_email"], d["subject"], d["body"]):
            print(f"  [{i}] ✓ Sent!")
            sent += 1
        else:
            print(f"  [{i}] ✗ Failed")

        # 30s delay between emails
        if i < len(drafts):
            print(f"  Waiting 30s before next email...")
            time.sleep(30)

    # Rename drafts file to prevent accidental re-sends
    slug = company_name.lower().replace(" ", "_")
    src = DRAFTS_DIR / f"{slug}_drafts.txt"
    dst = DRAFTS_DIR / f"{slug}_drafts_sent.txt"
    if src.exists():
        src.rename(dst)
        print(f"  Renamed {src.name} → {dst.name} (won't re-send)")

    # Mark company as completed
    if sent > 0:
        mark_completed(company_name)

    print(f"\n{'='*60}")
    print(f"  ✓ Done! Sent {sent}/{len(drafts)} emails.")
    allowed, remaining = can_send_today()
    print(f"  Daily send budget remaining: {remaining}/{MAX_EMAILS_PER_DAY}")
    print(f"{'='*60}")


# ── Main Pipeline ─────────────────────────────────────────────

def run_research(
    company_name: str,
    role: str = "Software Engineer",
) -> dict:
    """
    Run research + email finding + generate Gemini prompt.

    Returns the enriched prospect data.
    """
    company_data = get_company(company_name)
    if not company_data:
        print(f"⚠ Company '{company_name}' not found in target_companies.json")
        print(f"  Using defaults (domain: {company_name.lower()}.com)")
        company_data = {"name": company_name, "domain": f"{company_name.lower()}.com",
                        "why": "", "target_teams": [], "notes": ""}

    profile = load_profile()
    domain = company_data.get("domain", f"{company_name.lower()}.com")

    # Stage 1: Research
    prospects = research_prospects(company_name, role)

    if not prospects:
        print("\n⚠ No prospects found. Try a different company or role.")
        return {"error": "No prospects found"}

    # Stage 2: Find emails
    enriched = find_emails(prospects, domain)

    if not enriched:
        print(f"\n{'='*60}")
        print(f"  NO VALID EMAILS FOUND — skipping {company_name}")
        print(f"{'='*60}")
        mark_completed(company_name)
        return {"skip": True, "company": company_name, "reason": "no_valid_emails"}

    # Stage 3: Generate prompt
    print(f"\n{'='*60}")
    print(f"  STAGE 3: Generating Gemini prompt")
    print(f"{'='*60}")

    prompt = generate_gemini_prompt(company_data, enriched, profile)
    prompt_path = save_prompt(company_name, prompt, enriched)
    slug = company_name.lower().replace(" ", "_")

    print(f"\n  ✓ Prompt saved to: {prompt_path}")
    print(f"\n  NEXT STEPS:")
    print(f"  ┌──────────────────────────────────────────────────────┐")
    print(f"  │ 1. Open: drafts/{slug}_prompt.txt                   │")
    print(f"  │ 2. Copy ALL the text                                │")
    print(f"  │ 3. Paste into Gemini Pro (gemini.google.com)        │")
    print(f"  │ 4. Copy Gemini's entire reply                       │")
    print(f"  │ 5. Paste into: drafts/{slug}_drafts.txt             │")
    print(f"  │ 6. Run: python pipeline.py send -c {company_name:<14}│")
    print(f"  └──────────────────────────────────────────────────────┘")

    # Track progress
    mark_researched(company_name)

    return {"company": company_name, "prospects": enriched, "prompt_path": str(prompt_path)}


def cmd_loop(role: str = "Software Engineer", dry_run: bool = False):
    """
    Automated loop: research next company → wait for drafts → send → repeat.

    Flow per company:
      1. Research + generate prompt
      2. Open the prompt file for the user
      3. Wait for the user to paste drafts
      4. Parse + send
      5. Move to next company
    """
    companies = load_companies()
    prog = load_progress()
    total = len(companies)
    done = len(prog["completed"])

    print(f"\n{'#'*60}")
    print(f"  AUTOMATED OUTREACH LOOP")
    print(f"  {done}/{total} companies done — starting from next pending")
    print(f"{'#'*60}")

    while True:
        next_co = get_next_company()
        if not next_co:
            print(f"\n  ✓ ALL {total} companies completed! 🎉")
            show_status()
            return

        name = next_co["name"]
        slug = name.lower().replace(" ", "_")
        prog = load_progress()
        done = len(prog["completed"])

        print(f"\n{'#'*60}")
        print(f"  COMPANY {done+1}/{total}: {name}")
        print(f"{'#'*60}")

        # Check if already researched (just needs drafts + send)
        drafts_path = DRAFTS_DIR / f"{slug}_drafts.txt"
        prompt_path = DRAFTS_DIR / f"{slug}_prompt.txt"

        if name not in prog.get("researched", []):
            # Stage 1+2: Research
            result = run_research(name, role)
            if "error" in result:
                print(f"  Skipping {name} — no prospects found.")
                mark_completed(name)  # skip it
                continue
        else:
            print(f"  Already researched. Prompt at: drafts/{slug}_prompt.txt")

        # Wait for user to paste drafts
        print(f"\n  {'='*55}")
        print(f"  ACTION REQUIRED:")
        print(f"  1. Open: drafts/{slug}_prompt.txt")
        print(f"  2. Copy ALL text → paste into Gemini Pro")
        print(
            f"  3. Copy Gemini's reply → paste into drafts/{slug}_drafts.txt")
        print(f"  4. Save the file, then press ENTER here to continue")
        print(f"  {'='*55}")
        print(f"  (Type 'skip' to skip this company, 'quit' to stop)")

        user_input = input("\n  > ").strip().lower()
        if user_input == "quit":
            print("  Stopping loop. Run 'python pipeline.py loop' to resume.")
            return
        if user_input == "skip":
            print(f"  Skipping {name}.")
            mark_completed(name)
            continue

        # Stage 3: Parse + Send
        cmd_send(name, dry_run)

        # cmd_send already calls mark_completed internally
        prog = load_progress()
        remaining = total - len(prog["completed"])
        print(
            f"\n  📊 Progress: {len(prog['completed'])}/{total} done, {remaining} remaining")

        if remaining > 0:
            print(f"  Moving to next company in 5 seconds...")
            time.sleep(5)


# ── CLI ───────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Internship Outreach Pipeline (manual Gemini flow)")
    sub = parser.add_subparsers(dest="command")

    # research command
    res = sub.add_parser(
        "research", help="Research prospects + generate Gemini prompt")
    res.add_argument("--company", "-c", help="Company name")
    res.add_argument("--all", "-a", action="store_true",
                     help="All target companies")
    res.add_argument(
        "--role", "-r", default="Software Engineer", help="Target role")

    # send command
    snd = sub.add_parser("send", help="Parse Gemini drafts + send via Gmail")
    snd.add_argument("--company", "-c", required=True, help="Company name")
    snd.add_argument("--dry-run", action="store_true",
                     help="Preview only, don't send")

    # loop command — the main automation
    lp = sub.add_parser(
        "loop", help="Auto-loop: research → prompt → wait → send → next company")
    lp.add_argument(
        "--role", "-r", default="Software Engineer", help="Target role")
    lp.add_argument("--dry-run", action="store_true",
                    help="Preview emails without sending")

    # status command
    sub.add_parser("status", help="Show outreach progress")

    # reset command
    rst = sub.add_parser("reset", help="Reset progress for a company or all")
    rst.add_argument("--company", "-c", help="Company to reset (or --all)")
    rst.add_argument("--all", "-a", action="store_true",
                     help="Reset all progress")

    args = parser.parse_args()

    if args.command == "research":
        if args.all:
            companies = load_companies()
            prog = load_progress()
            pending = [c for c in companies if c["name"]
                       not in prog["completed"]]
            print(
                f"\n  Researching {len(pending)} pending companies (skipping {len(companies)-len(pending)} completed)...\n")
            for i, c in enumerate(pending, 1):
                print(f"\n{'#'*60}")
                print(f"  COMPANY {i}/{len(pending)}: {c['name']}")
                print(f"{'#'*60}")
                run_research(c["name"], args.role)
        elif args.company:
            run_research(args.company, args.role)
        else:
            res.print_help()

    elif args.command == "send":
        cmd_send(args.company, args.dry_run)

    elif args.command == "loop":
        cmd_loop(args.role, args.dry_run)

    elif args.command == "status":
        show_status()

    elif args.command == "reset":
        if args.all:
            if PROGRESS_FILE.exists():
                PROGRESS_FILE.unlink()
            print("  ✓ All progress reset.")
        elif args.company:
            prog = load_progress()
            prog["completed"] = [
                c for c in prog["completed"] if c != args.company]
            prog["researched"] = [
                c for c in prog["researched"] if c != args.company]
            save_progress(prog)
            print(f"  ✓ Reset progress for {args.company}.")
        else:
            rst.print_help()

    else:
        parser.print_help()
        print("\nWorkflow (manual):")
        print("  1. python pipeline.py research --company PiggyVest")
        print("  2. Copy drafts/piggyvest_prompt.txt → paste into Gemini Pro")
        print("  3. Paste Gemini reply → into drafts/piggyvest_drafts.txt")
        print("  4. python pipeline.py send --company PiggyVest")
        print("\nAutomated loop (recommended):")
        print("  python pipeline.py loop")
        print("  python pipeline.py status")


if __name__ == "__main__":
    main()
