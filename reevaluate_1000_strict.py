import json
from pathlib import Path

# Load envelopes from stress-1000-v1
envs = [json.loads(l) for l in open("out/stress-1000-envelopes.jsonl", encoding="utf-8")]

print("=== RE-EVALUATING 1,000-COMPANY ENVELOPES UNDER STRICT PUBLICATION GATE ===")
new_envelopes = []

published_count = 0
quarantined_abstention_count = 0

for e in envs:
    profile = e["profile"]
    ev_web = profile.get("evidence", {}).get("website", {})
    val = ev_web.get("value")
    
    current_module_state = e["modules"]["website"]["state"]
    
    if current_module_state == "complete":
        assessment = val.get("identity_assessment") if isinstance(val, dict) else None
        if assessment and not assessment.get("publishable"):
            e["modules"]["website"]["state"] = "not_found"
            quarantined_abstention_count += 1
        else:
            published_count += 1
            
    new_envelopes.append(e)

print(f"Total Envelopes: {len(new_envelopes)}")
print(f"Verified & Published Websites (Score >= 0.90): {published_count}")
print(f"Quarantined / Abstained Sites (Score < 0.90): {quarantined_abstention_count}")

# Check final module state distribution
web_states = {}
for e in new_envelopes:
    st = e["modules"]["website"]["state"]
    web_states[st] = web_states.get(st, 0) + 1

print("\nFinal Website Module Distribution:")
for k, v in sorted(web_states.items()):
    print(f"  {k:18s}: {v:4d}")

# Save updated envelopes
out_path = Path("out/stress-1000-envelopes-strict.jsonl")
with open(out_path, "w", encoding="utf-8") as f:
    for e in new_envelopes:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")

print(f"\nSaved strict envelopes to {out_path}")
