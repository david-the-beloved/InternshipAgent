"""
Pydantic models for structured data flowing through the agent pipeline.
These are used as CrewAI task output schemas and for internal data passing.
"""

from pydantic import BaseModel, Field


# ── Research Stage ───────────────────────────────────────────

class Prospect(BaseModel):
    """A single person discovered during research."""
    name: str = Field(description="Full name of the person")
    title: str = Field(description="Current job title")
    company: str = Field(description="Company they work at")
    linkedin_url: str = Field(default="", description="LinkedIn profile URL")
    personalization_hooks: list[str] = Field(
        description="2-3 specific, personal details that can be referenced in an email "
                    "(e.g., a recent talk, open-source project, blog post, shared interest)"
    )
    research_notes: str = Field(
        default="",
        description="Additional context gathered about this person",
    )


class ProspectList(BaseModel):
    """Output of the Research task — a list of prospects for a target company."""
    company: str = Field(description="The company that was researched")
    prospects: list[Prospect] = Field(
        description="List of 3-5 relevant people found at the company"
    )


# ── Email Finding Stage ──────────────────────────────────────

class EnrichedProspect(BaseModel):
    """A prospect enriched with a verified email address."""
    name: str = Field(description="Full name of the person")
    title: str = Field(description="Current job title")
    company: str = Field(description="Company they work at")
    linkedin_url: str = Field(default="", description="LinkedIn profile URL")
    personalization_hooks: list[str] = Field(
        description="Personalization hooks from research"
    )
    research_notes: str = Field(default="", description="Research notes")
    email: str = Field(description="Verified professional email address")
    email_confidence: float = Field(
        default=0.0,
        description="Confidence score for the email (0-100)",
    )
    email_source: str = Field(
        default="",
        description="Where the email was found (e.g., 'apollo', 'hunter')",
    )


class EnrichedProspectList(BaseModel):
    """Output of the Email Finding task — prospects with resolved emails."""
    company: str = Field(description="The company that was researched")
    prospects: list[EnrichedProspect] = Field(
        description="Prospects with verified email addresses (only those where an email was found)"
    )


# ── Email Drafting Stage ─────────────────────────────────────

class EmailDraft(BaseModel):
    """A personalized email draft ready for review."""
    to_name: str = Field(description="Recipient's full name")
    to_email: str = Field(description="Recipient's email address")
    company: str = Field(description="Recipient's company")
    subject: str = Field(
        description="Email subject line — specific and non-generic")
    body: str = Field(
        description="Email body — under 150 words, personalized, with CAN-SPAM footer"
    )
    personalization_note: str = Field(
        description="Internal note explaining which personalization hook was used and why "
                    "(not included in the email, just for your review)"
    )


class EmailDraftList(BaseModel):
    """Output of the Email Writing task — drafts for all enriched prospects."""
    company: str = Field(description="The company these drafts target")
    drafts: list[EmailDraft] = Field(description="Personalized email drafts")
