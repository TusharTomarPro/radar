"""
cleanup_megacorps.py

One-time (or occasional) cleanup: removes mega-corp entries that got tracked
before the blocklist existed in pipeline.py. Purges them from:
  - research/watchlist.md
  - research/_tracked_companies.json
  - research/_deep_researched.json
  - research/companies/<slug>/ (the whole folder)
Then regenerates top-ideas.md and SHORTLIST.md so the dashboard reflects
the cleanup immediately.

Run manually: python cleanup_megacorps.py
Safe to re-run any time -- it's idempotent, just does nothing if there's
nothing left to clean.
"""

import os
import re
import json
import shutil

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RESEARCH_DIR = os.path.join(BASE_DIR, "research")
WATCHLIST_PATH = os.path.join(RESEARCH_DIR, "watchlist.md")
TRACKED_PATH = os.path.join(RESEARCH_DIR, "_tracked_companies.json")
DEEP_SEEN_PATH = os.path.join(RESEARCH_DIR, "_deep_researched.json")

MEGACORP_BLOCKLIST = [
    "apple", "tesla", "google", "alphabet", "meta platforms", "microsoft",
    "amazon", "openai", "nvidia", "netflix", "samsung", "sony", "toyota",
    "spacex", "boeing", "airbus", "walmart", "disney", "intel", "ibm",
    "oracle", "salesforce", "adobe", "uber technologies", "anthropic",
    "reliance jio", "reliance industries", "tata group", "adani",
]


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return s.strip("-")[:60] or "unnamed"


def normalize_company_name(name):
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


def is_megacorp(company_name):
    lower = company_name.lower()
    return any(name in lower for name in MEGACORP_BLOCKLIST)


def clean_watchlist():
    if not os.path.exists(WATCHLIST_PATH):
        return []
    with open(WATCHLIST_PATH) as f:
        lines = f.readlines()

    kept_lines = []
    removed = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "Company" not in stripped and not set(stripped) <= set("|- "):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if cells and is_megacorp(cells[0]):
                removed.append(cells[0])
                continue
        kept_lines.append(line)

    with open(WATCHLIST_PATH, "w") as f:
        f.writelines(kept_lines)
    return removed


def clean_tracked_companies():
    if not os.path.exists(TRACKED_PATH):
        return
    with open(TRACKED_PATH) as f:
        tracked = set(json.load(f))
    cleaned = {t for t in tracked if not any(name.replace(" ", "") in t for name in MEGACORP_BLOCKLIST)}
    with open(TRACKED_PATH, "w") as f:
        json.dump(sorted(cleaned), f, indent=2)
    return len(tracked) - len(cleaned)


def clean_deep_seen():
    if not os.path.exists(DEEP_SEEN_PATH):
        return []
    with open(DEEP_SEEN_PATH) as f:
        deep_seen = json.load(f)
    removed = []
    cleaned = {}
    for key, record in deep_seen.items():
        if is_megacorp(record.get("company", "")):
            removed.append(record.get("company", key))
            continue
        cleaned[key] = record
    with open(DEEP_SEEN_PATH, "w") as f:
        json.dump(cleaned, f, indent=2)
    return removed


def clean_company_folders(removed_names):
    companies_dir = os.path.join(RESEARCH_DIR, "companies")
    if not os.path.exists(companies_dir):
        return
    slugs_to_remove = {slugify(name) for name in removed_names}
    for slug in slugs_to_remove:
        folder = os.path.join(companies_dir, slug)
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"  removed folder: companies/{slug}/")


def run():
    print("Cleaning watchlist...")
    removed_from_watchlist = clean_watchlist()
    print(f"  removed {len(removed_from_watchlist)}: {removed_from_watchlist}")

    print("Cleaning tracked-companies cache...")
    n_removed_tracked = clean_tracked_companies()
    print(f"  removed {n_removed_tracked} normalized entries")

    print("Cleaning deep-research cache...")
    removed_from_deep = clean_deep_seen()
    print(f"  removed {len(removed_from_deep)}: {removed_from_deep}")

    all_removed_names = list(set(removed_from_watchlist) | set(removed_from_deep))
    print("Removing company folders...")
    clean_company_folders(all_removed_names)

    print("\nRegenerating derived reports...")
    try:
        import deep_research
        deep_seen = deep_research.load_deep_seen()
        if deep_seen:
            deep_research.rebuild_top_ideas(list(deep_seen.values()))
            print("  rebuilt top-ideas.md")
    except Exception as e:
        print(f"  [warn] could not rebuild top-ideas.md: {e}")

    try:
        import generate_report
        generate_report.generate()
    except Exception as e:
        print(f"  [warn] could not rebuild SHORTLIST.md: {e}")

    print("\nDone. Commit and push the research/ folder to apply the cleanup.")


if __name__ == "__main__":
    run()
