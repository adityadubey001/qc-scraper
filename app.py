"""Blinkit Product Scraper — Streamlit Web UI."""

import csv
import io
import json
import re
import sys
import os
import time

import streamlit as st

# Ensure src/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.categories import Category, load_categories, filter_categories
from src.config import CATEGORY_URL, CSV_FIELDS, DEFAULT_DELAY
from src.fetcher import BlinkitFetcher
from src.location import resolve_pincode
from src.parser import (
    extract_products_from_html,
    extract_serviceable_location,
    parse_pagination_response,
)

MAX_PAGES_PER_CATEGORY = 20

# ScraperAPI key from Streamlit secrets (invisible to end users)
_SCRAPER_API_KEY = st.secrets.get("SCRAPER_API_KEY", None)

# Regex patterns for Google Maps URLs:
#   https://www.google.com/maps/@19.033,73.029,15z
#   https://www.google.com/maps/place/.../@19.033,73.029,15z/...
#   https://maps.google.com/?q=19.033,73.029
#   https://www.google.com/maps?ll=19.033,73.029
_GMAPS_AT_RE = re.compile(r"@(-?\d+\.?\d*),(-?\d+\.?\d*)")
_GMAPS_Q_RE = re.compile(r"[?&]q=(-?\d+\.?\d*),(-?\d+\.?\d*)")
_GMAPS_LL_RE = re.compile(r"[?&]ll=(-?\d+\.?\d*),(-?\d+\.?\d*)")


def _parse_gmaps_url(url: str) -> tuple[float, float] | None:
    """Extract lat/lon from a Google Maps URL. Returns None on failure."""
    for pattern in (_GMAPS_AT_RE, _GMAPS_Q_RE, _GMAPS_LL_RE):
        m = pattern.search(url)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None

st.set_page_config(page_title="Blinkit Scraper", page_icon="🛒", layout="wide")
st.title("🛒 Blinkit Product Scraper")

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Location")
    loc_mode = st.radio(
        "Resolve by", ["Google Maps Link", "Lat / Lon", "Pincode"], horizontal=True,
    )

    pincode = None
    input_lat = input_lon = None
    gmaps_url = None

    if loc_mode == "Google Maps Link":
        gmaps_url = st.text_input(
            "Google Maps URL",
            placeholder="https://www.google.com/maps/@19.033,73.029,15z",
        )
    elif loc_mode == "Lat / Lon":
        input_lat = st.number_input("Latitude", value=19.0330, format="%.4f")
        input_lon = st.number_input("Longitude", value=73.0297, format="%.4f")
    else:
        pincode = st.text_input("Pincode", value="400706", max_chars=6)

    st.divider()
    st.header("Categories")

    all_categories = load_categories()
    l1_names = sorted(set(c.l1_name for c in all_categories))
    selected_l1 = st.multiselect("L1 categories", l1_names, default=l1_names)

    if selected_l1:
        selected_set = set(selected_l1)
        categories = [c for c in all_categories if c.l1_name in selected_set]
    else:
        categories = all_categories

    st.caption(f"{len(categories)} sub-categories selected")

    st.divider()
    st.header("Settings")
    delay = st.slider("Delay between requests (s)", 1.0, 10.0, 5.0, 0.5)

    run_clicked = st.button("Run Scrape", type="primary", use_container_width=True)

# ── Main area ────────────────────────────────────────────────────────────────

if run_clicked:
    # Resolve location
    try:
        if gmaps_url:
            result = _parse_gmaps_url(gmaps_url)
            if result is None:
                st.error("Could not extract coordinates from that Google Maps URL.")
                st.stop()
            lat, lon = result
            st.info(f"Google Maps link resolved to ({lat:.4f}, {lon:.4f})")
        elif pincode:
            lat, lon = resolve_pincode(pincode)
            st.info(f"Pincode {pincode} resolved to ({lat:.4f}, {lon:.4f})")
        else:
            lat, lon = input_lat, input_lon
    except ValueError as e:
        st.error(f"Could not resolve location: {e}")
        st.stop()

    if not categories:
        st.warning("No categories selected.")
        st.stop()

    all_products: list[dict] = []
    categories_failed = 0
    location_checked = False
    total = len(categories)

    progress_bar = st.progress(0, text="Starting scrape...")
    status = st.status("Initializing...", expanded=True)

    try:
        with BlinkitFetcher(lat, lon, delay=delay, scraper_api_key=_SCRAPER_API_KEY) as fetcher:
            for i, category in enumerate(categories):
                pct = (i + 1) / total
                progress_bar.progress(pct, text=f"Category {i + 1}/{total}")
                status.update(label=f"Scraping {category.display_name}...")

                html = fetcher.fetch_category(category)
                if html is None:
                    categories_failed += 1
                    status.write(f"❌ {category.display_name}: failed")
                    continue

                # Check serviceable location once
                if not location_checked:
                    location_checked = True
                    svc = extract_serviceable_location(html)
                    if svc:
                        svc_lat, svc_lon, svc_city = svc
                        dist = abs(svc_lat - lat) + abs(svc_lon - lon)
                        if dist > 0.1:
                            status.write(
                                f"📍 Blinkit resolved to {svc_city} "
                                f"({svc_lat:.4f}, {svc_lon:.4f})"
                            )
                        fetcher.update_location(svc_lat, svc_lon)
                        lat, lon = svc_lat, svc_lon

                products, next_url = extract_products_from_html(
                    html, category, lat, lon
                )
                all_products.extend(products)

                # Pagination
                page = 1
                referer = CATEGORY_URL.format(
                    slug=category.slug,
                    l1_id=category.l1_id,
                    l2_id=category.l2_id,
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

                pages_note = f" (+{page - 1} pages)" if page > 1 else ""
                status.write(
                    f"✅ {category.display_name}: "
                    f"{len(products)} products{pages_note}"
                )

        status.update(label="Scrape complete!", state="complete")
    except Exception as exc:
        status.update(label="Scrape failed", state="error")
        st.error(f"Error during scrape: {exc}")
        st.stop()

    # ── Deduplication ────────────────────────────────────────────────────
    seen_ids: set[str] = set()
    unique_products: list[dict] = []
    for p in all_products:
        vid = str(p.get("variant_id", ""))
        if vid and vid in seen_ids:
            continue
        seen_ids.add(vid)
        unique_products.append(p)

    duplicates = len(all_products) - len(unique_products)
    cats_scraped = total - categories_failed

    # ── Metrics ──────────────────────────────────────────────────────────
    st.subheader("Results")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Categories Scraped", cats_scraped)
    c2.metric("Categories Failed", categories_failed)
    c3.metric("Total Products", len(all_products))
    c4.metric("Unique Products", len(unique_products), delta=f"-{duplicates} dupes")

    if categories_failed > 0 and categories_failed / total > 0.5:
        st.warning(
            f"{categories_failed}/{total} categories failed. "
            "Blinkit may be blocking requests — try increasing the delay."
        )

    # ── Data table ───────────────────────────────────────────────────────
    if unique_products:
        import pandas as pd

        df = pd.DataFrame(unique_products, columns=CSV_FIELDS)
        st.dataframe(df, use_container_width=True, height=500)

        # ── CSV download ─────────────────────────────────────────────────
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unique_products)

        st.download_button(
            "Download CSV",
            data=buf.getvalue(),
            file_name="blinkit_products.csv",
            mime="text/csv",
        )
    else:
        st.info("No products found.")
else:
    st.markdown(
        "Configure location and categories in the sidebar, then click **Run Scrape**."
    )
