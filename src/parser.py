"""Parse Blinkit HTML/JSON responses into flat product dictionaries."""

import json
import re
from datetime import date

from .categories import Category


def extract_products_from_html(
    html: str, category: Category, lat: float, lon: float
) -> tuple[list[dict], str | None]:
    """Extract product data from a Blinkit category page HTML response.

    Returns (products, next_url) where next_url is the pagination URL or None.
    """
    products = []
    next_url = None

    # Primary: extract from window.grofers.PRELOADED_STATE
    preloaded = _extract_preloaded_state(html)
    if preloaded:
        products, next_url = _parse_preloaded_state(preloaded, category, lat, lon)

    # Fallback: try __NEXT_DATA__ script tag
    if not products:
        next_data = _extract_next_data(html)
        if next_data:
            products = _parse_next_data(next_data, category, lat, lon)

    return products, next_url


def extract_serviceable_location(html: str) -> tuple[float, float, str] | None:
    """Extract Blinkit's serviceable location from the page response.

    Returns (lat, lon, city_name) or None if not found.
    Blinkit resolves user coordinates to the nearest serviceable location
    stored in PRELOADED_STATE → data.location.coords.
    """
    preloaded = _extract_preloaded_state(html)
    if not preloaded:
        return None

    coords = preloaded.get("data", {}).get("location", {}).get("coords", {})
    lat = coords.get("lat")
    lon = coords.get("lon")
    city = coords.get("cityName", "")

    if lat is not None and lon is not None:
        return float(lat), float(lon), city
    return None


def _extract_preloaded_state(html: str) -> dict | None:
    """Extract the PRELOADED_STATE JSON from Blinkit's page."""
    idx = html.find("PRELOADED_STATE")
    if idx == -1:
        return None

    eq_idx = html.find("=", idx)
    if eq_idx == -1:
        return None

    json_start = html.find("{", eq_idx)
    if json_start == -1:
        return None

    try:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(html, json_start)
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_preloaded_state(
    data: dict, category: Category, lat: float, lon: float
) -> tuple[list[dict], str | None]:
    """Parse products from Blinkit's PRELOADED_STATE structure.

    Path: ui.plpContainer.feedData.snippets[].data
    """
    products = []
    next_url = None
    today = date.today().isoformat()

    ui = data.get("ui", {})
    plp = ui.get("plpContainer", {})
    feed_data = plp.get("feedData", {})

    # Extract pagination
    pagination = feed_data.get("pagination", {})
    if isinstance(pagination, dict):
        next_url = pagination.get("next_url")

    # Extract products from snippets
    snippets = feed_data.get("snippets", [])
    if isinstance(snippets, list):
        for snippet in snippets:
            if not isinstance(snippet, dict):
                continue
            snippet_data = snippet.get("data", {})
            if not isinstance(snippet_data, dict):
                continue
            # Only process items with identity.id (actual products)
            identity = snippet_data.get("identity", {})
            if isinstance(identity, dict) and "id" in identity:
                product = _normalize_blinkit_product(
                    snippet_data, category, lat, lon, today
                )
                if product:
                    products.append(product)

    return products, next_url


def _normalize_blinkit_product(
    item: dict, category: Category, lat: float, lon: float, today: str
) -> dict | None:
    """Normalize a Blinkit product from PRELOADED_STATE format.

    Known fields:
      identity.id, name.text, normal_price.text (₹prefix),
      brand_name.text, variant.text, image.url,
      inventory, merchant_id, group_id, product_id,
      is_sold_out, atc_action.add_to_cart.cart_item.*
    """
    product_id = item.get("identity", {}).get("id", "")
    if not product_id:
        return None

    # Name
    name = _get_text(item, "name")

    # Variant (e.g. "1 ltr", "500 ml")
    variant = _get_text(item, "variant")
    if variant and name and variant not in name:
        name = f"{name} {variant}"

    # Price — strip ₹ symbol
    selling_price = _get_text(item, "normal_price").replace("₹", "").strip()

    # MRP
    mrp = _get_text(item, "mrp").replace("₹", "").strip()

    # Brand
    brand = _get_text(item, "brand_name")

    # Image
    image_url = ""
    img_obj = item.get("image", {})
    if isinstance(img_obj, dict):
        image_url = img_obj.get("url", "")

    # Fallback image from media_container
    if not image_url:
        media = item.get("media_container", {})
        if isinstance(media, dict):
            media_items = media.get("items", [])
            if media_items and isinstance(media_items[0], dict):
                image_url = media_items[0].get("image", {}).get("url", "")

    # Fallback image from atc_action
    if not image_url:
        atc = item.get("atc_action", {})
        if isinstance(atc, dict):
            cart_item = atc.get("add_to_cart", {}).get("cart_item", {})
            if isinstance(cart_item, dict):
                image_url = cart_item.get("image_url", "")

    # Store/merchant ID
    store_id = item.get("merchant_id", "")

    # Inventory & stock
    inventory = item.get("inventory", "")
    if isinstance(inventory, dict):
        inventory = ""

    is_sold_out = item.get("is_sold_out", False)
    in_stock = 0 if is_sold_out else (1 if inventory else 1)

    return {
        "date": today,
        "l1_category": category.l1_name,
        "l1_category_id": category.l1_id,
        "l2_category": category.l2_name,
        "l2_category_id": category.l2_id,
        "store_id": store_id,
        "variant_id": product_id,
        "variant_name": name,
        "group_id": item.get("group_id", ""),
        "product_id": item.get("product_id", product_id),
        "selling_price": selling_price,
        "mrp": mrp,
        "in_stock": in_stock,
        "inventory": inventory,
        "is_sponsored": "",
        "image_url": image_url,
        "brand_id": "",
        "brand": brand,
        "latitude": lat,
        "longitude": lon,
    }


