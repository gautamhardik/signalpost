import json

r = json.load(open('out/series-bc-report.json', encoding='utf-8'))
print("Candidate companies in S1:", r['strategy_performance']['S1_name_muni']['candidate_companies'])
for c in r['companies']:
    cand = c['strategy_results']['S1_name_muni']['selected_url']
    if cand:
        print(f"Company: {c['name']} ({c['organisation_number']})")
        print(f"  URL: {cand}")
        print(f"  Score: {c['strategy_results']['S1_name_muni']['score']}")
