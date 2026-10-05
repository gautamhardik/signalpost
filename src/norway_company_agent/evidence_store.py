from __future__ import annotations

import gzip
import hashlib
import json
import threading
from pathlib import Path
from typing import Any


class EvidenceStore:
    """Content-addressed store for the exact source bytes behind every published fact.

    Each body is written once to ``<root>/<sha256>.<ext>.gz`` where ``sha256`` is the hash of
    the uncompressed bytes, so a fact's ``snapshot_sha256`` can be checked against the file and
    re-running over the same sources never duplicates a record.
    """

    def __init__(self, root: str | Path, link_base: str | Path | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.link_base = Path(link_base) if link_base else self.root.parent
        self._lock = threading.Lock()
        self.written = 0
        self.reused = 0

    def put(self, body: bytes, *, kind: str = "html") -> dict[str, Any]:
        digest = hashlib.sha256(body).hexdigest()
        path = self.root / f"{digest}.{kind}.gz"
        with self._lock:
            if path.exists():
                self.reused += 1
            else:
                tmp = path.with_suffix(".tmp")
                with gzip.open(tmp, "wb") as handle:
                    handle.write(body)
                tmp.replace(path)
                self.written += 1
        return {
            "snapshot_sha256": digest,
            "snapshot_path": path.relative_to(self.link_base).as_posix() if path.is_relative_to(self.link_base) else path.as_posix(),
            "snapshot_bytes": len(body),
        }

    def put_json(self, body: Any) -> dict[str, Any]:
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.put(raw, kind="json")

    def summary(self) -> dict[str, Any]:
        return {"root": self.root.as_posix(), "written": self.written, "reused": self.reused}


def _canonical(url: str | None) -> str:
    return str(url or "").split("#", 1)[0].rstrip("/")


def snapshot_website_pages(store: EvidenceStore, website_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Persist every crawled page body and return a URL -> snapshot reference map.

    Removes the transient ``_raw`` bytes and the bounded ``html`` copy from the record so the
    profile stays small; the full page now lives in the evidence store.
    """
    refs: dict[str, dict[str, Any]] = {}
    value = website_record.get("value") if isinstance(website_record, dict) else None
    if not isinstance(value, dict):
        return refs
    for page in value.get("pages") or []:
        raw = page.pop("_raw", None)
        html = page.pop("html", None)
        body = raw if isinstance(raw, (bytes, bytearray)) else (html.encode("utf-8") if isinstance(html, str) else None)
        if not body:
            continue
        ref = store.put(bytes(body), kind=page.pop("snapshot_kind", None) or "html")
        page.update(ref)
        refs[_canonical(page.get("url"))] = ref
    homepage = refs.get(_canonical(value.get("final_url")))
    if homepage:
        value.update(homepage)
        website_record.update(homepage)
    return refs


def attach_observation_snapshots(observations: list[dict[str, Any]], page_refs: dict[str, dict[str, Any]], homepage_url: str | None) -> None:
    """Point each published observation at the stored page it was read from."""
    fallback = page_refs.get(_canonical(homepage_url))
    for obs in observations:
        if obs.get("snapshot_sha256"):
            continue
        ref = (
            page_refs.get(_canonical(obs.get("source_url")))
            or page_refs.get(_canonical(obs.get("found_on_url")))
        )
        if ref is None and obs.get("signal_type") in {"profile_handle", "profile_metrics"}:
            ref = fallback  # social links and site metrics are read from the homepage crawl
        if ref:
            obs.update(ref)


def strip_transient_bytes(website_record: dict[str, Any]) -> None:
    """Drop page bodies from a website record that is not being published."""
    value = website_record.get("value") if isinstance(website_record, dict) else None
    if isinstance(value, dict):
        for page in value.get("pages") or []:
            page.pop("_raw", None)
            page.pop("html", None)
