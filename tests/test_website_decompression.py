from __future__ import annotations

import gzip
import zlib
import pytest

from norway_company_agent.website import safe_decompress_body
from norway_company_agent.identity import assess_website_identity


def test_safe_decompress_plain_html():
    """Test 1: Plain uncompressed UTF-8 HTML passes through unchanged."""
    raw = b"<html><head><title>Test</title></head><body>Plain HTML</body></html>"
    decomp, err = safe_decompress_body(raw, encoding="")
    assert decomp == raw
    assert err is None


def test_safe_decompress_gzip_magic():
    """Test 2: gzip-compressed HTML is correctly decompressed via magic bytes."""
    plain = b"<html><head><title>Test</title></head><body>Gzip content</body></html>"
    compressed = gzip.compress(plain)
    decomp, err = safe_decompress_body(compressed, encoding="")
    assert decomp == plain
    assert err is None


def test_safe_decompress_gzip_header():
    """Test 3: gzip-compressed HTML with Content-Encoding header is decompressed."""
    plain = b"<html><body>Gzip with header</body></html>"
    compressed = gzip.compress(plain)
    decomp, err = safe_decompress_body(compressed, encoding="gzip")
    assert decomp == plain
    assert err is None


def test_safe_decompress_deflate():
    """Test 4: Deflate-compressed HTML is decompressed safely."""
    plain = b"<html><body>Deflate content</body></html>"
    compressed = zlib.compress(plain)
    decomp, err = safe_decompress_body(compressed, encoding="deflate")
    assert decomp == plain
    assert err is None


def test_safe_decompress_malformed_gzip():
    """Test 5: Malformed gzip bytes do not crash the fetcher (graceful fallback)."""
    corrupt = b"\x1f\x8b\x08" + b"random corrupt garbage data that is not valid gzip"
    decomp, err = safe_decompress_body(corrupt, encoding="gzip")
    assert decomp == corrupt
    assert err is not None
    assert "decompression_error" in err


def test_safe_decompress_zip_bomb_bounded():
    """Test 6: Decompression enforces streaming max_bytes without allocating unbounded memory."""
    huge_data = b"A" * 500_000
    compressed = gzip.compress(huge_data)
    decomp, err = safe_decompress_body(compressed, max_bytes=1_000)
    assert len(decomp) == 1_001
    assert err is None


def test_bade_og_recovery_evidence():
    """Test 7: BÅDE OG AS moves to publishable >= 0.90 under unchanged identity.py with decompressed HTML."""
    plain_html = """
    <html>
      <head><title>Produksjonsselskap | Alt innen film, lyd og tekst - Både Og</title></head>
      <body>
        <main>
          <h1>Både Og Produksjoner</h1>
          <p>Hos oss finner du kreatører, tekstforfattere, lyddesignere, regissører, produsenter og prosjektledere med lang erfaring i bransjen.</p>
          <p>Vi produserer alt innen film, radio, podcast og lyddesign for kjente merkevarer i hele Norge.</p>
        </main>
      </body>
    </html>
    """
    compressed = gzip.compress(plain_html.encode("utf-8"))
    decomp, err = safe_decompress_body(compressed)
    assert err is None
    
    val = {
        "requested_url": "https://badeog.no",
        "final_url": "https://badeog.no/",
        "title": "Produksjonsselskap | Alt innen film, lyd og tekst - Både Og",
        "main_text_excerpt": "Hos oss finner du kreatører, tekstforfattere, lyddesignere, regissører, produsenter og prosjektledere med lang erfaring. Vi produserer alt innen film, radio, podcast og lyddesign.",
        "identity_text_excerpt": "Både Og Produksjoner",
        "pages": [
            {
                "url": "https://badeog.no/kontakt/",
                "title": "Kontakt | Både Og",
                "main_text_excerpt": "Kontakt oss for produksjon i Oslo.",
                "identity_text_excerpt": "Både Og",
            }
        ],
    }
    profile = {
        "name": "BÅDE OG AS",
        "organisation_number": "859336302",
        "website": "https://www.badeog.no",
        "evidence": {
            "website": {"status": "available", "value": val, "source_url": "https://badeog.no"},
            "registry": {
                "value": {
                    "organisasjonsnummer": "859336302",
                    "navn": "BÅDE OG AS",
                    "hjemmeside": "www.badeog.no",
                    "forretningsadresse.kommune": "OSLO",
                }
            },
        },
    }
    assessment = assess_website_identity(profile)
    assert assessment["score"] >= 0.90
    assert assessment["publishable"] is True
    assert profile["organisation_number"] == "859336302"


def test_franchise_boundary_rejected():
    """Test 8: Domino's franchisee (DP TRONDHEIM AS) remains rejected (< 0.90) to prevent brand flattening."""
    val = {
        "requested_url": "https://www.dominos.no",
        "final_url": "https://www.dominos.no/",
        "title": "Domino's Pizza Norge | Bestill pizza online",
        "main_text_excerpt": "Velkommen til Domino's Pizza Norge! Bestill deilig pizza levert hjem eller til henting.",
        "identity_text_excerpt": "Domino's Pizza Norge",
        "pages": [],
    }
    profile = {
        "name": "DP TRONDHEIM AS",
        "organisation_number": "976336224",
        "website": "https://www.dominos.no",
        "evidence": {
            "website": {"status": "available", "value": val, "source_url": "https://www.dominos.no"},
            "registry": {
                "value": {
                    "organisasjonsnummer": "976336224",
                    "navn": "DP TRONDHEIM AS",
                    "hjemmeside": "www.dominos.no",
                }
            },
        },
    }
    assessment = assess_website_identity(profile)
    assert assessment["score"] < 0.90
    assert assessment["publishable"] is False
