"""Tests for normalization helpers."""

from app.ingest.normalizer import normalize_metadata, normalize_text_fields


def test_normalize_text_fields_extracts_expected_tokens():
    text = (
        "Livraison prévue le 2026-03-25. Révision REF-ABC123.\n"
        "Montant: EUR 1 250,50 et $99.99. Date alternative 25/03/2026."
    )
    result = normalize_text_fields(text)

    assert "2026-03-25" in result.dates
    assert "25/03/2026" in result.dates
    assert "1250.50" in result.amounts
    assert "99.99" in result.amounts
    assert "REF-ABC123" in result.references


def test_normalize_metadata_cleans_keys_and_values():
    metadata = {
        " Author Name ": "  Jean  ",
        "Empty": "   ",
        "NoneValue": None,
        "Pages Count": 12,
    }

    normalized = normalize_metadata(metadata)

    assert normalized["author_name"] == "Jean"
    assert normalized["pages_count"] == 12
    assert "empty" not in normalized
    assert "nonevalue" not in normalized

