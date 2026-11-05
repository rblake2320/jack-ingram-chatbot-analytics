"""VIN normalisation and validation (ISO 3779 / 49 CFR 565 check digit)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TRANSLITERATION = {
    **{str(d): d for d in range(10)},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}  # fmt: skip
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
_ALLOWED = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


@dataclass(frozen=True)
class VinCheck:
    valid: bool
    vin: str
    reason: str | None = None


def normalize_vin(raw: str) -> str:
    return re.sub(r"[\s\-]", "", raw or "").upper()


def check_digit(vin: str) -> str:
    total = sum(_TRANSLITERATION[ch] * weight for ch, weight in zip(vin, _WEIGHTS, strict=True))
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def validate_vin(raw: str) -> VinCheck:
    vin = normalize_vin(raw)
    if len(vin) != 17:
        return VinCheck(False, vin, "A VIN has exactly 17 characters.")
    if not _ALLOWED.match(vin):
        return VinCheck(False, vin, "VINs never contain the letters I, O or Q, or any symbols.")
    if check_digit(vin) != vin[8]:
        return VinCheck(False, vin, "The 9th character (check digit) does not match; please re-check the VIN.")
    return VinCheck(True, vin)


VIN_PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)


def find_vin(text: str) -> str | None:
    for match in VIN_PATTERN.finditer(text or ""):
        candidate = match.group(0).upper()
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            return candidate
    return None
