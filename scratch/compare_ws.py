import json

def get_stats(env_file):
    with open(env_file, 'r', encoding='utf-8') as f:
        envs = [json.loads(line) for line in f]
    
    stats = {
        'websites_verified': 0,
        'social': 0,
        'dated_news': 0,
        'hiring': 0,
        'total_evidence': 0,
        'requests': sum(e.get('operations_summary', {}).get('requests', 0) for e in envs),
        'complete_envelopes': len(envs)
    }
    
    # Try getting requests from discovery_funnel instead
    reqs = sum(e.get('profile', {}).get('discovery_funnel', {}).get('requests', 0) for e in envs)
    
    for e in envs:
        prof = e.get('profile', {})
        ev = prof.get('evidence', {})
        
        # Website
        if ev.get('website', {}).get('status') == 'available':
            stats['websites_verified'] += 1
            
        # Observations
        obs = ev.get('external_footprint', {}).get('value', {}).get('observations', [])
        stats['total_evidence'] += len(obs)
        
        for o in obs:
            if o.get('signal_type') == 'job_posting':
                stats['hiring'] += 1
            elif o.get('source_type') == 'social_profile':
                stats['social'] += 1
            elif o.get('metrics', {}).get('activity_date'):
                stats['dated_news'] += 1

    stats['requests'] = reqs
    return stats

v7_stats = get_stats('out/v7_fresh100_envelopes.jsonl')
v8_stats = get_stats('out/v8_fresh100_envelopes.jsonl')

print("| Metric | V7 | V8 |")
print("|---|---|---|")
for k in v7_stats.keys():
    print(f"| {k} | {v7_stats[k]} | {v8_stats[k]} |")
