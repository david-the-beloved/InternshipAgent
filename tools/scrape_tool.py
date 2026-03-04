"""
Web Scraper Tool for CrewAI.
Lightweight page reader for blog posts, GitHub READMEs, and other public pages.
NOT for scraping LinkedIn directly.
"""

import time
from typing import Type

import requests
from bs4 import BeautifulSoup
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class ScrapeInput(BaseModel):
    """Input for the web scrape tool."""
    url: str = Field(description="The URL of the web page to read")


class WebScrapeTool(BaseTool):
    name: str = "Read Web Page"
    description: str = (
        "Read the text content of a public web page. Use this to read blog posts, "
        "GitHub profile READMEs, company about pages, conference talk descriptions, "
        "and other public pages found during research. Returns the main text content "
        "of the page (stripped of HTML). DO NOT use this on LinkedIn — LinkedIn blocks "
        "scraping. Use DuckDuckGo search snippets for LinkedIn data instead."
    )
    args_schema: Type[BaseModel] = ScrapeInput

    _last_request_time: float = 0
    _min_interval: float = 5.0  # seconds between requests

    def _run(self, url: str) -> str:
        """Scrape the text content from a URL."""
        # Block LinkedIn scraping
        if "linkedin.com" in url.lower():
            return (
                "Cannot scrape LinkedIn directly — it blocks automated access. "
                "Use the DuckDuckGo or LinkedIn search tools instead to get "
                "LinkedIn profile information from search snippets."
            )

        # Rate limiting
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }

            response = requests.get(url, headers=headers, timeout=15)

            if response.status_code != 200:
                return f"Failed to read {url} (HTTP {response.status_code})"

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove script, style, nav, footer elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            # Try to find main content
            main = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", {"class": "content"})
                or soup.find("div", {"id": "content"})
                or soup.find("body")
            )

            if not main:
                return f"Could not extract content from {url}"

            text = main.get_text(separator="\n", strip=True)

            # Truncate very long pages to save tokens
            max_chars = 4000
            if len(text) > max_chars:
                text = text[:max_chars] + \
                    "\n\n[... content truncated for brevity]"

            return f"Content from {url}:\n\n{text}"

        except requests.exceptions.Timeout:
            return f"Request to {url} timed out."
        except requests.exceptions.RequestException as e:
            return f"Failed to read {url}: {str(e)}"
