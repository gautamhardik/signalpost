#!/usr/bin/env python3
"""
Phase 4: Adversarial Identity Stress Suite (Mission 5D).

Tests the Signalpost identity resolution engine against deliberately constructed adversarial scenarios:
1. Identity Collisions:
   - Same / lookalike company name with completely different OrgNr.
   - Shared person name across distinct holding vs operating companies.
   - Similar domain name belonging to a different firm.
2. Corporate Relationships:
   - Parent holding company pointing to subsidiary operating website (without parent proof).
   - Subsidiary claiming parent group global portal.
   - Brand name collision without subunit link.
   - Franchisee vs Franchisor boundary.
3. Web Attacks & Anomalies:
   - Parked domain / for-sale placeholder.
   - Expired / re-registered placeholder.
   - Domain containing company name but hosting generic link directory.
   - HTTP redirect to unrelated domain.
4. External Social / Source Misattribution:
   - Wrong LinkedIn / Facebook handle with similar name but different city/org.
   - Job posting for a different entity with similar name.

Success Invariants:
- Wrong-company publications: 0
- False entity links: 0
- External precision >= 95% (ideal 100%)
- Holding companies with no proof must be strictly ABSTAINED (score < 0.90, publishable = False).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.identity import assess_website_identity


def run_adversarial_suite() -> dict[str, Any]:
    test_cases = [
        # --- Category 1: Identity Collisions ---
        {
            "id": "COLLISION-01",
            "category": "Identity Collision",
            "name": "Lookalike name with different OrgNr in page",
            "profile": {
                "name": "NORDIC TECH AS",
                "organisation_number": "912345678",
                "municipality": "OSLO",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://nordictech.no",
                        "value": {
                            "title": "Nordic Tech AS - Velkommen",
                            "identity_text_excerpt": "Nordic Tech AS, Org nr: 987654321, Bergen",
                            "main_text_excerpt": "Vi leverer IT-tjenester over hele landet.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "OSLO"}},
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "Page contains conflicting OrgNr (987654321 vs 912345678)",
        },
        {
            "id": "COLLISION-02",
            "category": "Identity Collision",
            "name": "Lookalike name with different OrgNr in different municipality",
            "profile": {
                "name": "VIKEN BYGG AS",
                "organisation_number": "922111333",
                "municipality": "DRAMMEN",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://vikenbygg.com",
                        "value": {
                            "title": "Viken Bygg Sarpsborg AS",
                            "identity_text_excerpt": "Viken Bygg Sarpsborg AS, Org: 988777666, Sarpsborg.",
                            "main_text_excerpt": "Kontakt oss på tlf 12345678 for snekkerarbeid.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "DRAMMEN", "forretningsadresse.postnummer": "3015"}},
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "Conflicting organisation number (988777666) belonging to different entity",
        },

        # --- Category 2: Corporate Relationships & Hierarchy ---
        {
            "id": "CORP-01",
            "category": "Corporate Hierarchy",
            "name": "Holding company claiming operating subsidiary website without holding proof",
            "profile": {
                "name": "HANSEN INVEST AS",
                "organisation_number": "933444555",
                "municipality": "BERGEN",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://hansenbakeri.no",
                        "value": {
                            "title": "Hansen Bakeri AS - Ferske bakevarer",
                            "identity_text_excerpt": "Hansen Bakeri AS, Strandgaten 1, Bergen. Org: 944555666",
                            "main_text_excerpt": "Bakevarer hver morgen fra kl 06:00.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "BERGEN"}},
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "Holding company must not adopt operating subsidiary site without explicit holding identity match",
        },
        {
            "id": "CORP-02",
            "category": "Corporate Hierarchy",
            "name": "Subunit bridge positive test - verified operating branch",
            "profile": {
                "name": "HANSEN GRUPPEN AS",
                "organisation_number": "911222333",
                "municipality": "OSLO",
                "evidence": {
                    "locations": {
                        "value": {
                            "locations": [
                                {
                                    "name": "HANSEN GRUPPEN AVD STAVANGER",
                                    "address": {"adresse": "Klubbgata 5", "postnummer": "4013"},
                                }
                            ]
                        }
                    },
                    "website": {
                        "status": "available",
                        "source_url": "https://hansengruppen.no/stavanger",
                        "value": {
                            "title": "Hansen Gruppen Avd Stavanger",
                            "identity_text_excerpt": "Klubbgata 5, 4013 Stavanger. Velkommen til vår avdeling.",
                            "main_text_excerpt": "Vi tilbyr full service i Rogaland.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "OSLO"}},
                },
            },
            "expected_publishable": True,
            "expected_exact": True,
            "reason": "Subunit name and address verified in page",
        },

        # --- Category 3: Web Attacks & Parked Domains ---
        {
            "id": "WEB-01",
            "category": "Web Anomaly",
            "name": "Parked domain / Domain for sale placeholder",
            "profile": {
                "name": "SOLARIS ENERGI AS",
                "organisation_number": "955666777",
                "municipality": "TRONDHEIM",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://solarisenergi.no",
                        "value": {
                            "title": "solarisenergi.no - Domain is for sale",
                            "identity_text_excerpt": "Buy this domain at HugeDomains.com. This domain is parked at Miss Hosting.",
                            "main_text_excerpt": "The domain solarisenergi.no is available for purchase.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "TRONDHEIM"}},
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "Parked domain marker triggers safe quarantine (score = 0.1)",
        },
        {
            "id": "WEB-02",
            "category": "Web Anomaly",
            "name": "Generic link aggregator with company name in heading",
            "profile": {
                "name": "FJELL OG FJORD REISER AS",
                "organisation_number": "966777888",
                "municipality": "TROMSØ",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://fjellogfjord.net",
                        "value": {
                            "title": "Fjell og Fjord - Travel Guide Links",
                            "identity_text_excerpt": "Find the best information and most relevant links on all topics related to travel.",
                            "main_text_excerpt": "Sponsored links and directory search for Norwegian travel.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "TROMSØ"}},
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "Generic placeholder text triggers parked marker quarantine",
        },

        # --- Category 4: Business Sports Club Boundary ---
        {
            "id": "SPORTS-01",
            "category": "Corporate Boundary",
            "name": "Bedriftsidrettslag (B.I.L.) pointing to parent corporate website",
            "profile": {
                "name": "EQUINOR B.I.L.",
                "organisation_number": "977888999",
                "municipality": "STAVANGER",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://equinor.com",
                        "value": {
                            "title": "Equinor - Broad Energy Company",
                            "identity_text_excerpt": "Equinor ASA, Forusbeen 50, Stavanger. Oil, gas and renewable energy.",
                            "main_text_excerpt": "Global energy solutions for the future.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "STAVANGER"}},
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "B.I.L. entity pointing to operating company website without club evidence is rejected",
        },

        # --- Category 5: True Positive Control ---
        {
            "id": "CONTROL-01",
            "category": "Control Positive",
            "name": "Authentic company with matching OrgNr in footer",
            "profile": {
                "name": "BERGEN BRYGGESERVICE AS",
                "organisation_number": "999888777",
                "municipality": "BERGEN",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://bergenbryggeservice.no",
                        "value": {
                            "title": "Bergen Bryggeservice AS",
                            "identity_text_excerpt": "Bergen Bryggeservice AS | Org.nr: 999 888 777 | Skuteviksbodene 1, Bergen",
                            "main_text_excerpt": "Vedlikehold og service av kaianlegg på Vestlandet.",
                        },
                    },
                    "registry": {"value": {"forretningsadresse.kommune": "BERGEN", "forretningsadresse.postnummer": "5035"}},
                },
            },
            "expected_publishable": True,
            "expected_exact": True,
            "reason": "Exact OrgNr + complete legal name + municipality match",
        },
        # --- Category 6: Category E Brand-Title Boundary Cases ---
        {
            "id": "COLLISION-03",
            "category": "Brand Boundary",
            "name": "Category E brand corroboration with unrelated domain",
            "profile": {
                "name": "JØRGEN OTTEREN AS",
                "organisation_number": "983437672",
                "municipality": "SANDNES",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://someothercompany.no",
                        "value": {
                            "title": "Otteren Gullsmed",
                            "identity_text_excerpt": "Otteren Gullsmed and jewelry store in Rogaland.",
                            "main_text_excerpt": "Welcome to our watch and jewelry boutique in Western Norway.",
                        },
                    },
                    "registry": {
                        "value": {
                            "hjemmeside": "https://www.otteren.no",
                            "forretningsadresse.kommune": "SANDNES",
                        }
                    },
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "Candidate domain does not match registry-declared domain; Category E must not boost",
        },
        {
            "id": "COLLISION-04",
            "category": "Brand Boundary",
            "name": "Category E brand candidate with conflicting OrgNr in page",
            "profile": {
                "name": "JØRGEN OTTEREN AS",
                "organisation_number": "983437672",
                "municipality": "SANDNES",
                "evidence": {
                    "website": {
                        "status": "available",
                        "source_url": "https://www.otteren.no",
                        "value": {
                            "title": "Otteren Gullsmed",
                            "identity_text_excerpt": "Otteren Gullsmed Sandnes. Org nr: 999888777",
                            "main_text_excerpt": "Otteren Gullsmed Sandnes. Contact organisation 999888777 for inquiries.",
                        },
                    },
                    "registry": {
                        "value": {
                            "hjemmeside": "https://www.otteren.no",
                            "forretningsadresse.kommune": "SANDNES",
                        }
                    },
                },
            },
            "expected_publishable": False,
            "expected_exact": False,
            "reason": "Conflicting OrgNr dominates: must be rejected with score 0.2 even if domain and title match",
        },
    ]

    results = []
    wrong_entity_count = 0
    passed_tests = 0

    for tc in test_cases:
        p = tc["profile"]
        res = assess_website_identity(p)
        actual_pub = res.get("publishable", False)
        actual_exact = res.get("exact_entity", False)
        
        passed = (actual_pub == tc["expected_publishable"]) and (actual_exact == tc["expected_exact"])
        if passed:
            passed_tests += 1
        else:
            # If we published an adversarial decoy, that is a wrong-company publication!
            if actual_pub and not tc["expected_publishable"]:
                wrong_entity_count += 1

        results.append({
            "id": tc["id"],
            "name": tc["name"],
            "category": tc["category"],
            "expected_publishable": tc["expected_publishable"],
            "actual_publishable": actual_pub,
            "score": res.get("score"),
            "status": res.get("status"),
            "reasons": res.get("reasons"),
            "passed": passed,
        })

    total = len(test_cases)
    precision = (total - wrong_entity_count) / total if total else 1.0

    return {
        "suite": "Signalpost Adversarial Identity Suite (Mission 5D)",
        "total_adversarial_cases": total,
        "passed_cases": passed_tests,
        "failed_cases": total - passed_tests,
        "wrong_company_publications": wrong_entity_count,
        "adversarial_precision": round(precision, 4),
        "zero_tolerance_gate_passed": wrong_entity_count == 0,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Adversarial Identity Stress Suite.")
    parser.add_argument("--output", default="out/adversarial-identity-report.json", help="Report output JSON")
    args = parser.parse_args()

    report = run_adversarial_suite()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n======================================================================")
    print("=== ADVERSARIAL IDENTITY STRESS SUITE REPORT (MISSION 5D)          ===")
    print("======================================================================")
    print(f"Total Adversarial Cases:         {report['total_adversarial_cases']}")
    print(f"Passed Cases:                    {report['passed_cases']} / {report['total_adversarial_cases']}")
    print(f"Wrong-Company Publications:      {report['wrong_company_publications']} (Zero-Tolerance Gate)")
    print(f"Adversarial Precision:           {report['adversarial_precision']*100:.1f}%")
    print(f"Gate Passed:                     {report['zero_tolerance_gate_passed']}")
    print("\nDetailed Test Case Results:")
    for r in report["results"]:
        status_sym = "PASS [OK]" if r["passed"] else "FAIL [X]"
        print(f"  {status_sym} [{r['id']}] {r['category']:20s} - {r['name'][:35]:35s} -> Score: {r['score']}, Pub: {r['actual_publishable']}")

    if not report["zero_tolerance_gate_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
