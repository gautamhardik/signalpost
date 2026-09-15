import json
import collections

profiles = {json.loads(l)['organisation_number']: json.loads(l) for l in open('out/benchmark-100-profiles.jsonl', encoding='utf-8')}
cat_map = {json.loads(l)['organisation_number']: json.loads(l).get('benchmark_category') for l in open('benchmark-100.jsonl', encoding='utf-8')}

missing_profiles = [p for p in profiles.values() if not p.get('website')]

has_email = 0
email_domains = []
personal_domains = {"gmail.com", "online.no", "hotmail.com", "yahoo.no", "yahoo.com", "outlook.com", "live.no", "icloud.com"}

custom_domains = []

for p in missing_profiles:
    reg = p.get('evidence', {}).get('registry', {}).get('value') or {}
    email = str(reg.get('epostadresse') or reg.get('epost') or '').strip().casefold()
    if email and '@' in email:
        has_email += 1
        dom = email.split('@')[-1]
        email_domains.append(dom)
        if dom not in personal_domains:
            custom_domains.append((p['name'], p['organisation_number'], email, dom, cat_map.get(p['organisation_number'])))

print(f"Total missing profiles: {len(missing_profiles)}")
print(f"Profiles with BRREG email: {has_email}/{len(missing_profiles)} ({has_email/len(missing_profiles)*100:.1f}%)")
print(f"Profiles with custom business email domain: {len(custom_domains)}/{len(missing_profiles)} ({len(custom_domains)/len(missing_profiles)*100:.1f}%)")

print("\nCustom business email domains found in BRREG:")
for name, org, email, dom, cat in custom_domains:
    print(f"  {org} | {name[:30]:30s} | {dom:20s} | email: {email:25s} [{cat}]")
