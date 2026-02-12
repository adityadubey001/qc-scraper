"""Playwright-based Swiggy Instamart fetcher with network interception."""

import asyncio
import logging
import random
import time

from playwright.async_api import async_playwright, Page, BrowserContext, Response

from .categories import SwiggyCategory, parse_categories_from_links
from .config import (
    DEFAULT_DELAY,
    INSTAMART_URL,
    MAX_SCROLLS,
    NAV_TIMEOUT,
    PAGE_TIMEOUT,
    SCROLL_PAUSE,
    SWIGGY_BASE_URL,
)
from .parser import extract_products_from_response

log = logging.getLogger(__name__)


class SwiggyFetcher:
    """Headless Chromium fetcher for Swiggy Instamart.

    Uses Playwright to render pages and intercept XHR responses
    containing product data.
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        delay: float = DEFAULT_DELAY,
        headless: bool = True,
    ):
        self.lat = lat
        self.lon = lon
        self.delay = delay
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_nav_time: float = 0.0
        self._collected: list[dict] = []

    async def start(self) -> None:
        """Launch browser and establish Swiggy session."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            geolocation={"latitude": self.lat, "longitude": self.lon},
            permissions=["geolocation"],
            locale="en-IN",
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(PAGE_TIMEOUT)
        self._page.set_default_navigation_timeout(NAV_TIMEOUT)

        # Navigate to Swiggy homepage to establish cookies/session
        log.info("Navigating to Swiggy to establish session...")
        await self._page.goto(SWIGGY_BASE_URL, wait_until="domcontentloaded")
        await self._page.wait_for_timeout(2000)

        # Try to set location via the Swiggy address/location flow
        await self._set_location()

        # Navigate to Instamart to verify it loads
        log.info("Navigating to Instamart...")
        await self._page.goto(INSTAMART_URL, wait_until="domcontentloaded")
        await self._page.wait_for_timeout(3000)
        log.info("Session established. Page title: %s", await self._page.title())

    async def close(self) -> None:
        """Shut down browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._context = None
        self._page = None

    async def discover_categories(self) -> list[SwiggyCategory]:
        """Navigate to the Instamart homepage and extract category links."""
        page = self._page
        await self._rate_limit()
        await page.goto(INSTAMART_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Scroll down to ensure all category sections are loaded
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(800)

        # Extract all links that look like category-listing URLs
        links = await page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('a[href*="category-listing"]').forEach(a => {
                    results.push({href: a.href, text: a.textContent.trim()});
                });
                return results;
            }
        """)

        if not links:
            # Fallback: look for any links under the Instamart section
            links = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('a[href*="instamart"]').forEach(a => {
                        if (a.href.includes('category') || a.href.includes('listing')) {
                            results.push({href: a.href, text: a.textContent.trim()});
                        }
                    });
                    return results;
                }
            """)

        log.info("Found %d category links on Instamart homepage", len(links))
        return parse_categories_from_links(links)

    async def fetch_category(self, category: SwiggyCategory) -> list[dict]:
        """Fetch all products for a single category using network interception.

        Returns a list of normalized product row dicts.
        """
        page = self._page
        self._collected.clear()

        # Attach response listener
        page.on("response", self._on_response)

        try:
            await self._rate_limit()
            log.debug("Navigating to category: %s", category.display_name)
            await page.goto(category.url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Scroll to trigger lazy-loading / pagination
            await self._scroll_to_load_all(page)

            # Also try clicking "Load More" / "Show More" buttons
            await self._click_load_more(page)

        except Exception as e:
            log.warning("Error fetching category %s: %s", category.display_name, e)
        finally:
            page.remove_listener("response", self._on_response)

        # Parse all collected XHR responses
        products: list[dict] = []
        for json_data in self._collected:
            batch = extract_products_from_response(
                json_data, category.name, self.lat, self.lon
            )
            products.extend(batch)

        # Also try parsing from the page's initial HTML/script data
        page_products = await self._extract_from_page(page, category.name)
        products.extend(page_products)

        # Deduplicate by variant_id within this category
        seen: set[str] = set()
        unique: list[dict] = []
        for p in products:
            vid = p.get("variant_id", "")
            if vid and vid not in seen:
                seen.add(vid)
                unique.append(p)

        log.info(
            "Category %s: %d products (%d raw, %d deduped)",
            category.display_name,
            len(unique),
            len(products),
            len(products) - len(unique),
        )
        return unique

    async def _on_response(self, response: Response) -> None:
        """Intercept XHR/fetch responses that may contain product data."""
        req = response.request
        if req.resource_type not in ("xhr", "fetch"):
            return

        # Only process JSON responses
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return

        try:
            json_data = await response.json()
            if self._has_product_data(json_data):
                self._collected.append(json_data)
                log.debug(
                    "Intercepted product response from %s (%d bytes)",
                    req.url[:80],
                    len(str(json_data)),
                )
        except Exception:
            pass

    def _has_product_data(self, data: dict) -> bool:
        """Check if a JSON response likely contains product snippets."""
        if not isinstance(data, dict):
            return False

        # Walk through known response structures
        for path in [
            ("data", "response", "snippets"),
            ("response", "snippets"),
            ("data", "snippets"),
            ("snippets",),
            ("data", "widgets"),
            ("widgets",),
        ]:
            node = data
            for key in path:
                if isinstance(node, dict):
                    node = node.get(key)
                else:
                    node = None
                    break
            if isinstance(node, list) and len(node) > 0:
                # Check if first item looks like a product
                first = node[0]
                if isinstance(first, dict):
                    d = first.get("data", first)
                    if isinstance(d, dict) and (
                        self._deep_get(d, "identity", "id")
                        or d.get("product_id")
                        or d.get("id")
                        or d.get("name")
                    ):
                        return True
        return False

    @staticmethod
    def _deep_get(d: dict, *keys: str):
        node = d
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                return None
        return node

    async def _scroll_to_load_all(self, page: Page) -> None:
        """Scroll down the page to trigger lazy-loading of products."""
        prev_height = 0
        for i in range(MAX_SCROLLS):
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == prev_height and i > 0:
                break
            prev_height = current_height

            # Scroll to bottom with a small random offset for naturalness
            offset = random.randint(50, 200)
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight - {offset})")
            await page.wait_for_timeout(int(SCROLL_PAUSE * 1000))

        # Scroll back to top (some sites load content when scrolling up)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)

    async def _click_load_more(self, page: Page) -> None:
        """Click any 'Load More' / 'Show More' buttons on the page."""
        selectors = [
            "button:has-text('Load More')",
            "button:has-text('Show More')",
            "button:has-text('View More')",
            "button:has-text('See All')",
            "[data-testid='load-more']",
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=1000):
                    # Click repeatedly until the button disappears
                    for _ in range(10):
                        if not await btn.is_visible(timeout=500):
                            break
                        await btn.click()
                        await page.wait_for_timeout(int(SCROLL_PAUSE * 1000))
            except Exception:
                continue

    async def _extract_from_page(self, page: Page, category_name: str) -> list[dict]:
        """Try to extract product data from page script tags / window objects."""
        try:
            # Try to extract from window.__PRELOADED_STATE__ or similar
            data = await page.evaluate("""
                () => {
                    // Common Swiggy state containers
                    const candidates = [
                        window.__PRELOADED_STATE__,
                        window.__NEXT_DATA__,
                        window.__APP_DATA__,
                        window._swiggy_data,
                    ];
                    for (const c of candidates) {
                        if (c && typeof c === 'object') return c;
                    }
                    return null;
                }
            """)
            if data:
                return extract_products_from_response(data, category_name, self.lat, self.lon)
        except Exception:
            pass
        return []

    async def _set_location(self) -> None:
        """Attempt to set the delivery location on Swiggy.

        Strategy: Try Playwright geolocation first (set in context).
        If that isn't picked up, try interacting with the location UI.
        """
        page = self._page

        # Strategy 1: Click location / detect prompt and search by coordinates
        try:
            # Look for location-related elements (Swiggy often shows a location bar)
            location_selectors = [
                "[data-testid='address-input']",
                "input[placeholder*='location']",
                "input[placeholder*='address']",
                "input[placeholder*='area']",
                "#location-search",
            ]
            for selector in location_selectors:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=2000):
                        await el.click()
                        await el.fill(f"{self.lat}, {self.lon}")
                        await page.wait_for_timeout(2000)
                        # Try to select the first suggestion
                        suggestion = page.locator(
                            "[data-testid='address-suggestion'], "
                            ".location-suggestion, "
                            "[role='option']"
                        ).first
                        if await suggestion.is_visible(timeout=2000):
                            await suggestion.click()
                            await page.wait_for_timeout(1500)
                            log.info("Location set via address search UI")
                            return
                except Exception:
                    continue
        except Exception:
            pass

        # Strategy 2: Use Swiggy's address API directly via page.evaluate
        try:
            result = await page.evaluate(f"""
                async () => {{
                    try {{
                        const resp = await fetch(
                            'https://www.swiggy.com/dapi/misc/address-recommend?latlng={self.lat}%2C{self.lon}',
                            {{ credentials: 'include' }}
                        );
                        const data = await resp.json();
                        return data;
                    }} catch (e) {{
                        return null;
                    }}
                }}
            """)
            if result:
                log.info("Fetched address recommendation for location")

                # Set the address via Swiggy's internal API
                address_id = ""
                if isinstance(result, dict):
                    addresses = result.get("data", [])
                    if isinstance(addresses, list) and addresses:
                        address_id = addresses[0].get("place_id", "")

                if address_id:
                    await page.evaluate(f"""
                        async () => {{
                            try {{
                                await fetch(
                                    'https://www.swiggy.com/dapi/misc/place-autocomplete?place_id={address_id}',
                                    {{ credentials: 'include' }}
                                );
                            }} catch (e) {{}}
                        }}
                    """)
                    log.info("Set location via Swiggy address API")
                    return
        except Exception:
            pass

        # Strategy 3: Inject lat/lon cookies (fallback)
        try:
            await self._context.add_cookies([
                {
                    "name": "userLocation",
                    "value": f'{{"lat":{self.lat},"lng":{self.lon}}}',
                    "domain": ".swiggy.com",
                    "path": "/",
                },
                {
                    "name": "swgy_lat",
                    "value": str(self.lat),
                    "domain": ".swiggy.com",
                    "path": "/",
                },
                {
                    "name": "swgy_lng",
                    "value": str(self.lon),
                    "domain": ".swiggy.com",
                    "path": "/",
                },
            ])
            log.info("Set location via cookies (lat=%s, lon=%s)", self.lat, self.lon)
        except Exception as e:
            log.warning("Could not set location cookies: %s", e)

    async def _rate_limit(self) -> None:
        """Enforce minimum delay between page navigations."""
        elapsed = time.time() - self._last_nav_time
        if elapsed < self.delay:
            wait = self.delay - elapsed + random.uniform(0, 0.5)
            await asyncio.sleep(wait)
        self._last_nav_time = time.time()


def run_sync(coro):
    """Run an async coroutine synchronously (for CLI usage)."""
    return asyncio.run(coro)
