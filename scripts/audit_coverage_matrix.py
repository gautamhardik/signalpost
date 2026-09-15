#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit coverage matrix across profiles.")
    parser.add_argument("--profiles", required=True, help="Path to profiles JSONL")
    parser.add_argument("--output", required=True, help="Output coverage matrix JSON")
    args = parser.parse_args()

    profiles = load_jsonl(args.profiles)
    total = len(profiles)
    if not total:
        raise SystemExit("No profiles found")

    matrix: list[dict[str, Any]] = []
    counts = {
        "website": 0,
        "linkedin": 0,
        "facebook": 0,
        "instagram": 0,
        "financials": 0,
        "roles": 0,
        "subunits": 0,
        "hiring": 0,
        "news": 0,
    }

    for p in profiles:
        org = p.get("organisation_number")
        name = p.get("name")
        ev = p.get("evidence") or {}

        # Website
        web_rec = ev.get("website") or {}
        web_val = web_rec.get("value") or {}
        has_web = (web_rec.get("status") == "available") and bool((web_val.get("identity_assessment") or {}).get("publishable"))

        # Socials
        socials = web_val.get("social_links") or [] if has_web else []
        platforms = {s.get("platform") for s in socials}
        has_li = "linkedin" in platforms
        has_fb = "facebook" in platforms
        has_ig = "instagram" in platforms

        # Footprint observations
        fp_rec = ev.get("external_footprint") or {}
        fp_obs = (fp_rec.get("value") or {}).get("observations") or []
        for obs in fp_obs:
            plat = obs.get("platform")
            if plat == "linkedin":
                has_li = True
            elif plat == "facebook":
                has_fb = True
            elif plat == "instagram":
                has_ig = True

        # Financials
        fin_rec = ev.get("financials") or {}
        records = (fin_rec.get("value") or {}).get("records") or []
        has_fin = len(records) > 0

        # Roles
        roles_rec = ev.get("roles") or {}
        roles_list = (roles_rec.get("value") or {}).get("roles") or []
        has_roles = len([r for r in roles_list if not r.get("inactive")]) > 0

        # Subunits
        loc_rec = ev.get("locations") or {}
        subunits = (loc_rec.get("value") or {}).get("locations") or []
        has_subunits = len(subunits) > 0

        # Hiring & News indicators from site pages
        pages = web_val.get("pages") or []
        has_hiring = False
        has_news = False
        for pg in pages:
            path_str = urlparse(str(pg.get("url") or "")).path.casefold()
            if any(k in path_str for k in ("karriere", "stillinger", "jobb", "jobs", "career")):
                has_hiring = True
            if any(k in path_str for k in ("nyheter", "aktuelt", "presse", "news", "artikler", "blog")):
                has_news = True

        row = {
            "organisation_number": org,
            "name": name,
            "website": has_web,
            "linkedin": has_li,
            "facebook": has_fb,
            "instagram": has_ig,
            "financials": has_fin,
            "roles": has_roles,
            "subunits": has_subunits,
            "hiring": has_hiring,
            "news": has_news,
        }
        matrix.append(row)

        for k, v in (
            ("website", has_web),
            ("linkedin", has_li),
            ("facebook", has_fb),
            ("instagram", has_ig),
            ("financials", has_fin),
            ("roles", has_roles),
            ("subunits", has_subunits),
            ("hiring", has_hiring),
            ("news", has_news),
        ):
            if v:
                counts[k] += 1

    summary = {
        "total_profiles": total,
        "coverage_rates": {k: round(v / total, 4) for k, v in counts.items()},
        "missing_rates": {k: round((total - v) / total, 4) for k, v in counts.items()},
        "counts": counts,
        "sample_matrix": matrix[:20],
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "total_profiles": total,
        "coverage_rates": summary["coverage_rates"],
        "missing_rates": summary["missing_rates"],
    }, indent=2))


if __name__ == "__main__":
    main()
