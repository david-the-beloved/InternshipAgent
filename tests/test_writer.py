"""
Tests for the Writer Agent's output schemas and the database layer.
Run with: python -m pytest tests/test_writer.py -v
"""

import json
import os
import tempfile

import pytest
from pydantic import ValidationError

from agents.schemas import (
    EmailDraft,
    EmailDraftList,
    EnrichedProspect,
    EnrichedProspectList,
    Prospect,
    ProspectList,
)


class TestProspectSchema:
    """Test the Prospect Pydantic model."""

    def test_valid_prospect(self):
        p = Prospect(
            name="Jane Doe",
            title="Senior Software Engineer",
            company="Anthropic",
            linkedin_url="https://linkedin.com/in/janedoe",
            personalization_hooks=[
                "Gave a talk on 'Building Safe AI Systems' at NeurIPS 2025",
                "Maintains the open-source 'safety-gym' library on GitHub",
            ],
            research_notes="Very active in the AI safety community.",
        )
        assert p.name == "Jane Doe"
        assert len(p.personalization_hooks) == 2

    def test_prospect_requires_hooks(self):
        """Hooks list can be empty at schema level (guardrail catches this)."""
        p = Prospect(
            name="Jane Doe",
            title="Engineer",
            company="Test",
            personalization_hooks=[],
        )
        assert len(p.personalization_hooks) == 0


class TestEmailDraftSchema:
    """Test the EmailDraft Pydantic model."""

    def test_valid_draft(self):
        d = EmailDraft(
            to_name="Jane Doe",
            to_email="jane@anthropic.com",
            company="Anthropic",
            subject="Your NeurIPS talk on safe AI systems",
            body="Hi Jane, I loved your talk...",
            personalization_note="Used her NeurIPS talk as the hook because it's recent and specific.",
        )
        assert d.to_email == "jane@anthropic.com"
        assert "@" in d.to_email

    def test_draft_list(self):
        dl = EmailDraftList(
            company="Anthropic",
            drafts=[
                EmailDraft(
                    to_name="Jane Doe",
                    to_email="jane@example.com",
                    company="Anthropic",
                    subject="Test",
                    body="Hello",
                    personalization_note="Test hook",
                )
            ],
        )
        assert len(dl.drafts) == 1


class TestEnrichedProspectSchema:
    """Test the EnrichedProspect Pydantic model."""

    def test_valid_enriched(self):
        ep = EnrichedProspect(
            name="Jane Doe",
            title="Senior SWE",
            company="Anthropic",
            personalization_hooks=["NeurIPS talk"],
            email="jane@anthropic.com",
            email_confidence=92.0,
            email_source="apollo",
        )
        assert ep.email_confidence == 92.0
        assert ep.email_source == "apollo"
