"""Tests for HTML/JSON response parsing."""

import json
import os
from datetime import date

import pytest

from src.categories import Category
from src.parser import (
    _normalize_flat_product,
    _normalize_blinkit_product,
    _parse_preloaded_state,
    _extract_preloaded_state,
    extract_products_from_html,
    parse_pagination_response,
    parse_products_from_json,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def sample_category():
    return Category(
        l1_name="Dairy Bread & Eggs",
        l1_id=14,
        slug="milk",
        l2_name="Milk",
        l2_id=922,
    )


@pytest.fixture
def sample_next_data():
    with open(os.path.join(FIXTURES_DIR, "sample_response.json")) as f:
        return json.load(f)


class TestPreloadedState:
    """Test parsing Blinkit's actual PRELOADED_STATE format."""

    def test_extract_preloaded_state(self):
        html = '''<script>window.grofers = {};
            window.grofers.PRELOADED_STATE = {"ui": {"plpContainer": {"feedData": {"snippets": []}}}};
            window.grofers.CONFIG = {};
        </script>'''
        data = _extract_preloaded_state(html)
        assert data is not None
        assert "ui" in data

    def test_extract_preloaded_state_missing(self):
        html = "<html><body>No data here</body></html>"
        data = _extract_preloaded_state(html)
        assert data is None

    def test_parse_preloaded_products(self, sample_category):
        data = {
            "ui": {
                "plpContainer": {
                    "feedData": {
                        "snippets": [
                            {
                                "data": {
                                    "identity": {"id": "561270"},
                                    "name": {"text": "Amul Taaza Toned Milk"},
                                    "variant": {"text": "1 ltr"},
                                    "normal_price": {"text": "₹57"},
                                    "mrp": {},
                                    "brand_name": {"text": "Amul"},
                                    "inventory": 12,
                                    "merchant_id": 35792,
                                    "group_id": 2056959,
                                    "product_id": 561270,
                                    "image": {"url": "https://cdn.grofers.com/milk.png"},
                                    "is_sold_out": False,
                                }
                            },
                            {
                                "data": {
                                    "identity": {"id": "561271"},
                                    "name": {"text": "Mother Dairy Full Cream Milk"},
                                    "variant": {"text": "500 ml"},
                                    "normal_price": {"text": "₹34"},
                                    "mrp": {"text": "₹36"},
                                    "brand_name": {"text": "Mother Dairy"},
                                    "inventory": 5,
                                    "merchant_id": 35792,
                                    "image": {"url": "https://cdn.grofers.com/md.png"},
                                    "is_sold_out": False,
                                }
                            },
                        ],
                        "pagination": {
                            "next_url": "/v1/layout/listing_widgets?offset=30"
                        },
                    }
                }
            }
        }
        products, next_url = _parse_preloaded_state(data, sample_category, 19.36, 73.33)
        assert len(products) == 2
        assert next_url == "/v1/layout/listing_widgets?offset=30"

        milk = products[0]
        assert milk["variant_id"] == "561270"
        assert milk["variant_name"] == "Amul Taaza Toned Milk 1 ltr"
        assert milk["selling_price"] == "57"
        assert milk["brand"] == "Amul"
        assert milk["store_id"] == 35792
        assert milk["inventory"] == 12
        assert milk["in_stock"] == 1
        assert milk["image_url"] == "https://cdn.grofers.com/milk.png"
        assert milk["l1_category"] == "Dairy Bread & Eggs"
        assert milk["l2_category_id"] == 922

        md = products[1]
        assert md["mrp"] == "36"
        assert "500 ml" in md["variant_name"]

    def test_sold_out_product(self, sample_category):
        data = {
            "ui": {
                "plpContainer": {
                    "feedData": {
                        "snippets": [
                            {
                                "data": {
                                    "identity": {"id": "999"},
                                    "name": {"text": "Out of stock item"},
                                    "normal_price": {"text": "₹100"},
                                    "is_sold_out": True,
                                    "inventory": 0,
                                }
                            },
                        ],
                        "pagination": {},
                    }
                }
            }
        }
        products, next_url = _parse_preloaded_state(data, sample_category, 19.36, 73.33)
        assert len(products) == 1
        assert products[0]["in_stock"] == 0
        assert next_url is None

    def test_full_html_extraction(self, sample_category):
        """Test extract_products_from_html with PRELOADED_STATE embedded in HTML."""
        preloaded = {
            "ui": {
                "plpContainer": {
                    "feedData": {
                        "snippets": [
                            {
                                "data": {
                                    "identity": {"id": "123"},
                                    "name": {"text": "Test Milk"},
                                    "normal_price": {"text": "₹50"},
                                }
                            }
                        ],
                        "pagination": {},
                    }
                }
            }
        }
        html = f'''<html><script>
        window.grofers = {{}};
        window.grofers.PRELOADED_STATE = {json.dumps(preloaded)};
        </script></html>'''
        products, next_url = extract_products_from_html(html, sample_category, 19.36, 73.33)
        assert len(products) == 1
        assert products[0]["variant_name"] == "Test Milk"


class TestNextDataFallback:
    """Test __NEXT_DATA__ fallback parsing."""

    def test_extracts_from_next_data_script(self, sample_next_data, sample_category):
        html = (
            '<html><body>'
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(sample_next_data)
            + '</script></body></html>'
        )
        products, _ = extract_products_from_html(html, sample_category, 28.6, 77.2)
        assert len(products) == 3

    def test_product_fields(self, sample_next_data, sample_category):
        html = (
            '<html><body>'
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(sample_next_data)
            + '</script></body></html>'
        )
        products, _ = extract_products_from_html(html, sample_category, 28.6, 77.2)
        milk = products[0]
        assert milk["variant_id"] == 10001
        assert milk["variant_name"] == "Amul Taaza Toned Fresh Milk 500 ml"
        assert milk["selling_price"] == 27.0

    def test_empty_html_returns_empty(self, sample_category):
        products, _ = extract_products_from_html("<html></html>", sample_category, 28.6, 77.2)
        assert products == []


class TestNormalizeFlatProduct:
    def test_minimal_product(self, sample_category):
        today = date.today().isoformat()
        raw = {"variant_id": 999, "name": "Test Product", "price": 10.0}
        result = _normalize_flat_product(raw, sample_category, 28.6, 77.2, today)
        assert result is not None
        assert result["variant_id"] == 999

    def test_missing_id_returns_none(self, sample_category):
        today = date.today().isoformat()
        raw = {"name": "No ID product"}
        result = _normalize_flat_product(raw, sample_category, 28.6, 77.2, today)
        assert result is None


class TestPaginationResponse:
    """Test parsing pagination API responses (POST /v1/layout/listing_widgets)."""

    def test_parse_pagination_products(self, sample_category):
        data = {
            "is_success": True,
            "response": {
                "snippets": [
                    {
                        "data": {
                            "identity": {"id": "26915"},
                            "name": {"text": "Go Daily Milk"},
                            "normal_price": {"text": "₹68"},
                            "brand_name": {"text": "Go"},
                            "inventory": 8,
                            "merchant_id": 36912,
                            "is_sold_out": False,
                        }
                    },
                ],
                "pagination": {
                    "next_url": "/v1/layout/listing_widgets?offset=45"
                },
            },
        }
        products, next_url = parse_pagination_response(data, sample_category, 19.36, 73.33)
        assert len(products) == 1
        assert products[0]["variant_id"] == "26915"
        assert products[0]["variant_name"] == "Go Daily Milk"
        assert products[0]["selling_price"] == "68"
        assert next_url == "/v1/layout/listing_widgets?offset=45"

    def test_pagination_no_more_pages(self, sample_category):
        data = {
            "is_success": True,
            "response": {
                "snippets": [
                    {
                        "data": {
                            "identity": {"id": "100"},
                            "name": {"text": "Last Product"},
                            "normal_price": {"text": "₹25"},
                        }
                    },
                ],
                "pagination": {},
            },
        }
        products, next_url = parse_pagination_response(data, sample_category, 19.36, 73.33)
        assert len(products) == 1
        assert next_url is None

    def test_pagination_failure(self, sample_category):
        data = {"is_success": False, "response": {}}
        products, next_url = parse_pagination_response(data, sample_category, 19.36, 73.33)
        assert products == []
        assert next_url is None

    def test_pagination_empty_snippets(self, sample_category):
        data = {
            "is_success": True,
            "response": {"snippets": [], "pagination": {}},
        }
        products, next_url = parse_pagination_response(data, sample_category, 19.36, 73.33)
        assert products == []


class TestParseJson:
    def test_parse_list(self, sample_category):
        data = [
            {"variant_id": 1, "name": "A", "price": 10},
            {"variant_id": 2, "name": "B", "price": 20},
        ]
        products = parse_products_from_json(data, sample_category, 28.6, 77.2)
        assert len(products) == 2

    def test_parse_wrapped_dict(self, sample_category):
        data = {"products": [{"variant_id": 1, "name": "A", "price": 10}]}
        products = parse_products_from_json(data, sample_category, 28.6, 77.2)
        assert len(products) == 1
