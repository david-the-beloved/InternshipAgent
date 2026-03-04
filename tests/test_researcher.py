"""
Tests for the Researcher Agent's tools.
Run with: python -m pytest tests/test_researcher.py -v
"""

import pytest
from tools.search_tool import DuckDuckGoSearchTool, LinkedInSearchTool


class TestDuckDuckGoSearchTool:
    """Test the DuckDuckGo search tool."""

    def test_tool_has_correct_metadata(self):
        tool = DuckDuckGoSearchTool()
        assert tool.name == "DuckDuckGo Web Search"
        assert "search" in tool.description.lower()

    def test_search_returns_results(self):
        """Integration test — requires internet. May fail due to rate limits."""
        tool = DuckDuckGoSearchTool()
        result = tool._run("Python programming language", max_results=3)
        # DuckDuckGo may rate-limit in CI — accept both success and empty results
        assert isinstance(result, str)
        assert "Python" in result or "No results" in result

    def test_search_handles_empty_results(self):
        tool = DuckDuckGoSearchTool()
        result = tool._run("xyzzyqqqnotarealquery12345", max_results=3)
        assert isinstance(result, str)


class TestLinkedInSearchTool:
    """Test the LinkedIn search tool."""

    def test_tool_has_correct_metadata(self):
        tool = LinkedInSearchTool()
        assert tool.name == "LinkedIn Profile Search"

    def test_adds_site_operator(self):
        tool = LinkedInSearchTool()
        # This test mainly checks the tool doesn't crash
        result = tool._run('"software engineer" "Google"', max_results=3)
        assert isinstance(result, str)
