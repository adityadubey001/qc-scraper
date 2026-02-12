"""Tests for pincode → lat/long resolution."""

import math
import pytest
from src.location import resolve_pincode, _resolve_pgeocode


class TestResolvePgeocode:
    """Test offline pincode resolution."""

    def test_valid_delhi_pincode(self):
        lat, lon = _resolve_pgeocode("110001")
        assert lat is not None and lon is not None
        # Delhi is roughly 28.6°N, 77.2°E
        assert 28.0 < lat < 29.0
        assert 76.5 < lon < 78.0

    def test_valid_mumbai_pincode(self):
        lat, lon = _resolve_pgeocode("400001")
        assert lat is not None and lon is not None
        # Mumbai is roughly 18.9°N, 72.8°E
        assert 18.0 < lat < 20.0
        assert 72.0 < lon < 73.5

    def test_invalid_pincode_returns_none(self):
        lat, lon = _resolve_pgeocode("000000")
        assert lat is None and lon is None


class TestResolvePincode:
    """Test the main resolve_pincode function."""

    def test_delhi(self):
        lat, lon = resolve_pincode("110001")
        assert 28.0 < lat < 29.0
        assert 76.5 < lon < 78.0

    def test_bangalore(self):
        lat, lon = resolve_pincode("560001")
        assert 12.0 < lat < 14.0
        assert 77.0 < lon < 78.0

    def test_invalid_raises(self, monkeypatch):
        # Mock geopy fallback to ensure it returns None (network-independent)
        monkeypatch.setattr(
            "src.location._resolve_geopy", lambda pincode: (None, None)
        )
        with pytest.raises(ValueError, match="Could not resolve"):
            resolve_pincode("000000")
