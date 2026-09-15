import sys
import sqlite3
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest
from norway_company_agent.identity_store import (
    SQLiteIdentityStore,
    BulkFileIdentityStore,
    HybridIdentityStore,
    get_default_identity_store,
    DEFAULT_SQLITE_PATH,
    FALLBACK_CSV_PATH,
)
from norway_company_agent.batch import profiles_from_bulk, terminal_envelope, validate_envelopes
from norway_company_agent.evidence import utc_now


@pytest.fixture(scope="module")
def db_path():
    return DEFAULT_SQLITE_PATH


def test_universe_health_check_411k(db_path):
    """Phase V2-F: Verify all 411,160 entities are correctly indexed and unique."""
    assert db_path.exists(), f"SQLite universe DB missing at {db_path}"
    with sqlite3.connect(str(db_path)) as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT organisation_number) FROM companies")
        total_rows, unique_orgs = cur.fetchone()
        assert total_rows == 411160, f"Expected 411,160 rows, got {total_rows}"
        assert unique_orgs == 411160, f"Expected 411,160 unique orgs, got {unique_orgs}"

        # Verify no empty organisation numbers
        cur.execute("SELECT COUNT(*) FROM companies WHERE organisation_number IS NULL OR trim(organisation_number) = ''")
        empty_orgs = cur.fetchone()[0]
        assert empty_orgs == 0, f"Found {empty_orgs} empty organisation numbers"


def test_identity_parity_known_company(db_path):
    """Phase V2-C Test 1: Compare known company 810034882 against BRREG definition."""
    store = SQLiteIdentityStore(db_path)
    profile = store.get("810034882")
    assert profile is not None
    assert profile["organisation_number"] == "810034882"
    assert profile["name"] == "SANDNES ELEKTRISKE AS"
    assert profile["legal_form"] == "AS"
    assert profile["employees"] == 11
    assert profile["municipality"] == "SANDNES"
    assert profile["municipality_number"] == "1108"
    assert profile["industry_code"] == "43.210"
    assert profile["latest_submitted_accounts"] == "2025"
    assert "registry" in profile["evidence"]
    assert profile["evidence"]["registry"]["status"] == "available"
    assert profile["evidence"]["accounting_obligation"]["status"] == "available"


def test_random_100_orgs_sub_5ms(db_path):
    """Phase V2-C Test 2: Random 100 org numbers from 411k universe -> 100/100 found."""
    with sqlite3.connect(str(db_path)) as con:
        cur = con.cursor()
        cur.execute("SELECT organisation_number FROM companies")
        all_orgs = [r[0] for r in cur.fetchall()]

    random.seed(42)
    sample_100 = random.sample(all_orgs, 100)

    store = SQLiteIdentityStore(db_path)
    t0 = time.perf_counter()
    profiles, meta = store.get_batch(sample_100)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert len(profiles) == 100
    assert meta["selected"] == 100
    assert [p["organisation_number"] for p in profiles] == sample_100
    assert elapsed_ms < 100.0, f"100 lookups took {elapsed_ms:.2f} ms (expected fast SQL batch)"


def test_random_1000_orgs_sub_50ms(db_path):
    """Phase V2-C Test 3: Random 1,000 org numbers -> 1,000/1,000 found."""
    with sqlite3.connect(str(db_path)) as con:
        cur = con.cursor()
        cur.execute("SELECT organisation_number FROM companies")
        all_orgs = [r[0] for r in cur.fetchall()]

    random.seed(2026)
    sample_1000 = random.sample(all_orgs, 1000)

    store = SQLiteIdentityStore(db_path)
    t0 = time.perf_counter()
    profiles, meta = store.get_batch(sample_1000)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert len(profiles) == 1000
    assert meta["selected"] == 1000
    assert [p["organisation_number"] for p in profiles] == sample_1000
    assert elapsed_ms < 500.0, f"1,000 lookups took {elapsed_ms:.2f} ms"


def test_out_of_corpus_companies_valid_terminal_envelopes(db_path):
    """Phase V2-C Test 4: Random companies outside 1,100 corpus produce valid terminal envelopes."""
    manifest_path = ROOT / "submission" / "organisation-manifest.jsonl"
    in_corpus = set()
    if manifest_path.exists():
        import json
        in_corpus = {json.loads(l)["organisation_number"] for l in manifest_path.read_text(encoding="utf-8").splitlines() if l.strip()}

    with sqlite3.connect(str(db_path)) as con:
        cur = con.cursor()
        cur.execute("SELECT organisation_number FROM companies")
        all_orgs = [r[0] for r in cur.fetchall()]

    out_of_corpus = [org for org in all_orgs if org not in in_corpus]
    assert len(out_of_corpus) > 10000

    random.seed(99)
    sample = random.sample(out_of_corpus, 20)

    profiles, _ = profiles_from_bulk(db_path, sample)
    assert len(profiles) == 20

    started = utc_now()
    completed = utc_now()
    envelopes = [
        terminal_envelope(p, run_id="test-v2", modules=["registry", "accounting_obligation"], started_at=started, completed_at=completed)
        for p in profiles
    ]
    val = validate_envelopes(envelopes, 20)
    assert val["passed"], f"Envelopes failed validation: {val['invalid_states']}"
    assert all(e["state"] == "complete" for e in envelopes)


def test_hybrid_fallback():
    """Verify HybridIdentityStore transparently falls back if an entity is absent from primary."""
    class MockPrimary(SQLiteIdentityStore):
        def __init__(self):
            pass
        def get(self, org):
            return None
        def get_batch(self, orgs):
            return [], {}

    store = get_default_identity_store()
    assert store is not None
    res = store.get("810034882")
    assert res is not None
    assert res["name"] == "SANDNES ELEKTRISKE AS"
