"""
Tests for the Email Finder Agent's tools.
Run with: python -m pytest tests/test_email_finder.py -v
"""

import os

import pytest
from tools.apollo_tool import ApolloPersonSearchTool, ApolloEnrichTool
from tools.hunter_tool import HunterEmailFinderTool, HunterEmailVerifyTool


class TestApolloPersonSearchTool:
    """Test Apollo.io People Search tool."""

    def test_tool_has_correct_metadata(self):
        tool = ApolloPersonSearchTool()
        assert tool.name == "Apollo People Search"
        assert "apollo" in tool.description.lower()

    def test_returns_error_without_api_key(self):
        """Without a valid API key, should return a helpful error."""
        # Temporarily clear the key
        original = os.environ.get("APOLLO_API_KEY", "")
        os.environ["APOLLO_API_KEY"] = ""
        try:
            tool = ApolloPersonSearchTool()
            result = tool._run("John Doe", "example.com")
            assert "not configured" in result.lower() or "api key" in result.lower()
        finally:
            os.environ["APOLLO_API_KEY"] = original


class TestApolloEnrichTool:
    """Test Apollo.io Enrichment tool."""

    def test_tool_has_correct_metadata(self):
        tool = ApolloEnrichTool()
        assert tool.name == "Apollo Person Enrichment"


class TestHunterEmailFinderTool:
    """Test Hunter.io Email Finder tool."""

    def test_tool_has_correct_metadata(self):
        tool = HunterEmailFinderTool()
        assert tool.name == "Hunter Email Finder"

    def test_returns_error_without_api_key(self):
        original = os.environ.get("HUNTER_API_KEY", "")
        os.environ["HUNTER_API_KEY"] = ""
        try:
            tool = HunterEmailFinderTool()
            result = tool._run("John", "Doe", "example.com")
            assert "not configured" in result.lower() or "api key" in result.lower()
        finally:
            os.environ["HUNTER_API_KEY"] = original


class TestHunterEmailVerifyTool:
    """Test Hunter.io Email Verifier tool."""

    def test_tool_has_correct_metadata(self):
        tool = HunterEmailVerifyTool()
        assert tool.name == "Hunter Email Verifier"
