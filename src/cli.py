"""Click CLI for the Blinkit and Swiggy Instamart scrapers."""

import asyncio
import logging
import sys

import json

import click
from tqdm import tqdm

from .categories import filter_categories, load_categories
from .config import DEFAULT_DELAY, DEFAULT_OUTPUT, FAILURE_THRESHOLD
from .fetcher import BlinkitFetcher
from .location import resolve_pincode
from .config import CATEGORY_URL
from .parser import extract_products_from_html, extract_serviceable_location, parse_pagination_response
from .writer import print_summary, write_products

# Max pagination pages per category to avoid infinite loops
MAX_PAGES_PER_CATEGORY = 20


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose):
    """Blinkit & Swiggy Instamart product scraper — scrape grocery data by location."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
@click.option("--pincode", type=str, help="Indian pincode (e.g., 110001)")
@click.option("--lat", type=float, help="Latitude")
@click.option("--lon", type=float, help="Longitude")
@click.option("-o", "--output", default=DEFAULT_OUTPUT, help="Output CSV path")
@click.option("--category", "cat_filter", default=None, help="Filter by L1 category name")
@click.option("--delay", type=float, default=DEFAULT_DELAY, help="Delay between requests (seconds)")
@click.option("--categories-file", default=None, help="Path to categories CSV")
def scrape(pincode, lat, lon, output, cat_filter, delay, categories_file):
    """Scrape all products from Blinkit for a given location."""
    # Resolve location
    lat, lon = _resolve_location(pincode, lat, lon)
    click.echo(f"Location: ({lat:.4f}, {lon:.4f})")

    # Load categories
    categories = load_categories(categories_file)
    categories = filter_categories(categories, cat_filter)

    if not categories:
        click.echo("No categories to scrape. Check your --category filter or categories.csv.")
        sys.exit(1)

    click.echo(f"Scraping {len(categories)} categories...")

    all_products = []
    categories_failed = 0
    location_checked = False

    with BlinkitFetcher(lat, lon, delay=delay) as fetcher:
        for category in tqdm(categories, desc="Categories", unit="cat"):
            html = fetcher.fetch_category(category)
            if html is None:
                categories_failed += 1
                continue

            # On first successful fetch, check if Blinkit resolved to a different location
            if not location_checked:
                location_checked = True
                svc = extract_serviceable_location(html)
                if svc:
                    svc_lat, svc_lon, svc_city = svc
                    dist = abs(svc_lat - lat) + abs(svc_lon - lon)
                    if dist > 0.1:
                        tqdm.write(
                            f"  Note: Blinkit resolved location to {svc_city} "
                            f"({svc_lat:.4f}, {svc_lon:.4f}). "
                            f"Pincode may not be directly serviceable."
                        )
                    fetcher.update_location(svc_lat, svc_lon)
                    lat, lon = svc_lat, svc_lon

            products, next_url = extract_products_from_html(html, category, lat, lon)
            all_products.extend(products)

            # Follow pagination via POST API
            page = 1
            referer = CATEGORY_URL.format(
                slug=category.slug, l1_id=category.l1_id, l2_id=category.l2_id
            )
            while next_url and page < MAX_PAGES_PER_CATEGORY:
                page += 1
                page_text = fetcher.fetch_pagination(next_url, referer=referer)
                if not page_text:
                    break
                try:
                    page_data = json.loads(page_text)
                except (json.JSONDecodeError, ValueError):
                    break
                page_products, next_url = parse_pagination_response(
                    page_data, category, lat, lon,
                )
                if not page_products:
                    break
                all_products.extend(page_products)

            tqdm.write(
                f"  {category.display_name}: {len(products)} products"
                + (f" (+{page - 1} pages)" if page > 1 else "")
            )

    # Check failure rate
    total_cats = len(categories)
    if categories_failed > 0 and categories_failed / total_cats > FAILURE_THRESHOLD:
        click.echo(
            f"\nWarning: {categories_failed}/{total_cats} categories failed. "
            "Blinkit may be blocking direct requests. "
            "Try using --delay 5 or a proxy."
        )

    # Write output
    written, duplicates = write_products(all_products, output)
    summary = print_summary(
        total_products=len(all_products),
        duplicates=duplicates,
        categories_scraped=total_cats - categories_failed,
        categories_failed=categories_failed,
        output_path=output,
    )
    click.echo(summary)


@cli.command()
@click.option("--pincode", required=True, type=str, help="Indian pincode")
def locate(pincode):
    """Resolve a pincode to latitude/longitude."""
    try:
        lat, lon = resolve_pincode(pincode)
        click.echo(f"Pincode: {pincode}")
        click.echo(f"Latitude:  {lat:.6f}")
        click.echo(f"Longitude: {lon:.6f}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("list-categories")
@click.option("--category", "cat_filter", default=None, help="Filter by L1 category name")
@click.option("--categories-file", default=None, help="Path to categories CSV")
def list_categories(cat_filter, categories_file):
    """List all bundled Blinkit categories."""
    categories = load_categories(categories_file)
    categories = filter_categories(categories, cat_filter)

    if not categories:
        click.echo("No categories found.")
        return

    current_l1 = None
    for cat in categories:
        if cat.l1_name != current_l1:
            current_l1 = cat.l1_name
            click.echo(f"\n{cat.l1_name} (id={cat.l1_id})")
        click.echo(f"  └─ {cat.l2_name} (id={cat.l2_id})")

    click.echo(f"\nTotal: {len(categories)} sub-categories")


def _resolve_location(
    pincode: str | None, lat: float | None, lon: float | None
) -> tuple[float, float]:
    """Resolve location from pincode or lat/lon arguments."""
    if lat is not None and lon is not None:
        return lat, lon
    if pincode:
        return resolve_pincode(pincode)
    click.echo("Error: Provide --pincode or both --lat and --lon.", err=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Swiggy Instamart commands
# ---------------------------------------------------------------------------

@cli.command("swiggy-scrape")
@click.option("--pincode", type=str, help="Indian pincode (e.g., 400706)")
@click.option("--lat", type=float, help="Latitude")
@click.option("--lon", type=float, help="Longitude")
@click.option("-o", "--output", default=None, help="Output CSV path")
@click.option("--category", "cat_filter", default=None, help="Filter by category name")
@click.option("--delay", type=float, default=None, help="Delay between navigations (seconds)")
@click.option("--headful", is_flag=True, help="Run browser in visible (non-headless) mode")
@click.option("--categories-file", default=None, help="Path to cached categories CSV")
def swiggy_scrape(pincode, lat, lon, output, cat_filter, delay, headful, categories_file):
    """Scrape all products from Swiggy Instamart for a given location."""
    from .swiggy.config import DEFAULT_DELAY as SWIGGY_DELAY, DEFAULT_OUTPUT as SWIGGY_OUTPUT
    from .swiggy.fetcher import SwiggyFetcher
    from .swiggy.categories import (
        filter_categories as swiggy_filter,
        load_categories_from_cache,
        save_categories_to_cache,
    )

    lat, lon = _resolve_location(pincode, lat, lon)
    click.echo(f"Location: ({lat:.4f}, {lon:.4f})")

    output = output or SWIGGY_OUTPUT
    delay = delay if delay is not None else SWIGGY_DELAY

    async def _run():
        fetcher = SwiggyFetcher(lat, lon, delay=delay, headless=not headful)
        await fetcher.start()

        try:
            # Load categories: from cache, or auto-discover
            categories = load_categories_from_cache(categories_file)
            if not categories:
                click.echo("Discovering Swiggy Instamart categories...")
                categories = await fetcher.discover_categories()
                if categories:
                    save_categories_to_cache(categories)
                    click.echo(f"Found {len(categories)} categories (saved to cache)")
                else:
                    click.echo("No categories discovered. Try --headful to debug.")
                    return

            categories = swiggy_filter(categories, cat_filter)
            if not categories:
                click.echo("No categories match your filter.")
                return

            click.echo(f"Scraping {len(categories)} categories...")

            all_products = []
            categories_failed = 0

            for i, category in enumerate(categories, 1):
                click.echo(f"  [{i}/{len(categories)}] {category.display_name}...", nl=False)
                try:
                    products = await fetcher.fetch_category(category)
                    all_products.extend(products)
                    click.echo(f" {len(products)} products")
                except Exception as e:
                    categories_failed += 1
                    click.echo(f" FAILED ({e})")

            # Write output
            written, duplicates = write_products(all_products, output)
            summary = print_summary(
                total_products=len(all_products),
                duplicates=duplicates,
                categories_scraped=len(categories) - categories_failed,
                categories_failed=categories_failed,
                output_path=output,
            )
            click.echo(summary)

        finally:
            await fetcher.close()

    asyncio.run(_run())


@cli.command("swiggy-categories")
@click.option("--pincode", type=str, help="Indian pincode (e.g., 400706)")
@click.option("--lat", type=float, help="Latitude")
@click.option("--lon", type=float, help="Longitude")
@click.option("--headful", is_flag=True, help="Run browser in visible mode")
@click.option("--refresh", is_flag=True, help="Re-discover categories (ignore cache)")
def swiggy_categories(pincode, lat, lon, headful, refresh):
    """Discover and list Swiggy Instamart categories."""
    from .swiggy.config import DEFAULT_DELAY as SWIGGY_DELAY
    from .swiggy.fetcher import SwiggyFetcher
    from .swiggy.categories import load_categories_from_cache, save_categories_to_cache

    lat, lon = _resolve_location(pincode, lat, lon)
    click.echo(f"Location: ({lat:.4f}, {lon:.4f})")

    # Try cache first (unless --refresh)
    if not refresh:
        categories = load_categories_from_cache()
        if categories:
            click.echo(f"\nCached Swiggy Instamart categories ({len(categories)}):\n")
            for i, cat in enumerate(categories, 1):
                click.echo(f"  {i:3d}. {cat.display_name}")
            click.echo(f"\nTotal: {len(categories)} categories")
            click.echo("(Use --refresh to re-discover from Swiggy)")
            return

    async def _run():
        fetcher = SwiggyFetcher(lat, lon, delay=SWIGGY_DELAY, headless=not headful)
        await fetcher.start()
        try:
            click.echo("Discovering categories from Swiggy Instamart...")
            categories = await fetcher.discover_categories()
            if categories:
                save_categories_to_cache(categories)
                click.echo(f"\nSwiggy Instamart categories ({len(categories)}):\n")
                for i, cat in enumerate(categories, 1):
                    click.echo(f"  {i:3d}. {cat.display_name}")
                click.echo(f"\nTotal: {len(categories)} categories (saved to cache)")
            else:
                click.echo("No categories found. Try --headful to debug.")
        finally:
            await fetcher.close()

    asyncio.run(_run())
