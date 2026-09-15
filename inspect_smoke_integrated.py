import json

envs = [json.loads(l) for l in open('out/smoke-integrated-envelopes.jsonl', encoding='utf-8')]
print("\n=== SMOKE INTEGRATED BATCH RESULTS ===")
for e in envs:
    org = e["organisation_number"]
    name = e["profile"]["name"]
    ent_st = e["state"]
    web_st = e["modules"]["website"]["state"]
    ev_web = e["profile"]["evidence"]["website"]
    status = ev_web.get("status")
    score = ev_web.get("value", {}).get("identity_assessment", {}).get("score") if ev_web.get("value") else None
    url = ev_web.get("source_url") or ev_web.get("value", {}).get("url")
    print(f"  {org} | {name[:28]:28s} | entity: {ent_st:8s} | web_state: {web_st:14s} | status: {str(status):12s} | score: {str(score):4s} | url: {url}")
