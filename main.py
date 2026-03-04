"""
Main CLI entry point for the Internship Outreach Agent.

Usage:
    python main.py run --company "Anthropic"           # Full pipeline with review
    python main.py run --company "Anthropic" --auto    # Full pipeline, skip review
    python main.py train --company "Anthropic"         # Training mode (human feedback loop)
    python main.py review                              # Review pending drafts
    python main.py send                                # Send approved emails
    python main.py status                              # Show pipeline stats
"""

from sender.mailer import review_drafts, send_approved_emails
from db.database import (
    add_company,
    add_contact,
    get_pipeline_stats,
    save_draft,
    update_contact_email,
)
from crew import run_crew, train_crew
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables before anything else
load_dotenv(Path(__file__).parent / ".env")


def cmd_run(args):
    """Run the full outreach pipeline for a company."""
    company = args.company
    role = args.role
    auto = args.auto

    print(f"\n{'='*60}")
    print(f"  INTERNSHIP OUTREACH AGENT")
    print(f"  Company: {company}")
    print(f"  Role:    {role}")
    print(f"  Mode:    {'Autonomous' if auto else 'Human-in-the-loop'}")
    print(f"{'='*60}\n")

    # Add company to database
    company_id = add_company(company)

    # Run the crew
    print("Starting agent pipeline...\n")
    result = run_crew(company, role, human_input=not auto)

    # Save results to database
    drafts = result.get("drafts", {})
    if isinstance(drafts, dict) and "drafts" in drafts:
        draft_list = drafts["drafts"]
    elif isinstance(drafts, list):
        draft_list = drafts
    else:
        draft_list = []

    saved = 0
    for draft in draft_list:
        if isinstance(draft, dict):
            # Save contact
            contact_id = add_contact(
                company_id=company_id,
                name=draft.get("to_name", "Unknown"),
                title="",
                linkedin_url="",
                personalization_hooks=[draft.get("personalization_note", "")],
            )

            if draft.get("to_email"):
                update_contact_email(
                    contact_id, draft["to_email"], 90, "pipeline")

            # Save draft
            save_draft(
                contact_id=contact_id,
                subject=draft.get("subject", ""),
                body=draft.get("body", ""),
                personalization_note=draft.get("personalization_note", ""),
            )
            saved += 1

    print(f"\n✓ Pipeline complete! {saved} draft(s) saved to database.")

    if not auto and saved > 0:
        print("\nStarting draft review...\n")
        review_drafts()


def cmd_train(args):
    """Run the crew in training mode."""
    company = args.company
    role = args.role
    iterations = args.iterations

    print(f"\n{'='*60}")
    print(f"  TRAINING MODE")
    print(f"  Company:    {company}")
    print(f"  Role:       {role}")
    print(f"  Iterations: {iterations}")
    print(f"{'='*60}\n")
    print("You'll review each agent's output and provide feedback.")
    print("Your feedback will be saved and used to improve future runs.\n")

    train_crew(company, role, n_iterations=iterations)


def cmd_review(args):
    """Review pending email drafts."""
    review_drafts()


def cmd_send(args):
    """Send all approved emails."""
    send_approved_emails()


def cmd_status(args):
    """Show pipeline statistics."""
    stats = get_pipeline_stats()

    print(f"\n{'='*60}")
    print(f"  PIPELINE STATUS")
    print(f"{'='*60}\n")
    print(f"  Companies tracked:    {stats.get('total_companies', 0)}")
    print(f"  ─────────────────────────────────")
    print(f"  Contacts researched:  {stats.get('researched', 0)}")
    print(f"  Emails found:         {stats.get('email_found', 0)}")
    print(f"  Drafts pending:       {stats.get('pending_drafts', 0)}")
    print(f"  Drafts approved:      {stats.get('approved_unsent', 0)}")
    print(f"  Emails sent:          {stats.get('total_sent', 0)}")
    print(f"  Replies received:     {stats.get('replied', 0)}")
    print(f"  Opted out:            {stats.get('opted_out', 0)}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="AI-powered internship outreach agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py run --company "Anthropic"
  python main.py run --company "OpenAI" --role "ML Engineer" --auto
  python main.py train --company "Google" --iterations 3
  python main.py review
  python main.py send
  python main.py status
        """,
    )

    subparsers = parser.add_subparsers(
        dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser(
        "run", help="Run the full outreach pipeline")
    run_parser.add_argument(
        "--company", "-c", required=True, help="Target company name")
    run_parser.add_argument("--role", "-r", default="Software Engineer",
                            help="Target role (default: Software Engineer)")
    run_parser.add_argument("--auto", action="store_true",
                            help="Autonomous mode — skip human review")
    run_parser.set_defaults(func=cmd_run)

    # Train command
    train_parser = subparsers.add_parser(
        "train", help="Training mode — improve agents with feedback")
    train_parser.add_argument(
        "--company", "-c", required=True, help="Company to train on")
    train_parser.add_argument(
        "--role", "-r", default="Software Engineer", help="Target role")
    train_parser.add_argument("--iterations", "-n", type=int,
                              default=2, help="Training iterations (default: 2)")
    train_parser.set_defaults(func=cmd_train)

    # Review command
    review_parser = subparsers.add_parser(
        "review", help="Review pending email drafts")
    review_parser.set_defaults(func=cmd_review)

    # Send command
    send_parser = subparsers.add_parser("send", help="Send approved emails")
    send_parser.set_defaults(func=cmd_send)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show pipeline stats")
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
