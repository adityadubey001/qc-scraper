"""Normalize Swiggy Instamart product data to the standard 20-column CSV schema."""

import logging
from datetime import date

log = logging.getLogger(__name__)


def normalize_swiggy_product(
    snippet_data: dict,
    category_name: str,
    lat: float,
    lon: float,
    today: str | None = None,
) -> dict | None:
    """Normalize a single Swiggy Instamart product snippet to a CSV row dict.

    Returns None if the snippet has no usable product ID.
    """
    if today is None:
        today = date.today().isoformat()

    # Product identity — try several known paths
    product_id = _deep_get(snippet_data, "identity", "id") or ""
    if not product_id:
        product_id = snippet_data.get("product_id", snippet_data.get("id", ""))
    if not product_id:
        return None

    # Name — may include variant/weight info
    name = _deep_get(snippet_data, "name", "text") or snippet_data.get("name", "")
    weight = (
        _deep_get(snippet_data, "variant", "text")
        or snippet_data.get("weight", "")
        or snippet_data.get("quantity", "")
    )
    if weight and str(weight) not in str(name):
        name = f"{name} {weight}".strip()

    # Pricing
    selling_price = (
        _deep_get(snippet_data, "normal_price", "text")
        or snippet_data.get("final_price", "")
        or snippet_data.get("offer_price", "")
        or snippet_data.get("price", "")
    )
    mrp = (
        _deep_get(snippet_data, "mrp", "text")
        or snippet_data.get("mrp", "")
        or snippet_data.get("price", "")
    )
    selling_price = _strip_currency(selling_price)
    mrp = _strip_currency(mrp)

    # Image — try multiple paths
    image_url = (
        _deep_get(snippet_data, "image", "url")
        or snippet_data.get("image_url", "")
        or snippet_data.get("img_url", "")
    )

    # Stock
    is_sold_out = snippet_data.get("is_sold_out", snippet_data.get("out_of_stock", False))
    in_stock = 0 if is_sold_out else 1

    # Brand
    brand = (
        _deep_get(snippet_data, "brand_name", "text")
        or snippet_data.get("brand", "")
    )

    # Store / merchant
    store_id = snippet_data.get("store_id", snippet_data.get("merchant_id", ""))

    return {
        "date": today,
        "l1_category": category_name,
        "l1_category_id": "",
        "l2_category": "",
        "l2_category_id": "",
        "store_id": store_id,
        "variant_id": str(product_id),
        "variant_name": name,
        "group_id": snippet_data.get("group_id", ""),
        "product_id": snippet_data.get("product_id", str(product_id)),
        "selling_price": selling_price,
        "mrp": mrp,
        "in_stock": in_stock,
        "inventory": snippet_data.get("inventory", ""),
        "is_sponsored": "",
        "image_url": image_url,
        "brand_id": "",
        "brand": brand,
        "latitude": lat,
        "longitude": lon,
    }


def extract_products_from_response(
    json_data: dict,
    category_name: str,
    lat: float,
    lon: float,
) -> list[dict]:
    """Extract and normalize products from an intercepted XHR JSON response.

    Walks through multiple possible response structures to find product
    snippet arrays.
    """
    products: list[dict] = []
    snippets = _find_snippets(json_data)

    for snippet in snippets:
        # Snippet may be the data directly or wrapped in {"data": {...}}
        data = snippet.get("data", snippet) if isinstance(snippet, dict) else snippet
        if not isinstance(data, dict):
            continue
        row = normalize_swiggy_product(data, category_name, lat, lon)
        if row:
            products.append(row)

    if products:
        log.debug("Extracted %d products from response", len(products))
    return products


def _find_snippets(data: dict) -> list:
    """Recursively search for product snippet arrays in a JSON response."""
    if not isinstance(data, dict):
        return []

    # Direct snippets array at various nesting depths
    for key_path in [
        ("response", "snippets"),
        ("data", "response", "snippets"),
        ("data", "snippets"),
        ("snippets",),
        ("data", "widgets",),
        ("widgets",),
    ]:
        node = data
        for key in key_path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = None
                break
        if isinstance(node, list) and node:
            return node

    # Try to find product-like objects in any list value
    for value in data.values():
        if isinstance(value, list) and len(value) > 0:
            first = value[0]
            if isinstance(first, dict) and (
                _deep_get(first, "data", "identity", "id")
                or _deep_get(first, "identity", "id")
                or first.get("product_id")
                or first.get("id")
            ):
                return value

    # Recurse one level into dict values
    for value in data.values():
        if isinstance(value, dict):
            found = _find_snippets(value)
            if found:
                return found

    return []


def _deep_get(d: dict, *keys: str):
    """Safely traverse nested dicts."""
    node = d
    for key in keys:
        if isinstance(node, dict):
            node = node.get(key)
        else:
            return None
    return node


def _strip_currency(value) -> str:
    """Strip currency symbols and whitespace from a price string."""
    if value is None:
        return ""
    s = str(value).strip()
    for ch in ("₹", "$", "Rs", "Rs.", "INR", ","):
        s = s.replace(ch, "")
    return s.strip()
