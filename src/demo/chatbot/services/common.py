"""Shared validated value types for contact details and vehicle references."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from ..knowledge import canonical_brand
from ..text import clean_text, normalize_email, normalize_us_phone, valid_name
from ..vin import validate_vin


class ServiceError(Exception):
    """Business-rule violation with a customer-safe message."""

    def __init__(self, message: str, *, code: str = "invalid_request", status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class VehicleRef(BaseModel):
    year: int | None = Field(default=None, ge=1950, le=2100)
    make: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=40)
    vin: str | None = None
    stock_number: str | None = Field(default=None, max_length=20)
    condition: Literal["new", "used", "cpo"] | None = None
    mileage: int | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("make")
    @classmethod
    def _make(cls, value: str | None) -> str | None:
        return canonical_brand(clean_text(value, multiline=False)) if value else None

    @field_validator("model", "stock_number")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return clean_text(value, multiline=False) or None if value else None

    @field_validator("vin")
    @classmethod
    def _vin(cls, value: str | None) -> str | None:
        if not value:
            return None
        check = validate_vin(value)
        if not check.valid:
            raise ValueError(check.reason)
        return check.vin


class ContactDetails(BaseModel):
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    consent_to_contact: bool

    @field_validator("first_name", "last_name")
    @classmethod
    def _name(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        value = clean_text(value, multiline=False)
        if not value:
            if info.field_name == "first_name":
                raise ValueError("first name is required")
            return None
        if not valid_name(value):
            raise ValueError("names may contain letters, spaces, apostrophes, periods and hyphens only")
        return value

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if not value:
            return None
        normalized = normalize_us_phone(value)
        if normalized is None:
            raise ValueError("enter a valid 10-digit US phone number")
        return normalized

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if not value:
            return None
        normalized = normalize_email(value)
        if normalized is None:
            raise ValueError("enter a valid email address")
        return normalized

    @model_validator(mode="after")
    def _reachable(self) -> ContactDetails:
        if not self.consent_to_contact:
            raise ValueError("the customer must agree to be contacted (consent_to_contact must be true)")
        if not (self.phone or self.email):
            raise ValueError("a phone number or an email address is required")
        return self
