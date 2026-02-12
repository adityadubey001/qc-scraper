"""Swiggy Instamart category discovery and caching."""

import csv
import logging
import os
from dataclasses import dataclass
from urllib.parse import quote, unquote_plus

from .config import CATEGORY_LISTING_URL, CATEGORIES_CACHE

log = logging.getLogger(__name__)


@dataclass
class SwiggyCategory:
    """A single Swiggy Instamart category."""

    name: str       # Display name, e.g. "Dairy & Breakfast"
    url_name: str   # URL-encoded fragment used in the listing URL

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def url(self) -> str:
        return CATEGORY_LISTING_URL.format(name=quote(self.url_name))


def load_categories_from_cache(cache_path: str | None = None) -> list[SwiggyCategory]:
    """Load previously discovered categories from a CSV cache file."""
    path = cache_path or CATEGORIES_CACHE
    if not os.path.exists(path):
        return []

    categories: list[SwiggyCategory] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            categories.append(
                SwiggyCategory(
                    name=row["name"],
                    url_name=row["url_name"],
                )
            )
    log.info("Loaded %d categories from cache %s", len(categories), path)
    return categories


def save_categories_to_cache(
    categories: list[SwiggyCategory], cache_path: str | None = None
) -> None:
    """Save discovered categories to a CSV cache file."""
    path = cache_path or CATEGORIES_CACHE
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "url_name"])
        writer.writeheader()
        for cat in categories:
            writer.writerow({"name": cat.name, "url_name": cat.url_name})
    log.info("Saved %d categories to %s", len(categories), path)


def parse_categories_from_links(links: list[dict]) -> list[SwiggyCategory]:
    """Parse category objects from a list of link dicts (href, text).

    Each dict should have keys 'href' and 'text' extracted from the
    Instamart homepage DOM.
    """
    categories: list[SwiggyCategory] = []
    seen: set[str] = set()

    for link in links:
        href = link.get("href", "")
        text = link.get("text", "").strip()

        if "category-listing" not in href:
            continue

        # Extract categoryName param from the URL
        url_name = _extract_category_name(href)
        if not url_name or url_name in seen:
            continue
        seen.add(url_name)

        display = text or unquote_plus(url_name)
        categories.append(SwiggyCategory(name=display, url_name=url_name))

    log.info("Parsed %d unique categories from links", len(categories))
    return categories


def filter_categories(
    categories: list[SwiggyCategory], name_filter: str | None
) -> list[SwiggyCategory]:
    """Case-insensitive substring filter on category name."""
    if not name_filter:
        return categories
    needle = name_filter.lower()
    return [c for c in categories if needle in c.name.lower()]


def _extract_category_name(href: str) -> str:
    """Extract the categoryName query-param value from a URL."""
    # e.g. /instamart/category-listing?categoryName=Dairy+%26+Breakfast&...
    if "categoryName=" not in href:
        return ""
    after = href.split("categoryName=", 1)[1]
    # Take everything until the next & or end of string
    name = after.split("&", 1)[0]
    return unquote_plus(name)
