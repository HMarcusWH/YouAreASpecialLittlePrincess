"""Consent notice delivery for clients (T03 registry, read-only).

Clients must present the exact notice text and version the server accepts
when it records a grant. This reads the reviewed notice registry
(``contracts/consent/v1/notices.json``), refuses a registry whose purpose
coverage disagrees with the domain mirror, and reports whether a notice may
authorize anything in this deployment: a DRAFT notice only counts where the
service runs with synthetic data (``allow_draft_policy``). Serving a notice
never records or implies a permission.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..domain.permissions import APPROVED_NOTICES, NOTICE_COVERAGE
from ..ports.base import InvalidInput, NotFound, PermanentFailure

# Notices shown in the consumer product; the pilot enrollment notice belongs to T11 tooling.
PRODUCT_NOTICE_IDS = frozenset({"notice.consent-choices"})
LOCALES = ("en", "sv")


@dataclass(frozen=True)
class NoticeCopy:
    purpose_id: str
    purpose_version: int
    label: str
    explanation: str
    decline_consequence: str


@dataclass(frozen=True)
class Notice:
    notice_version: str  # "<notice_id>:<version>", the value a grant cites
    status: str
    copy: Mapping[str, tuple[NoticeCopy, ...]]  # by locale


class NoticeCatalog:
    def __init__(self, notices: tuple[Notice, ...], *, allow_draft_policy: bool) -> None:
        self._notices = {notice.notice_version: notice for notice in notices}
        self._allow_draft = allow_draft_policy

    @classmethod
    def from_registry(cls, path: Path, *, allow_draft_policy: bool) -> "NoticeCatalog":
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PermanentFailure("notice_registry_unreadable") from None
        return cls(parse_registry(registry), allow_draft_policy=allow_draft_policy)

    def describe(self, locale: str) -> list[dict[str, Any]]:
        language = "sv" if locale.lower().startswith("sv") else "en"
        out = []
        for version in sorted(self._notices):
            notice = self._notices[version]
            approved = version in APPROVED_NOTICES
            out.append({
                "notice_version": version,
                "status": notice.status,
                # Whether a grant citing this notice can authorize use here.
                "accepted_for_use": approved or self._allow_draft,
                "locale": language,
                "purposes": [{
                    "purpose_id": item.purpose_id, "purpose_version": item.purpose_version, "label": item.label,
                    "explanation": item.explanation, "decline_consequence": item.decline_consequence,
                } for item in notice.copy.get(language, ())],
            })
        return out

    def require(self, notice_version: str) -> Notice:
        notice = self._notices.get(notice_version)
        if notice is None:
            raise NotFound("notice_not_found")
        return notice


def parse_registry(registry: Mapping[str, Any]) -> tuple[Notice, ...]:
    if not isinstance(registry, Mapping) or registry.get("contract_version") != "notice-registry/v1":
        raise PermanentFailure("notice_registry_unsupported")
    notices = []
    for raw in registry.get("notices", ()):
        if not isinstance(raw, Mapping) or raw.get("notice_id") not in PRODUCT_NOTICE_IDS:
            continue
        version = f"{raw['notice_id']}:{raw['version']}"
        covered = frozenset((p["purpose_id"], int(p["purpose_version"])) for p in raw.get("purposes", ()))
        if NOTICE_COVERAGE.get(version) != covered:
            # The domain mirror decides what a grant may cite; never serve text it would not accept.
            raise PermanentFailure("notice_registry_mismatch", detail=version[:64])
        copy: dict[str, list[NoticeCopy]] = {locale: [] for locale in LOCALES}
        for item in raw.get("copy", ()):
            locale = item.get("locale")
            if locale not in copy:
                continue
            purpose = item.get("purpose_id")
            purpose_version = next((v for p, v in covered if p == purpose), None)
            if purpose_version is None:
                raise InvalidInput("notice_copy_for_uncovered_purpose")
            copy[locale].append(NoticeCopy(purpose, purpose_version, str(item["label"]), str(item["explanation"]),
                                           str(item["decline_consequence"])))
        notices.append(Notice(version, str(raw["status"]),
                              {locale: tuple(items) for locale, items in copy.items()}))
    return tuple(notices)


__all__ = ["Notice", "NoticeCatalog", "NoticeCopy", "PRODUCT_NOTICE_IDS", "parse_registry"]
