"""
DuckDuckGo Search Tool for CrewAI.
Wraps the duckduckgo-search package with rate limiting and result formatting.
"""

import time
from typing import Type

from crewai.tools import BaseTool
from ddgs import DDGS
from pydantic import BaseModel, Field


class SearchInput(BaseModel):
    """Input for the DuckDuckGo search tool."""
    query: str = Field(description="The search query to execute")
    max_results: int = Field(
        default=8, description="Maximum number of results to return")


class DuckDuckGoSearchTool(BaseTool):
    name: str = "DuckDuckGo Web Search"
    description: str = (
        "Search the internet using DuckDuckGo. Use this to find people at companies, "
        "discover LinkedIn profiles, blog posts, conference talks, GitHub profiles, "
        "and any other public information. Supports advanced operators like "
        "site:linkedin.com/in/ for targeted searches. Returns titles, URLs, and snippets."
    )
    args_schema: Type[BaseModel] = SearchInput

    # Rate limiting: track last request time
    _last_request_time: float = 0
    _min_interval: float = 12.0  # seconds between requests (5 per minute)

    def _run(self, query: str, max_results: int = 8) -> str:
        """Execute a DuckDuckGo search with rate limiting."""
        # Rate limiting
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            time.sleep(wait)
        self._last_request_time = time.time()

        try:
            results = DDGS().text(query, max_results=max_results)

            if not results:
                return f"No results found for: {query}"

            formatted = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("href", r.get("link", "No URL"))
                snippet = r.get("body", r.get("snippet", "No description"))
                formatted.append(
                    f"[{i}] {title}\n    URL: {url}\n    {snippet}"
                )

            return f"Search results for: {query}\n\n" + "\n\n".join(formatted)

        except Exception as e:
            return f"Search failed for '{query}': {str(e)}. Try again with a simpler query."


class LinkedInSearchTool(BaseTool):
    name: str = "LinkedIn Profile Search"
    description: str = (
        "Search for LinkedIn profiles of people at a specific company in a specific role. "
        "This searches Google/DuckDuckGo with site:linkedin.com/in/ — it does NOT scrape "
        "LinkedIn directly. Use this to find names, titles, and LinkedIn URLs of potential "
        "outreach targets."
    )
    args_schema: Type[BaseModel] = SearchInput

    _last_request_time: float = 0
    _min_interval: float = 12.0

    def _run(self, query: str, max_results: int = 8) -> str:
        """Search for LinkedIn profiles via DuckDuckGo."""
        # Ensure the query targets LinkedIn
        if "site:linkedin.com" not in query.lower():
            query = f"site:linkedin.com/in/ {query}"

        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            time.sleep(wait)
        self._last_request_time = time.time()

        try:
            results = DDGS().text(query, max_results=max_results)

            if not results:
                return f"No LinkedIn profiles found for: {query}"

            formatted = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                url = r.get("href", r.get("link", "No URL"))
                snippet = r.get("body", r.get("snippet", "No description"))
                # Only include results that are actually LinkedIn profiles
                if "linkedin.com/in/" in url.lower():
                    formatted.append(
                        f"[{i}] {title}\n    LinkedIn: {url}\n    {snippet}"
                    )

            if not formatted:
                return f"No LinkedIn profile results found for: {query}"

            return f"LinkedIn search results for: {query}\n\n" + "\n\n".join(formatted)

        except Exception as e:
            return f"LinkedIn search failed for '{query}': {str(e)}"