def _get_text(item: dict, key: str) -> str:
    """Extract .text from a Blinkit styled text object like {text, color, font}."""
    obj = item.get(key, {})
    if isinstance(obj, dict):
        return obj.get("text", "")
    if isinstance(obj, str):
        return obj
    return ""


# --- Fallback: __NEXT_DATA__ parsing (kept for compatibility) ---

def _extract_next_data(html: str) -> dict | None:
    """Extract the __NEXT_DATA__ JSON from the page."""
    pattern = r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>'
    match = re.search(pattern, html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None


def _parse_next_data(
    data: dict, category: Category, lat: float, lon: float
) -> list[dict]:
    """Parse products from __NEXT_DATA__ JSON structure."""
    products = []
    today = date.today().isoformat()

    page_props = data.get("props", {}).get("pageProps", {})
    product_lists = []

    if "products" in page_props:
        product_lists.append(page_props["products"])

    cat_data = page_props.get("categoryData", {})
    if "products" in cat_data:
        product_lists.append(cat_data["products"])

    for product_list in product_lists:
        if not isinstance(product_list, list):
            continue
        for item in product_list:
            product = _normalize_flat_product(item, category, lat, lon, today)
            if product:
                products.append(product)

    return products


def _normalize_flat_product(
    item: dict, category: Category, lat: float, lon: float, today: str
) -> dict | None:
    """Normalize a flat-format product dict (for __NEXT_DATA__ or JSON API)."""
    if not isinstance(item, dict):
        return None

    variant_id = item.get("variant_id") or item.get("id") or item.get("variant")
    if not variant_id:
        return None

    selling_price = (
        item.get("selling_price")
        or item.get("price")
        or item.get("offer_price")
        or ""
    )
    mrp = item.get("mrp") or item.get("max_price") or ""

    name = (
        item.get("variant_name")
        or item.get("name")
        or item.get("product_name")
        or item.get("title")
        or ""
    )

    in_stock = item.get("in_stock", item.get("is_in_stock", True))
    if isinstance(in_stock, bool):
        in_stock = 1 if in_stock else 0

    inventory = item.get("inventory", item.get("qty", item.get("quantity", "")))
    image_url = item.get("image_url") or item.get("image") or item.get("thumbnail") or ""

    return {
        "date": today,
        "l1_category": category.l1_name,
        "l1_category_id": category.l1_id,
        "l2_category": category.l2_name,
        "l2_category_id": category.l2_id,
        "store_id": item.get("store_id", ""),
        "variant_id": variant_id,
        "variant_name": name,
        "group_id": item.get("group_id", item.get("grp_id", "")),
        "product_id": item.get("product_id", item.get("prod_id", "")),
        "selling_price": selling_price,
        "mrp": mrp,
        "in_stock": in_stock,
        "inventory": inventory,
        "is_sponsored": item.get("is_sponsored", item.get("sponsored", 0)),
        "image_url": image_url,
        "brand_id": item.get("brand_id", ""),
        "brand": item.get("brand", item.get("brand_name", "")),
        "latitude": lat,
        "longitude": lon,
    }


def parse_pagination_response(
    data: dict, category: Category, lat: float, lon: float
) -> tuple[list[dict], str | None]:
    """Parse products from Blinkit's pagination API response.

    The pagination API (POST /v1/layout/listing_widgets) returns:
    {"is_success": true, "response": {"snippets": [...], "pagination": {...}}}

    Snippets use the same format as PRELOADED_STATE snippets.
    """
    products = []
    next_url = None
    today = date.today().isoformat()

    if not isinstance(data, dict) or not data.get("is_success"):
        return products, next_url

    response = data.get("response", {})
    if not isinstance(response, dict):
        return products, next_url

    # Extract pagination
    pagination = response.get("pagination", {})
    if isinstance(pagination, dict):
        next_url = pagination.get("next_url")

    # Extract products from snippets (same format as PRELOADED_STATE)
    snippets = response.get("snippets", [])
    if isinstance(snippets, list):
        for snippet in snippets:
            if not isinstance(snippet, dict):
                continue
            snippet_data = snippet.get("data", {})
            if not isinstance(snippet_data, dict):
                continue
            identity = snippet_data.get("identity", {})
            if isinstance(identity, dict) and "id" in identity:
                product = _normalize_blinkit_product(
                    snippet_data, category, lat, lon, today
                )
                if product:
                    products.append(product)

    return products, next_url


def parse_products_from_json(
    data: dict | list, category: Category, lat: float, lon: float
) -> list[dict]:
    """Parse products directly from a JSON API response (non-HTML)."""
    products = []
    today = date.today().isoformat()

    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("products", "data", "items", "results", "objects"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items:
        product = _normalize_flat_product(item, category, lat, lon, today)
        if product:
            products.append(product)

    return products
