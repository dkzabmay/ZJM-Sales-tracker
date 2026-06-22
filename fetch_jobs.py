#!/usr/bin/env python3
"""
Daily job fetcher for the Tampa-St. Pete Sales Tracker.

Reads Adzuna credentials from environment variables ADZUNA_APP_ID and
ADZUNA_APP_KEY, searches the Tampa Bay area for entry-level sales roles
across three industries, and writes the result to jobs.json.

Run modes:
    python fetch_jobs.py            -> live fetch (needs API credentials)
    python fetch_jobs.py --sample   -> write sample jobs.json (no network)

Design note: if a live fetch fails, the existing jobs.json is left
untouched so the web page never goes blank on a transient error.
"""

import json
import os
import sys
import datetime
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
COMPANIES_PATH = os.path.join(HERE, "companies.json")
OUTPUT_PATH = os.path.join(HERE, "jobs.json")

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/us/search"
WHERE = "Tampa, Florida"
DISTANCE_KM = 45          # covers Tampa, St. Pete, Clearwater, Brandon, Largo, Riverview
MAX_DAYS_OLD = 14
RESULTS_PER_PAGE = 50
PAGES_PER_QUERY = 2

# Keyword searches per industry. Each returned job is tagged with this industry.
INDUSTRY_QUERIES = {
    "pharma": [
        "pharmaceutical sales representative",
        "associate pharmaceutical sales",
        "medical sales representative",
    ],
    "sporting": [
        "ticket sales representative",
        "inside sales sports",
        "membership sales premium",
    ],
    "device": [
        "medical device sales associate",
        "surgical sales representative",
        "clinical sales associate",
    ],
}

# Title keywords used to drop roles that are too senior for the candidate.
TOO_SENIOR = ["senior", "sr.", "sr ", "manager", "director", "principal",
              "vp ", "vice president", "head of", "lead ", " iii", " ii"]

# Title keywords -> role category shown in the UI.
CAT_RULES = [
    ("training", ["program", "trainee", "rotational", "graduate",
                  "development program", "leadership development"]),
    ("account", ["account", "client", "customer success", "membership service",
                 "retention", "renewal", "service coordinator"]),
    ("entry", ["associate", "entry", "junior", "inside sales", "representative",
               "development representative", "sdr", "coordinator"]),
]


def load_companies():
    with open(COMPANIES_PATH, encoding="utf-8") as f:
        return json.load(f)


def classify_category(title):
    t = title.lower()
    for cat, words in CAT_RULES:
        if any(w in t for w in words):
            return cat
    return "entry"


def is_too_senior(title):
    t = " " + title.lower() + " "
    return any(w in t for w in TOO_SENIOR)


def company_industry(company, companies):
    """If the employer is on a known list, trust that over the search tag."""
    c = company.lower()
    for industry, names in companies.items():
        for name in names:
            if name.lower() in c:
                return industry
    return None


def days_since(iso_created):
    try:
        dt = datetime.datetime.fromisoformat(iso_created.replace("Z", "+00:00"))
        delta = datetime.datetime.now(datetime.timezone.utc) - dt
        return max(0, delta.days)
    except Exception:
        return 0


def adzuna_request(app_id, app_key, query, page):
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "where": WHERE,
        "distance": DISTANCE_KM,
        "max_days_old": MAX_DAYS_OLD,
        "results_per_page": RESULTS_PER_PAGE,
        "sort_by": "date",
        "content-type": "application/json",
    }
    url = f"{ADZUNA_BASE}/{page}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "sales-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_live():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError(
            "Missing ADZUNA_APP_ID / ADZUNA_APP_KEY. "
            "Set them as repository secrets (live) or env vars (local)."
        )

    companies = load_companies()
    seen_ids = set()
    jobs = []

    for industry, queries in INDUSTRY_QUERIES.items():
        for query in queries:
            for page in range(1, PAGES_PER_QUERY + 1):
                data = adzuna_request(app_id, app_key, query, page)
                results = data.get("results", [])
                if not results:
                    break
                for r in results:
                    jid = str(r.get("id", ""))
                    title = (r.get("title") or "").strip()
                    if not title or jid in seen_ids:
                        continue
                    if is_too_senior(title):
                        continue
                    seen_ids.add(jid)
                    company = (r.get("company", {}) or {}).get("display_name", "Unknown")
                    city = (r.get("location", {}) or {}).get("display_name", "Tampa Bay, FL")
                    ind = company_industry(company, companies) or industry
                    jobs.append({
                        "title": title,
                        "company": company,
                        "city": city,
                        "industry": ind,
                        "category": classify_category(title),
                        "days_ago": days_since(r.get("created", "")),
                        "url": r.get("redirect_url", ""),
                    })

    jobs.sort(key=lambda j: j["days_ago"])
    return jobs


SAMPLE_JOBS = [
    ("IQVIA", "pharma", "Associate Sales Representative", "Tampa, FL", 2),
    ("EVERSANA", "pharma", "Sales Development Program Associate", "Tampa, FL", 1),
    ("Syneos Health", "pharma", "Entry-Level Pharmaceutical Sales Rep", "St. Petersburg, FL", 5),
    ("Pfizer", "pharma", "Health Representative I", "Clearwater, FL", 9),
    ("Novartis", "pharma", "Associate Account Specialist", "Tampa, FL", 6),
    ("Tampa Bay Rays", "sporting", "Ticket Sales Associate", "St. Petersburg, FL", 0),
    ("Tampa Bay Buccaneers", "sporting", "Inside Sales Representative", "Tampa, FL", 3),
    ("Tampa Bay Lightning", "sporting", "Membership Service Coordinator", "Tampa, FL", 7),
    ("ASM Global - Amalie Arena", "sporting", "Premium Sales Trainee", "Tampa, FL", 11),
    ("Topgolf", "sporting", "Event Sales Coordinator", "Tampa, FL", 4),
    ("Stryker", "device", "Associate Sales Representative", "Tampa, FL", 1),
    ("Medtronic", "device", "Clinical Sales Associate - Development Program", "Tampa, FL", 8),
    ("Boston Scientific", "device", "Territory Account Associate", "St. Petersburg, FL", 5),
    ("GE HealthCare", "device", "Sales Development Associate", "Clearwater, FL", 6),
    ("Abbott", "device", "Inside Sales Representative I", "Tampa, FL", 12),
]


def build_sample():
    jobs = []
    for company, ind, title, city, days in SAMPLE_JOBS:
        q = urllib.parse.quote(f"{company} {title} Tampa jobs apply")
        jobs.append({
            "title": title,
            "company": company,
            "city": city,
            "industry": ind,
            "category": classify_category(title),
            "days_ago": days,
            "url": f"https://www.google.com/search?q={q}",
        })
    jobs.sort(key=lambda j: j["days_ago"])
    return jobs


def write_output(jobs):
    payload = {
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(jobs),
        "jobs": jobs,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {len(jobs)} jobs to {OUTPUT_PATH}")


def main():
    if "--sample" in sys.argv:
        write_output(build_sample())
        return
    try:
        jobs = fetch_live()
    except Exception as e:
        print(f"Fetch failed, keeping existing jobs.json. Reason: {e}", file=sys.stderr)
        sys.exit(1)
    write_output(jobs)


if __name__ == "__main__":
    main()
