"""Tests for deterministic conflict detectors."""

from app.detect.deterministic import (
    AmountConflictDetector,
    DateConflictDetector,
    ReferenceMismatchDetector,
)


def test_date_conflict_detector():
    detector = DateConflictDetector()
    conflicts = detector.detect("Livraison le 2026-03-25", "Livraison confirmée 2026-04-01")
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "date_conflict"


def test_amount_conflict_detector():
    detector = AmountConflictDetector()
    conflicts = detector.detect("Montant: 1200 EUR", "Montant validé: 900 EUR")
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "amount_conflict"


def test_reference_mismatch_detector():
    detector = ReferenceMismatchDetector()
    conflicts = detector.detect("Contrat REF-AAA01", "Contrat REF-BBB02")
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "reference_mismatch"

