"""Shared observation contract and cross-artifact validation."""

from .compare import compare_documents
from .model import (
    DOCUMENT_SCHEMA,
    VALIDATION_SCHEMA,
    ConversionError,
    claim,
    document,
    entity,
    evidence,
    finding,
    load_document,
    validate_document,
)

__all__ = [
    "DOCUMENT_SCHEMA",
    "VALIDATION_SCHEMA",
    "ConversionError",
    "claim",
    "compare_documents",
    "document",
    "entity",
    "evidence",
    "finding",
    "load_document",
    "validate_document",
]

__version__ = "0.1.0"
