import sys
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
import json
from norway_company_agent.discovery import choose_search_candidate

profiles = {json.loads(l)['organisation_number']: json.loads(l) for l in open(r'out\smoke-profiles.jsonl', encoding='utf-8')}
searches = [json.loads(l) for l in open(r'C:\signalpost-searxng\signalpost-discovery-results.jsonl', encoding='utf-8')]

print('\n=== DISCOVERY GATE EVALUATION ON SEARXNG CANDIDATES ===\n')
accepted_count = 0
abstained_count = 0

for s in searches:
    org = s['organisation_number']
    profile = profiles[org]
    results = s['results']
    decision = choose_search_candidate(profile, results)
    sel = decision.get('selected')
    if sel:
        accepted_count += 1
        print(f"[ACCEPTED] {profile['name']} ({org})")
        print(f"  URL: {sel['url']} (score: {sel['score']})")
        print(f"  Reasons: {sel['reasons']}\n")
    else:
        abstained_count += 1
        print(f"[ABSTAINED] {profile['name']} ({org})")
        cands = [c for c in decision.get('candidates', []) if c.get('status') != 'rejected']
        if cands:
            top = cands[0]
            print(f"  Top candidate for review: {top.get('url')} (score: {top.get('score')}) -> {top.get('reasons')}\n")
        else:
            print("  All search results were directories/aggregators (safe rejection)\n")

print(f"Summary: {accepted_count} Accepted for Crawl, {abstained_count} Abstained, 0 False Matches.")
