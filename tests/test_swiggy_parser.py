"""Tests for the Swiggy Instamart parser."""

import pytest

from src.swiggy.parser import (
    extract_products_from_response,
    normalize_swiggy_product,
    _find_snippets,
    _strip_currency,
)
from src.swiggy.categories import (
    SwiggyCategory,
    parse_categories_from_links,
    _extract_category_name,
    filter_categories,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SNIPPET = {
    "identity": {"id": "12345"},
    "name": {"text": "Amul Taaza Toned Milk"},
    "variant": {"text": "500 ml"},
    "normal_price": {"text": "₹27"},
    "mrp": {"text": "₹29"},
    "brand_name": {"text": "Amul"},
    "image": {"url": "https://img.swiggy.com/milk.jpg"},
    "merchant_id": "store_99",
    "inventory": 50,
    "is_sold_out": False,
    "group_id": "grp_100",
    "product_id": "prod_12345",
}

SAMPLE_SNIPPET_FLAT = {
    "id": "67890",
    "name": "Britannia Bread",
    "price": "45",
    "final_price": "40",
    "brand": "Britannia",
    "image_url": "https://img.swiggy.com/bread.jpg",
    "out_of_stock": False,
    "store_id": "store_77",
    "weight": "400g",
}

SAMPLE_SNIPPET_SOLD_OUT = {
    "identity": {"id": "99999"},
    "name": {"text": "Unavailable Product"},
    "normal_price": {"text": "₹100"},
    "mrp": {"text": "₹120"},
    "is_sold_out": True,
}


# ---------------------------------------------------------------------------
# normalize_swiggy_product
# ---------------------------------------------------------------------------

class TestNormalizeSwiggyProduct:
    def test_nested_format(self):
        row = normalize_swiggy_product(SAMPLE_SNIPPET, "Dairy", 19.0, 73.0, "2025-01-15")
        assert row is not None
        assert row["variant_id"] == "12345"
        assert row["variant_name"] == "Amul Taaza Toned Milk 500 ml"
        assert row["selling_price"] == "27"
        assert row["mrp"] == "29"
        assert row["brand"] == "Amul"
        assert row["in_stock"] == 1
        assert row["image_url"] == "https://img.swiggy.com/milk.jpg"
        assert row["l1_category"] == "Dairy"
        assert row["store_id"] == "store_99"
        assert row["latitude"] == 19.0
        assert row["longitude"] == 73.0
        assert row["date"] == "2025-01-15"

    def test_flat_format(self):
        row = normalize_swiggy_product(SAMPLE_SNIPPET_FLAT, "Bakery", 19.0, 73.0, "2025-01-15")
        assert row is not None
        assert row["variant_id"] == "67890"
        assert row["variant_name"] == "Britannia Bread 400g"
        assert row["selling_price"] == "40"
        assert row["mrp"] == "45"
        assert row["brand"] == "Britannia"
        assert row["in_stock"] == 1

    def test_sold_out(self):
        row = normalize_swiggy_product(SAMPLE_SNIPPET_SOLD_OUT, "Other", 19.0, 73.0, "2025-01-15")
        assert row is not None
        assert row["in_stock"] == 0

    def test_missing_id_returns_none(self):
        row = normalize_swiggy_product({"name": "No ID product"}, "Cat", 0, 0, "2025-01-15")
        assert row is None

    def test_empty_dict_returns_none(self):
        row = normalize_swiggy_product({}, "Cat", 0, 0, "2025-01-15")
        assert row is None

    def test_weight_not_duplicated_in_name(self):
        snippet = {
            "identity": {"id": "111"},
            "name": {"text": "Milk 500 ml"},
            "variant": {"text": "500 ml"},
        }
        row = normalize_swiggy_product(snippet, "Dairy", 0, 0, "2025-01-15")
        assert row["variant_name"] == "Milk 500 ml"  # Not duplicated

    def test_default_date(self):
        row = normalize_swiggy_product(SAMPLE_SNIPPET, "Dairy", 19.0, 73.0)
        assert row is not None
        assert row["date"]  # Should be today's date


# ---------------------------------------------------------------------------
# extract_products_from_response
# ---------------------------------------------------------------------------

class TestExtractProductsFromResponse:
    def test_nested_response_snippets(self):
        data = {
            "response": {
                "snippets": [
                    {"data": SAMPLE_SNIPPET},
                    {"data": SAMPLE_SNIPPET_FLAT},
                ]
            }
        }
        products = extract_products_from_response(data, "Dairy", 19.0, 73.0)
        assert len(products) == 2

    def test_data_response_snippets(self):
        data = {
            "data": {
                "response": {
                    "snippets": [
                        {"data": SAMPLE_SNIPPET},
                    ]
                }
            }
        }
        products = extract_products_from_response(data, "Dairy", 19.0, 73.0)
        assert len(products) == 1

    def test_direct_snippets(self):
        data = {
            "snippets": [SAMPLE_SNIPPET, SAMPLE_SNIPPET_FLAT],
        }
        products = extract_products_from_response(data, "Dairy", 19.0, 73.0)
        assert len(products) == 2

    def test_empty_response(self):
        products = extract_products_from_response({}, "Dairy", 19.0, 73.0)
        assert products == []

    def test_no_product_data(self):
        data = {"response": {"snippets": [{"data": {"not": "a product"}}]}}
        products = extract_products_from_response(data, "Dairy", 19.0, 73.0)
        assert products == []


# ---------------------------------------------------------------------------
# _find_snippets
# ---------------------------------------------------------------------------

class TestFindSnippets:
    def test_finds_nested_snippets(self):
        data = {"data": {"response": {"snippets": [{"identity": {"id": "1"}}]}}}
        result = _find_snippets(data)
        assert len(result) == 1

    def test_finds_direct_snippets(self):
        data = {"snippets": [{"identity": {"id": "1"}}]}
        result = _find_snippets(data)
        assert len(result) == 1

    def test_empty_dict(self):
        assert _find_snippets({}) == []


# ---------------------------------------------------------------------------
# _strip_currency
# ---------------------------------------------------------------------------

class TestStripCurrency:
    def test_rupee_symbol(self):
        assert _strip_currency("₹29") == "29"

    def test_rs_prefix(self):
        assert _strip_currency("Rs 45.00") == "45.00"

    def test_none(self):
        assert _strip_currency(None) == ""

    def test_numeric(self):
        assert _strip_currency(27) == "27"

    def test_comma_separated(self):
        assert _strip_currency("₹1,299") == "1299"


# ---------------------------------------------------------------------------
# Category parsing
# ---------------------------------------------------------------------------

class TestCategoryParsing:
    def test_extract_category_name(self):
        url = "/instamart/category-listing?categoryName=Dairy+%26+Breakfast&custom_back=true"
        assert _extract_category_name(url) == "Dairy & Breakfast"

    def test_extract_category_name_simple(self):
        url = "/instamart/category-listing?categoryName=Fruits"
        assert _extract_category_name(url) == "Fruits"

    def test_extract_no_param(self):
        assert _extract_category_name("/instamart/some-page") == ""

    def test_parse_links(self):
        links = [
            {"href": "/instamart/category-listing?categoryName=Dairy", "text": "Dairy"},
            {"href": "/instamart/category-listing?categoryName=Fruits", "text": "Fruits"},
            {"href": "/instamart/other-page", "text": "Other"},
        ]
        cats = parse_categories_from_links(links)
        assert len(cats) == 2
        assert cats[0].name == "Dairy"
        assert cats[1].name == "Fruits"

    def test_parse_links_dedup(self):
        links = [
            {"href": "/instamart/category-listing?categoryName=Dairy", "text": "Dairy"},
            {"href": "/instamart/category-listing?categoryName=Dairy", "text": "Dairy Again"},
        ]
        cats = parse_categories_from_links(links)
        assert len(cats) == 1

    def test_filter_categories(self):
        cats = [
            SwiggyCategory("Dairy & Breakfast", "Dairy & Breakfast"),
            SwiggyCategory("Fruits & Vegetables", "Fruits & Vegetables"),
            SwiggyCategory("Snacks", "Snacks"),
        ]
        filtered = filter_categories(cats, "dairy")
        assert len(filtered) == 1
        assert filtered[0].name == "Dairy & Breakfast"

    def test_filter_none_returns_all(self):
        cats = [
            SwiggyCategory("A", "A"),
            SwiggyCategory("B", "B"),
        ]
        assert len(filter_categories(cats, None)) == 2

    def test_category_url(self):
        cat = SwiggyCategory("Dairy & Breakfast", "Dairy & Breakfast")
        assert "categoryName=" in cat.url
        assert "Dairy" in cat.url
