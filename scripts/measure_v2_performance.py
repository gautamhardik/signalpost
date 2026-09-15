import sys
import time
import json
import random
import sqlite3
from pathlib import Path

sys.path.insert(0, "src")
from norway_company_agent.identity_store import BulkFileIdentityStore, SQLiteIdentityStore

def main():
    con = sqlite3.connect("data/company_universe_411k.db")
    cur = con.cursor()
    cur.execute("SELECT organisation_number FROM companies")
    all_orgs = [r[0] for r in cur.fetchall()]

    random.seed(777)
    rand_1 = random.sample(all_orgs, 1)
    rand_100 = random.sample(all_orgs, 100)
    rand_1000 = random.sample(all_orgs, 1000)

    sq_store = SQLiteIdentityStore("data/company_universe_411k.db")
    csv_store = BulkFileIdentityStore("brreg-enheter.csv")

    # Single lookup
    t0 = time.perf_counter()
    sq_store.get(rand_1[0])
    t_sq_1 = (time.perf_counter() - t0) * 1000

    # 100 lookup SQLite
    t0 = time.perf_counter()
    p100, m100 = sq_store.get_batch(rand_100)
    t_sq_100 = (time.perf_counter() - t0) * 1000

    # 1000 lookup SQLite
    t0 = time.perf_counter()
    p1000, m1000 = sq_store.get_batch(rand_1000)
    t_sq_1000 = (time.perf_counter() - t0) * 1000

    print(f"RESULTS: Single SQLite: {t_sq_1:.3f} ms | 100 SQLite: {t_sq_100:.2f} ms | 1000 SQLite: {t_sq_1000:.2f} ms")

if __name__ == "__main__":
    main()
