"""
Apollo.io API Tools for CrewAI.
Uses Apollo's free-tier People Search and Enrichment endpoints to find emails.
Free tier: 10k records/month, limited export credits.
API docs: https://docs.apollo.io/
"""

import os
from typing import Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


APOLLO_BASE_URL = "https://api.apollo.io"


def _get_api_key() -> str:
    """Get Apollo API key from environment."""
    key = os.getenv("APOLLO_API_KEY", "")
    if not key or key == "your-apollo-api-key-here":
        return ""
    return key


class ApolloPersonSearchInput(BaseModel):
    """Input for Apollo person search."""
    person_name: str = Field(
        description="Full name of the person to search for")
    company_domain: str = Field(
        description="Company domain (e.g., 'anthropic.com')")


class ApolloPersonSearchTool(BaseTool):
    name: str = "Apollo People Search"
    description: str = (
        "Search Apollo.io's B2B database for a person by name and company domain. "
        "Returns their professional email, title, and LinkedIn URL if available. "
        "Apollo has the largest B2B database — try this FIRST before other email "
        "finding methods."
    )
    args_schema: Type[BaseModel] = ApolloPersonSearchInput

    def _run(self, person_name: str, company_domain: str) -> str:
        """Search Apollo for a person and their email."""
        api_key = _get_api_key()
        if not api_key:
            return (
                "Apollo API key not configured. Set APOLLO_API_KEY in your .env file. "
                "Get a free key at https://app.apollo.io/#/settings/integrations/api"
            )

        # Split name into first/last
        parts = person_name.strip().split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        try:
            # Use the People Search endpoint
            response = requests.post(
                f"{APOLLO_BASE_URL}/v1/mixed_people/search",
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": api_key,
                },
                json={
                    "q_keywords": person_name,
                    "person_titles": [],
                    "q_organization_domains": company_domain,
                    "page": 1,
                    "per_page": 5,
                },
                timeout=30,
            )

            if response.status_code == 401:
                return "Apollo API key is invalid. Check your APOLLO_API_KEY in .env"
            if response.status_code == 429:
                return "Apollo API rate limit reached. Try again later."
            if response.status_code != 200:
                return f"Apollo API error (HTTP {response.status_code}): {response.text[:200]}"

            data = response.json()
            people = data.get("people", [])

            if not people:
                return f"No results found on Apollo for '{person_name}' at {company_domain}"

            # Find the best match
            best = None
            for person in people:
                name_match = (
                    first_name.lower() in (person.get("first_name", "") or "").lower()
                    and last_name.lower() in (person.get("last_name", "") or "").lower()
                )
                if name_match:
                    best = person
                    break

            if not best:
                best = people[0]  # Fall back to top result

            # Extract relevant fields
            email = best.get("email")
            title = best.get("title", "Unknown")
            linkedin = best.get("linkedin_url", "")
            org = best.get("organization", {})
            company_name = org.get(
                "name", company_domain) if org else company_domain
            confidence = 90 if email else 0

            if email:
                return (
                    f"FOUND on Apollo:\n"
                    f"  Name: {best.get('first_name', '')} {best.get('last_name', '')}\n"
                    f"  Title: {title}\n"
                    f"  Company: {company_name}\n"
                    f"  Email: {email}\n"
                    f"  LinkedIn: {linkedin}\n"
                    f"  Confidence: {confidence}%\n"
                    f"  Source: apollo"
                )
            else:
                return (
                    f"Person found on Apollo but NO EMAIL available:\n"
                    f"  Name: {best.get('first_name', '')} {best.get('last_name', '')}\n"
                    f"  Title: {title}\n"
                    f"  Company: {company_name}\n"
                    f"  LinkedIn: {linkedin}\n"
                    f"  Try Hunter.io as a fallback."
                )

        except requests.exceptions.Timeout:
            return "Apollo API request timed out. Try again."
        except requests.exceptions.RequestException as e:
            return f"Apollo API request failed: {str(e)}"


class ApolloEnrichInput(BaseModel):
    """Input for Apollo enrichment."""
    first_name: str = Field(description="Person's first name")
    last_name: str = Field(description="Person's last name")
    company_domain: str = Field(
        description="Company domain (e.g., 'anthropic.com')")


class ApolloEnrichTool(BaseTool):
    name: str = "Apollo Person Enrichment"
    description: str = (
        "Enrich a person's profile using Apollo.io — get their email, phone, title, "
        "and LinkedIn from just their name and company domain. Use this when you already "
        "know who you're looking for and need their contact details."
    )
    args_schema: Type[BaseModel] = ApolloEnrichInput

    def _run(self, first_name: str, last_name: str, company_domain: str) -> str:
        """Enrich a person's profile via Apollo."""
        api_key = _get_api_key()
        if not api_key:
            return "Apollo API key not configured. Set APOLLO_API_KEY in .env"

        try:
            response = requests.post(
                f"{APOLLO_BASE_URL}/v1/people/match",
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": api_key,
                },
                json={
                    "first_name": first_name,
                    "last_name": last_name,
                    "organization_domain": company_domain,
                },
                timeout=30,
            )

            if response.status_code != 200:
                return f"Apollo enrichment failed (HTTP {response.status_code})"

            data = response.json()
            person = data.get("person")

            if not person:
                return f"No enrichment data found for {first_name} {last_name} at {company_domain}"

            email = person.get("email")
            title = person.get("title", "Unknown")
            linkedin = person.get("linkedin_url", "")
            confidence = 90 if email else 0

            if email:
                return (
                    f"ENRICHED via Apollo:\n"
                    f"  Name: {first_name} {last_name}\n"
                    f"  Title: {title}\n"
                    f"  Email: {email}\n"
                    f"  LinkedIn: {linkedin}\n"
                    f"  Confidence: {confidence}%\n"
                    f"  Source: apollo-enrich"
                )
            else:
                return f"Enrichment found but no email for {first_name} {last_name}. Try Hunter.io."

        except requests.exceptions.RequestException as e:
            return f"Apollo enrichment request failed: {str(e)}"
