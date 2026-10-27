"""Fetch Zepto pages through the Scrape.do API.

Zepto sits behind AWS WAF on CloudFront. A plain ``requests`` call gets HTTP 429;
with a browser user agent it gets HTTP 202, an empty body and
``x-amzn-waf-action: challenge``. 202 counts as success to
``raise_for_status()``, so this client checks for ``status_code != 200``.

Zepto's WAF also blocks Scrape.do's default rotation (502 ROTATION_FAILED after
about a minute), so every page goes through residential proxies in India
(``super=true&geoCode=in``, 10 credits, about 3 seconds).
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

import requests

from .parser import ZEPTO, parse_listing, parse_product, subcategory_paths

API_URL = "https://api.scrape.do/"
TOKEN_ENV = "SCRAPEDO_TOKEN"
PROXY_PARAMS = {"super": "true", "geoCode": "in"}


class ScrapeError(RuntimeError):
    """Raised when a page cannot be fetched."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ZeptoScraper:
    """Fetch and parse Zepto category and product pages.

    >>> scraper = ZeptoScraper(token="YOUR_SCRAPEDO_TOKEN")
    >>> rows = scraper.get_category("https://www.zepto.com/cn/munchies/chips-crisps/cid/.../scid/...")
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = 120.0,
        retries: int = 2,
        session: Optional[requests.Session] = None,
    ):
        self.token = token or os.environ.get(TOKEN_ENV, "")
        if not self.token:
            raise ValueError(f"A Scrape.do API token is required. Pass token=... or set {TOKEN_ENV}.")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session()

    def fetch(self, url: str) -> str:
        """Return the raw HTML of ``url``. Anything but a 200 is an error."""
        params = {"token": self.token, "url": url, **PROXY_PARAMS}
        last_error: Optional[ScrapeError] = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = ScrapeError(f"Request failed: {exc}")
            else:
                if response.status_code == 200 and response.text:
                    return response.text
                last_error = ScrapeError(
                    f"Request for {url} failed with status {response.status_code}",
                    status_code=response.status_code,
                )
                # Client errors (bad token, bad URL) will not fix themselves
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < self.retries:
                time.sleep(2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def get_subcategory(self, url: str) -> List[dict]:
        """Every product card on one subcategory page (at most 32 on Zepto's web pages)."""
        return parse_listing(self.fetch(url))

    def get_category(self, start_url: str, max_subcategories: int = 20) -> List[dict]:
        """Walk the start subcategory and its siblings; one row per unique product."""
        first = self.fetch(start_url)
        rows = {}
        for path in subcategory_paths(first, start_url)[:max_subcategories]:
            html = first if path in start_url else self.fetch(ZEPTO + path)
            for row in parse_listing(html):
                rows.setdefault(row["variant_id"], row)
        return list(rows.values())

    def get_product(self, url: str) -> dict:
        """Catalog sheet for one product page (seller, shelf life, FSSAI licence...)."""
        return parse_product(self.fetch(url), url)
