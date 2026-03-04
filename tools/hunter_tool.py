"""
Hunter.io API Tools for CrewAI.
Email finder and verifier using Hunter's free tier (25 searches + 50 verifications/month).
API docs: https://hunter.io/api-documentation
"""

import os
from typing import Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


HUNTER_BASE_URL = "https://api.hunter.io/v2"


def _get_api_key() -> str:
    """Get Hunter API key from environment."""
    key = os.getenv("HUNTER_API_KEY", "")
    if not key or key == "your-hunter-api-key-here":
        return ""
    return key


class HunterEmailFinderInput(BaseModel):
    """Input for Hunter email finder."""
    first_name: str = Field(description="Person's first name")
    last_name: str = Field(description="Person's last name")
    company_domain: str = Field(
        description="Company domain (e.g., 'anthropic.com')")


class HunterEmailFinderTool(BaseTool):
    name: str = "Hunter Email Finder"
    description: str = (
        "Find a person's professional email using Hunter.io's Email Finder. "
        "Provide first name, last name, and company domain. Returns the email "
        "with a confidence score. Use this as a FALLBACK when Apollo.io doesn't "
        "find an email. Free tier: 25 searches/month — use sparingly."
    )
    args_schema: Type[BaseModel] = HunterEmailFinderInput

    def _run(self, first_name: str, last_name: str, company_domain: str) -> str:
        """Find email via Hunter.io."""
        api_key = _get_api_key()
        if not api_key:
            return (
                "Hunter API key not configured. Set HUNTER_API_KEY in your .env file. "
                "Get a free key at https://hunter.io/api-keys"
            )

        try:
            response = requests.get(
                f"{HUNTER_BASE_URL}/email-finder",
                params={
                    "domain": company_domain,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": api_key,
                },
                timeout=30,
            )

            if response.status_code == 401:
                return "Hunter API key is invalid. Check your HUNTER_API_KEY in .env"
            if response.status_code == 429:
                return "Hunter API rate limit reached (25 searches/month on free tier). Try again next month."
            if response.status_code != 200:
                return f"Hunter API error (HTTP {response.status_code}): {response.text[:200]}"

            data = response.json().get("data", {})
            email = data.get("email")
            confidence = data.get("score", 0)
            first = data.get("first_name", first_name)
            last = data.get("last_name", last_name)

            if email:
                return (
                    f"FOUND on Hunter:\n"
                    f"  Name: {first} {last}\n"
                    f"  Email: {email}\n"
                    f"  Confidence: {confidence}%\n"
                    f"  Source: hunter"
                )
            else:
                return f"No email found on Hunter for {first_name} {last_name} at {company_domain}"

        except requests.exceptions.RequestException as e:
            return f"Hunter API request failed: {str(e)}"


class HunterVerifyInput(BaseModel):
    """Input for Hunter email verification."""
    email: str = Field(description="Email address to verify")


class HunterEmailVerifyTool(BaseTool):
    name: str = "Hunter Email Verifier"
    description: str = (
        "Verify if an email address is deliverable using Hunter.io's Email Verifier. "
        "Returns the verification status (valid, invalid, accept_all, unknown) and a "
        "confidence score. Use this to validate emails before sending. "
        "Free tier: 50 verifications/month."
    )
    args_schema: Type[BaseModel] = HunterVerifyInput

    def _run(self, email: str) -> str:
        """Verify an email via Hunter.io."""
        api_key = _get_api_key()
        if not api_key:
            return "Hunter API key not configured. Set HUNTER_API_KEY in .env"

        try:
            response = requests.get(
                f"{HUNTER_BASE_URL}/email-verifier",
                params={"email": email, "api_key": api_key},
                timeout=30,
            )

            if response.status_code == 429:
                return "Hunter verification rate limit reached (50/month free). Try next month."
            if response.status_code != 200:
                return f"Hunter verify error (HTTP {response.status_code})"

            data = response.json().get("data", {})
            status = data.get("status", "unknown")
            score = data.get("score", 0)
            result = data.get("result", "unknown")

            return (
                f"Email verification for {email}:\n"
                f"  Status: {status}\n"
                f"  Result: {result}\n"
                f"  Score: {score}%\n"
                f"  {'✓ Safe to send' if status == 'valid' else '⚠ Proceed with caution' if status == 'accept_all' else '✗ Do not send'}"
            )

        except requests.exceptions.RequestException as e:
            return f"Hunter verify request failed: {str(e)}"
