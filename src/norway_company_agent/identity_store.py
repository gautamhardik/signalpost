from __future__ import annotations

import abc
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .evidence import evidence, utc_now
from .official import accounting_obligation_assessment
from .sampling import iter_bulk

OFFICIAL_BULK_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
FALLBACK_CSV_PATH = Path("brreg-enheter.csv")
DEFAULT_SQLITE_PATH = Path("data/company_universe_411k.db")
DEFAULT_UNIVERSE_GZ_PATH = Path("data/signalpost-company-universe-2025.jsonl.gz")


def _build_registry_evidence_value(raw_record: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct official registry bulk dictionary expected by downstream gates."""
    # If the raw record already has full CSV column keys, return as-is
    if "organisasjonsnummer" in raw_record:
        return raw_record

    # Otherwise reconstruct from normalized JSON row
    return {
        "organisasjonsnummer": raw_record.get("organisation_number") or "",
        "navn": raw_record.get("name") or "",
        "organisasjonsform.kode": raw_record.get("legal_form") or "",
        "antallAnsatte": str(raw_record.get("employees") if raw_record.get("employees") is not None else ""),
        "konkurs": str(bool(raw_record.get("bankrupt"))).lower(),
        "underAvvikling": str(bool(raw_record.get("liquidating"))).lower(),
        "forretningsadresse.kommune": raw_record.get("municipality") or "",
        "forretningsadresse.kommunenummer": raw_record.get("municipality_number") or "",
        "naeringskode1.kode": raw_record.get("industry_code") or "",
        "naeringskode1.beskrivelse": raw_record.get("industry_label") or "",
        "hjemmeside": raw_record.get("website") or "",
        "sisteInnsendteAarsregnskap": str(raw_record.get("latest_submitted_accounts") or ""),
    }


def _profile_from_raw(raw_record: dict[str, Any], snapshot_sha256: str, retrieved_at: str) -> dict[str, Any]:
    """Construct full profile with official registry & accounting obligation evidence."""
    org = raw_record.get("organisation_number") or raw_record.get("organisasjonsnummer") or ""
    reg_val = _build_registry_evidence_value(raw_record)
    
    # Extract normalized top-level profile attributes
    employees_val = raw_record.get("employees")
    if employees_val is None and reg_val.get("antallAnsatte"):
        try:
            employees_val = int(reg_val["antallAnsatte"])
        except ValueError:
            employees_val = None

    profile = {
        "organisation_number": org,
        "name": raw_record.get("name") or reg_val.get("navn") or "",
        "legal_form": raw_record.get("legal_form") or reg_val.get("organisasjonsform.kode") or "",
        "employees": employees_val,
        "bankrupt": bool(raw_record.get("bankrupt")) if "bankrupt" in raw_record else reg_val.get("konkurs") == "true",
        "liquidating": bool(raw_record.get("liquidating")) if "liquidating" in raw_record else reg_val.get("underAvvikling") == "true",
        "municipality": raw_record.get("municipality") or reg_val.get("forretningsadresse.kommune") or "",
        "municipality_number": raw_record.get("municipality_number") or reg_val.get("forretningsadresse.kommunenummer") or "",
        "industry_code": raw_record.get("industry_code") or reg_val.get("naeringskode1.kode") or "",
        "industry_label": raw_record.get("industry_label") or reg_val.get("naeringskode1.beskrivelse") or "",
        "website": raw_record.get("website") if raw_record.get("website") is not None else reg_val.get("hjemmeside") or "",
        "latest_submitted_accounts": raw_record.get("latest_submitted_accounts") or reg_val.get("sisteInnsendteAarsregnskap") or "",
    }

    profile["evidence"] = {
        "registry": evidence(
            "registry",
            "available",
            "official_registry_bulk",
            OFFICIAL_BULK_URL,
            value=reg_val,
            retrieved_at=retrieved_at,
            content_sha256=snapshot_sha256,
            source_row_key=org,
        ),
        "accounting_obligation": accounting_obligation_assessment(profile),
    }
    return profile


class IdentityStore(abc.ABC):
    """Abstract interface for accessing authoritative BRREG entity snapshots."""

    @abc.abstractmethod
    def get(self, organisation_number: str) -> dict[str, Any] | None:
        """Lookup a single organisation profile."""
        ...

    @abc.abstractmethod
    def get_batch(self, organisation_numbers: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Lookup a batch of organisation profiles preserving request order."""
        ...


_CACHED_SNAPSHOT_SHA256: str | None = None

def get_snapshot_sha256() -> str:
    global _CACHED_SNAPSHOT_SHA256
    if _CACHED_SNAPSHOT_SHA256 is None:
        if FALLBACK_CSV_PATH.exists():
            _CACHED_SNAPSHOT_SHA256 = hashlib.sha256(FALLBACK_CSV_PATH.read_bytes()).hexdigest()
        elif DEFAULT_UNIVERSE_GZ_PATH.exists():
            _CACHED_SNAPSHOT_SHA256 = hashlib.sha256(DEFAULT_UNIVERSE_GZ_PATH.read_bytes()).hexdigest()
        elif DEFAULT_SQLITE_PATH.exists():
            _CACHED_SNAPSHOT_SHA256 = hashlib.sha256(DEFAULT_SQLITE_PATH.read_bytes()).hexdigest()
        else:
            _CACHED_SNAPSHOT_SHA256 = ""
    return _CACHED_SNAPSHOT_SHA256


class SQLiteIdentityStore(IdentityStore):
    """High-performance local indexed cache over the 411,160-company universe."""

    def __init__(self, db_path: str | Path, snapshot_sha256: str | None = None) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"SQLite identity database not found: {self.db_path}")
        self.snapshot_sha256 = snapshot_sha256 or get_snapshot_sha256()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def get(self, organisation_number: str) -> dict[str, Any] | None:
        retrieved_at = utc_now()
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT raw_json FROM companies WHERE organisation_number = ?", (organisation_number,))
            row = cur.fetchone()
            if not row:
                return None
            raw_record = json.loads(row[0])
            return _profile_from_raw(raw_record, self.snapshot_sha256, retrieved_at)

    def get_batch(self, organisation_numbers: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        requested = list(organisation_numbers)
        retrieved_at = utc_now()
        found: dict[str, dict[str, Any]] = {}

        chunk_size = 900
        with self._connect() as con:
            cur = con.cursor()
            for i in range(0, len(requested), chunk_size):
                chunk = requested[i : i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                cur.execute(
                    f"SELECT organisation_number, raw_json FROM companies WHERE organisation_number IN ({placeholders})",
                    chunk,
                )
                for org, raw_json_str in cur.fetchall():
                    raw_record = json.loads(raw_json_str)
                    found[org] = _profile_from_raw(raw_record, self.snapshot_sha256, retrieved_at)

        missing = [org for org in requested if org not in found]
        if missing:
            raise KeyError(f"Organisation numbers not found in SQLite index: {missing[:10]}")

        ordered = [found[org] for org in requested]
        metadata = {
            "identity_store": "sqlite_index",
            "db_path": str(self.db_path),
            "registry_snapshot_sha256": self.snapshot_sha256,
            "registry_rows_scanned": len(found),
            "requested": len(requested),
            "selected": len(found),
        }
        return ordered, metadata


class BulkFileIdentityStore(IdentityStore):
    """Streaming identity store for CSV / GZ BRREG bulk snapshots."""

    def __init__(self, file_path: str | Path, snapshot_sha256: str | None = None) -> None:
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"Bulk file not found: {self.file_path}")
        self.snapshot_sha256 = snapshot_sha256 or hashlib.sha256(self.file_path.read_bytes()).hexdigest()

    def get(self, organisation_number: str) -> dict[str, Any] | None:
        batch, _ = self.get_batch([organisation_number])
        return batch[0] if batch else None

    def get_batch(self, organisation_numbers: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        requested = list(organisation_numbers)
        wanted = set(requested)
        retrieved_at = utc_now()
        found: dict[str, dict[str, Any]] = {}
        scanned = 0

        for profile in iter_bulk(self.file_path):
            scanned += 1
            org = profile["organisation_number"]
            if org not in wanted:
                continue
            raw = profile.pop("raw", {})
            profile["evidence"] = {
                "registry": evidence(
                    "registry",
                    "available",
                    "official_registry_bulk",
                    OFFICIAL_BULK_URL,
                    value=raw,
                    retrieved_at=retrieved_at,
                    content_sha256=self.snapshot_sha256,
                    source_row_key=org,
                ),
                "accounting_obligation": accounting_obligation_assessment(profile),
            }
            found[org] = profile
            if len(found) == len(wanted):
                break

        missing = [org for org in requested if org not in found]
        if missing:
            raise KeyError(f"Organisation numbers absent from bulk file: {missing[:10]}")

        ordered = [found[org] for org in requested]
        metadata = {
            "identity_store": "bulk_file",
            "file_path": str(self.file_path),
            "registry_snapshot_sha256": self.snapshot_sha256,
            "registry_rows_scanned": scanned,
            "requested": len(requested),
            "selected": len(found),
        }
        return ordered, metadata


class HybridIdentityStore(IdentityStore):
    """Prefers SQLite primary cache and falls back gracefully to bulk file."""

    def __init__(self, primary: IdentityStore | None = None, fallback: IdentityStore | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    def get(self, organisation_number: str) -> dict[str, Any] | None:
        if self.primary:
            try:
                res = self.primary.get(organisation_number)
                if res is not None:
                    return res
            except Exception:
                pass
        if self.fallback:
            return self.fallback.get(organisation_number)
        return None

    def get_batch(self, organisation_numbers: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        requested = list(organisation_numbers)
        found: dict[str, dict[str, Any]] = {}
        missing = set(requested)
        metadata: dict[str, Any] = {"identity_store": "hybrid"}

        if self.primary:
            try:
                # Attempt primary lookup
                chunk_size = 900
                if isinstance(self.primary, SQLiteIdentityStore):
                    retrieved_at = utc_now()
                    with self.primary._connect() as con:
                        cur = con.cursor()
                        for i in range(0, len(requested), chunk_size):
                            chunk = requested[i : i + chunk_size]
                            placeholders = ",".join("?" for _ in chunk)
                            cur.execute(
                                f"SELECT organisation_number, raw_json FROM companies WHERE organisation_number IN ({placeholders})",
                                chunk,
                            )
                            for org, raw_json_str in cur.fetchall():
                                raw_record = json.loads(raw_json_str)
                                found[org] = _profile_from_raw(raw_record, self.primary.snapshot_sha256, retrieved_at)
                    missing = set(requested) - set(found)
                    metadata["primary_resolved"] = len(found)
            except Exception as exc:
                metadata["primary_error"] = str(exc)

        if missing and self.fallback:
            fallback_profiles, fb_meta = self.fallback.get_batch(list(missing))
            for p in fallback_profiles:
                found[p["organisation_number"]] = p
            metadata["fallback_resolved"] = len(fallback_profiles)

        final_missing = [org for org in requested if org not in found]
        if final_missing:
            raise KeyError(f"Organisation numbers not found across primary and fallback stores: {final_missing[:10]}")

        ordered = [found[org] for org in requested]
        metadata["requested"] = len(requested)
        metadata["selected"] = len(found)
        return ordered, metadata


def get_default_identity_store(
    db_path: str | Path | None = None,
    bulk_path: str | Path | None = None,
) -> IdentityStore:
    """Factory to construct the standard production identity store with automatic fallbacks."""
    sqlite_store = None
    bulk_store = None

    target_db = Path(db_path) if db_path else DEFAULT_SQLITE_PATH
    if target_db.exists():
        try:
            sqlite_store = SQLiteIdentityStore(target_db)
        except Exception:
            sqlite_store = None

    target_bulk = Path(bulk_path) if bulk_path else (FALLBACK_CSV_PATH if FALLBACK_CSV_PATH.exists() else DEFAULT_UNIVERSE_GZ_PATH)
    if target_bulk.exists():
        try:
            bulk_store = BulkFileIdentityStore(target_bulk)
        except Exception:
            bulk_store = None

    if sqlite_store and bulk_store:
        return HybridIdentityStore(primary=sqlite_store, fallback=bulk_store)
    elif sqlite_store:
        return sqlite_store
    elif bulk_store:
        return bulk_store
    else:
        raise FileNotFoundError("Neither SQLite identity database nor BRREG bulk file could be found.")
