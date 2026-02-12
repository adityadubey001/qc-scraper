"""HTTP fetcher with session management, header spoofing, retry, and rate limiting."""

import logging
import time

import requests
from fake_useragent import UserAgent
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .categories import Category
from .config import (
    BASE_URL,
    CATEGORY_URL,
    DEFAULT_DELAY,
    DEFAULT_HEADERS,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
)

logger = logging.getLogger(__name__)


class BlinkitFetcher:
    """Fetches Blinkit category pages with proper session/headers."""

    def __init__(self, lat: float, lon: float, delay: float = DEFAULT_DELAY):
        self.lat = lat
        self.lon = lon
        self.delay = delay
        self.session = requests.Session()
        self._ua = UserAgent(fallback="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self._setup_session()
        self._last_request_time = 0.0

    def _setup_session(self):
        """Configure session with default headers and location cookies."""
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers["User-Agent"] = self._ua.random

        # Set location headers that Blinkit uses
        self.session.headers["lat"] = str(self.lat)
        self.session.headers["lon"] = str(self.lon)

        # Visit homepage first to get session cookies
        try:
            logger.info("Visiting homepage to establish session...")
            resp = self.session.get(BASE_URL, timeout=15)
            resp.raise_for_status()
            logger.info(
                "Session established. Cookies: %s",
                list(self.session.cookies.keys()),
            )
        except requests.RequestException as e:
            logger.warning("Failed to establish session via homepage: %s", e)

    def _rate_limit(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=RETRY_BACKOFF_BASE, min=2, max=16),
        reraise=True,
    )
    def _get(self, url: str) -> requests.Response:
        """Make a GET request with retry logic."""
        self._rate_limit()

        # Rotate User-Agent periodically
        self.session.headers["User-Agent"] = self._ua.random

        self._last_request_time = time.time()
        response = self.session.get(url, timeout=20)
        return response

    def fetch_category(self, category: Category) -> str | None:
        """Fetch a category page and return the HTML content.

        Returns None if the request fails (403, 404, etc.).
        """
        url = CATEGORY_URL.format(
            slug=category.slug,
            l1_id=category.l1_id,
            l2_id=category.l2_id,
        )

        logger.info("Fetching: %s", url)

        try:
            response = self._get(url)

            if response.status_code == 200:
                return response.text
            elif response.status_code == 403:
                logger.warning(
                    "403 Forbidden for %s — may need browser mode",
                    category.display_name,
                )
            elif response.status_code == 404:
                logger.warning(
                    "404 Not Found for %s — category may not exist at this location",
                    category.display_name,
                )
            else:
                logger.warning(
                    "HTTP %d for %s",
                    response.status_code,
                    category.display_name,
                )

        except requests.RequestException as e:
            logger.error(
                "Request failed for %s: %s",
                category.display_name,
                e,
            )

        return None

    def fetch_pagination(self, next_url: str, referer: str = "") -> str | None:
        """Fetch a pagination API URL via POST and return the JSON response text.

        next_url is a relative path like /v1/layout/listing_widgets?offset=30&...
        Blinkit's pagination API requires POST (GET returns 404).
        """
        url = BASE_URL + next_url
        logger.info("Fetching pagination: %s", url)

        self._rate_limit()
        self.session.headers["User-Agent"] = self._ua.random
        self._last_request_time = time.time()

        api_headers = {
            "Accept": "application/json, text/plain, */*",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        if referer:
            api_headers["Referer"] = referer

        try:
            response = self.session.post(url, headers=api_headers, timeout=20)
            if response.status_code == 200:
                return response.text
            else:
                logger.warning("HTTP %d for pagination URL", response.status_code)
        except requests.RequestException as e:
            logger.error("Pagination request failed: %s", e)

        return None

    def update_location(self, lat: float, lon: float):
        """Update the session's location headers (e.g. after serviceability check)."""
        self.lat = lat
        self.lon = lon
        self.session.headers["lat"] = str(lat)
        self.session.headers["lon"] = str(lon)

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
