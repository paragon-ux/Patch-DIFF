"""Typed PDCP parse models for deterministic runtime phases."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


OPTIONAL_DISAMBIGUATION_FIELDS = frozenset(
    {
        "anchor_before",
        "anchor_after",
        "occurrence_index",
    }
)
VALID_RISK_VALUES = frozenset({"low", "medium", "high"})


@dataclass(frozen=True, slots=True)
class PDCPHeader:
    protocol_version: str
    target_file_id: str
    target_type: str
    target_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PDCPManifest:
    fields: Mapping[str, str]

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "PDCPManifest":
        return cls(fields=MappingProxyType(dict(fields)))

    @property
    def change_id(self) -> str:
        return self.fields["change_id"]

    @property
    def risk(self) -> str:
        return self.fields["risk"]

    @property
    def disambiguation(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                key: value
                for key, value in self.fields.items()
                if key in OPTIONAL_DISAMBIGUATION_FIELDS
            }
        )


@dataclass(frozen=True, slots=True)
class PDCPChange:
    change_index: int
    manifest: PDCPManifest
    match_payload: str
    replace_payload: str
    operation: str = "match"
    span_start: int | None = None
    span_end: int | None = None
    # tx/2 span context guards (runtime patchdiff-mvp-0.5.0 only); exact adjacent text.
    expected_before: str | None = None
    expected_after: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedPDCP:
    header: PDCPHeader
    changes: tuple[PDCPChange, ...]
