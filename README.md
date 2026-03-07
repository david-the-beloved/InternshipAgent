# Internship Outreach Automation Pipeline

An end-to-end automation system that researches companies, finds engineering contacts, verifies emails, generates personalized cold emails via Gemini AI, and saves them as Gmail drafts for review — all orchestrated through an n8n workflow.

Built to automate my SIWES internship outreach to Nigerian tech companies.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      n8n Workflow (Orchestrator)                │
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐  │
│  │  Manual   │──▶│Get Next  │──▶│  Run     │──▶│  Emails    │  │
│  │  Trigger  │   │ Company  │   │ Research │   │  Found?    │  │
│  └──────────┘   └──────────┘   └──────────┘   └─────┬──────┘  │
│                       ▲                          Yes │  │ No   │
│                       │                              ▼  ▼      │
│                       │    ┌──────────┐   ┌──────────────┐     │
│                       │◀───│ Wait 10s │◀──│Mark Researched│    │
│                       │    └──────────┘   └──────────────┘     │
│                       │                                        │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐  │
│  │ Schedule │──▶│  Check   │──▶│  Parse   │──▶│Save Gmail │  │
│  │ (10 min) │   │  Drafts  │   │  Emails  │   │  Draft    │  │
│  └──────────┘   └──────────┘   └──────────┘   └───────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    pipeline.py (Engine)                         │
│                                                                 │
│  Stage 1: Research          Stage 2: Email Finding              │
│  ┌─────────────────┐       ┌──────────────────────┐           │
│  │ DuckDuckGo      │       │ Pattern guessing     │           │
│  │ LinkedIn search  │       │ (first@, first.last@)│           │
│  │ Name extraction  │       │ Abstract API verify  │           │
│  │ Hook gathering   │       │ Dedup & filter       │           │
│  └─────────────────┘       └──────────────────────┘           │
│                                                                 │
│  Stage 3: Prompt Generation                                    │
│  ┌─────────────────────────────────────────────┐              │
│  │ Builds structured prompt with:               │              │
│  │ - Applicant profile & projects               │              │
│  │ - Company context & target teams             │              │
│  │ - Prospect details & personalization hooks   │              │
│  │ → Copy into Gemini → Paste reply back        │              │
│  └─────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

1. **Research** — DuckDuckGo searches find engineering leads at each target company via LinkedIn. Extracts names, titles, and personalization hooks (blog posts, talks, open-source work).

2. **Email Finding** — Guesses email patterns (`first@domain`, `first.last@domain`) and verifies them via Abstract API's Email Reputation endpoint. Filters out undeliverable addresses and deduplicates.

3. **Prompt Generation** — Builds a structured prompt combining your profile, the company context, and prospect details. Designed for Gemini Pro to generate personalized cold emails.

4. **Human-in-the-Loop** — You paste the prompt into Gemini, review the output, and save it. The pipeline parses the `---EMAIL---` blocks from Gemini's reply.

5. **Gmail Drafts** — n8n's scheduled flow picks up parsed emails and saves them as Gmail drafts via OAuth2. You review each draft in Gmail before hitting send.

## Tech Stack

| Component              | Technology                                |
| ---------------------- | ----------------------------------------- |
| Pipeline Engine        | Python 3.13                               |
| Workflow Orchestration | n8n (self-hosted)                         |
| Web Research           | DuckDuckGo Search API                     |
| Email Verification     | Abstract API (Email Reputation)           |
| Email Delivery         | Gmail API (OAuth2, draft creation)        |
| AI Generation          | Google Gemini Pro (via manual copy-paste) |
| HTTP Client            | httpx                                     |
| HTML Parsing           | BeautifulSoup4                            |

## Safety Features

- **Spam prevention**: 18 emails/day hard limit, 30s delay between sends, duplicate recipient detection
- **CAN-SPAM compliance**: Opt-out line in every email, no misleading headers
- **Name-collision filtering**: Rejects prospects whose name matches the company name (false positives)
- **Rate limit handling**: Auto-switches between multiple API keys when quota is exhausted
- **Human review**: Emails are saved as Gmail drafts, not sent automatically

## Project Structure

```
├── pipeline.py                  # Core engine (~1300 lines)
├── n8n_workflow.json            # n8n workflow (import into n8n)
├── start_n8n.ps1               # n8n launcher with required env vars
├── requirements.txt             # Python dependencies
├── knowledge/
│   ├── target_companies.json    # Company targets with context
│   ├── my_profile.json          # Applicant profile for prompts
│   ├── outreach_strategy.txt    # Cold email strategy guide
│   ├── cold_email_examples.txt  # Reference examples
│   ├── email_anti_patterns.txt  # What to avoid
│   └── can_spam_rules.txt       # Legal compliance reference
├── drafts/                      # Generated prompts & email drafts (gitignored)
├── progress.json                # Pipeline state tracking (gitignored)
└── send_log.json                # Send history & dedup log (gitignored)
```

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for n8n)
- Gmail account with 2FA enabled
- Abstract API key ([free tier: 100/month](https://app.abstractapi.com/))

### Installation

```bash
# Clone
git clone https://github.com/david-the-beloved/InternshipAgent.git
cd InternshipAgent

# Python environment
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Environment variables
cp .env.example .env
# Fill in your API keys and Gmail App Password
```

### n8n Setup

```powershell
# Option 1: Use the launcher script
.\start_n8n.ps1

# Option 2: Manual
$env:NODE_FUNCTION_ALLOW_BUILTIN = "fs,path,child_process"
$env:N8N_RUNNERS_TASK_TIMEOUT = "600"
npx n8n
```

Then import `n8n_workflow.json` into n8n at `http://localhost:5678`.

### Gmail OAuth2 (for draft creation)

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (Web application)
4. Set redirect URI: `http://localhost:5678/rest/oauth2-credential/callback`
5. In n8n, add a Gmail OAuth2 credential with your Client ID & Secret

## Usage

### CLI

```bash
# Research a single company
python pipeline.py research --company "Kuda"

# Send emails for a company (after pasting Gemini output)
python pipeline.py send --company "Kuda"

# Dry run (preview without sending)
python pipeline.py send --company "Kuda" --dry-run
```

### n8n Workflow

1. **Click "Execute Workflow"** — auto-loops through all companies, researching each one
2. **Copy each `drafts/{company}_prompt.txt`** → paste into Gemini Pro → save reply to `drafts/{company}_drafts.txt`
3. **The scheduled flow** (every 10 min) picks up drafts and creates Gmail drafts automatically

## Author

**David Ihegaranya**

- GitHub: [@david-the-beloved](https://github.com/david-the-beloved)
- LinkedIn: [david-ihegaranya](https://linkedin.com/in/david-ihegaranya)
