"""
pipeline.py
The main run. This is what GitHub Actions calls on a schedule.

Flow:
  1. Fetch new articles from all feeds (fetch_feeds.py)
  2. Cheap model filters: "is this a new consumer product/business-model worth tracking? y/n"
  3. Survivors go to the better model for structured extraction:
       company name, category, what it does, likely revenue model,
       does an Indian equivalent already exist, first-pass India-fit note
  4. Writes:
       research/<date>/daily-log.md          -- everything found today
       research/companies/<slug>/<date>.md   -- per-idea file, timeline of research
       research/watchlist.md                 -- running table, auto-updated
"""

import os
import re
import json
import time
from datetime import date

from fetch_feeds import fetch_new_articles
from llm_router import call_llm

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RESEARCH_DIR = os.path.join(BASE_DIR, "research")
TODAY = date.today().isoformat()


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return s.strip("-")[:60] or "unnamed"


def sanitize_cell(text, max_len=200):
    """Strip characters that would break a markdown table row: literal pipes and newlines."""
    if not text:
        return ""
    text = str(text).replace("|", "/").replace("\n", " ").replace("\r", " ").strip()
    if len(text) > max_len:
        text = text[:max_len - 1].rstrip() + "…"
    return text


def filter_article(article):
    prompt = f"""You are screening news articles for a startup-idea research tracker focused on spotting new consumer product or business-model innovations that could be adapted for the Indian market.

Article title: {article['title']}
Article summary: {article['summary']}

Answer with ONLY one word: YES if this describes a genuinely new product, app, or business model worth researching as a potential India-adaptation opportunity.

Answer NO for any of these, even if a big company is mentioned:
- Routine news about a major company (Tesla, Apple, OpenAI, Google, Meta, Microsoft, etc.) that isn't about a genuinely new business model -- earnings, executive/personnel changes, lawsuits, regulatory investigations, product events/keynotes, generic model releases, stock moves, layoffs
- Funding rounds with no new idea described (just "X raised $Y")
- Opinion pieces, listicles, deal/discount roundups, awards, conference announcements
- Politics, general macro/economic news unrelated to a specific product
"""
    try:
        text, provider = call_llm(prompt, tier="filter")
        return text.strip().upper().startswith("YES")
    except Exception as e:
        print(f"[warn] filter failed for '{article['title']}': {e}")
        return False


def extract_research(article):
    prompt = f"""You are a startup research analyst. Analyze this article about a product/business innovation and return ONLY valid JSON (no markdown fences, no preamble) with these exact keys:

{{
  "company_name": "short name of the company/product",
  "category": "one or two words, e.g. quick-commerce, legal-tech, ai-agent",
  "what_it_does": "1-2 plain sentences",
  "likely_revenue_model": "your best guess at how they actually make money, 1 sentence",
  "india_equivalent_exists": "name an existing Indian company doing something similar, or say 'none found' ",
  "india_fit_note": "1-2 sentences: does this depend on behavior/infrastructure that may not exist in India? be specific",
  "badge_guess": "orange or black -- orange if india_equivalent_exists is not 'none found', otherwise black"
}}

Article title: {article['title']}
Article summary: {article['summary']}
Source: {article['source']}
"""
    try:
        text, provider = call_llm(prompt, tier="extract")
        cleaned = text.strip()
        cleaned = re.sub(r"^```json\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        data["_provider"] = provider
        return data
    except Exception as e:
        print(f"[warn] extraction failed for '{article['title']}': {e}")
        return None


def write_daily_log(entries):
    day_dir = os.path.join(RESEARCH_DIR, TODAY)
    os.makedirs(day_dir, exist_ok=True)
    log_path = os.path.join(day_dir, "daily-log.md")
    with open(log_path, "a") as f:
        for e in entries:
            f.write(f"## {e['research']['company_name']}\n")
            f.write(f"- Source article: [{e['article']['title']}]({e['article']['link']}) ({e['article']['source']})\n")
            f.write(f"- Category: {e['research']['category']}\n")
            f.write(f"- What it does: {e['research']['what_it_does']}\n")
            f.write(f"- Likely revenue model: {e['research']['likely_revenue_model']}\n")
            f.write(f"- India equivalent: {e['research']['india_equivalent_exists']}\n")
            f.write(f"- India fit note: {e['research']['india_fit_note']}\n")
            f.write(f"- Badge guess: {e['research']['badge_guess']}\n\n")


def write_company_file(entry):
    slug = slugify(entry["research"]["company_name"])
    company_dir = os.path.join(RESEARCH_DIR, "companies", slug)
    os.makedirs(company_dir, exist_ok=True)
    file_path = os.path.join(company_dir, f"{TODAY}-research.md")
    r = entry["research"]
    a = entry["article"]
    with open(file_path, "w") as f:
        f.write(f"# {r['company_name']}\n\n")
        f.write(f"Researched: {TODAY}\n\n")
        f.write(f"**Category:** {r['category']}\n\n")
        f.write(f"**What it does:** {r['what_it_does']}\n\n")
        f.write(f"**Likely revenue model:** {r['likely_revenue_model']}\n\n")
        f.write(f"**India equivalent already exists:** {r['india_equivalent_exists']}\n\n")
        f.write(f"**India fit note (AI first pass, verify yourself):** {r['india_fit_note']}\n\n")
        f.write(f"**Badge guess:** {r['badge_guess']}\n\n")
        f.write(f"**Source article:** [{a['title']}]({a['link']}) -- {a['source']}\n\n")
        f.write("---\n\n## Your notes (add during daily review)\n\n_(empty -- add your human-intuition thoughts here)_\n")

    notes_path = os.path.join(company_dir, "your-notes.md")
    if not os.path.exists(notes_path):
        with open(notes_path, "w") as f:
            f.write(f"# Notes on {r['company_name']}\n\nAdd your daily 18:00-19:00 thoughts here, dated.\n\n")


TRACKED_COMPANIES_PATH = os.path.join(RESEARCH_DIR, "_tracked_companies.json")


def normalize_company_name(name):
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


def load_tracked_companies():
    if os.path.exists(TRACKED_COMPANIES_PATH):
        with open(TRACKED_COMPANIES_PATH) as f:
            return set(json.load(f))
    # First run after this feature was added -- bootstrap from the existing watchlist
    # so already-tracked companies aren't treated as new again.
    tracked = set()
    watchlist_path = os.path.join(RESEARCH_DIR, "watchlist.md")
    if os.path.exists(watchlist_path):
        with open(watchlist_path) as f:
            for line in f:
                line = line.strip()
                if not line.startswith("|") or "Company" in line or set(line) <= set("|-"):
                    continue
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if cells and cells[0]:
                    tracked.add(normalize_company_name(cells[0]))
    return tracked


def save_tracked_companies(tracked):
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    with open(TRACKED_COMPANIES_PATH, "w") as f:
        json.dump(sorted(tracked), f, indent=2)


def update_watchlist(entries):
    watchlist_path = os.path.join(RESEARCH_DIR, "watchlist.md")
    existing = ""
    if os.path.exists(watchlist_path):
        with open(watchlist_path) as f:
            existing = f.read()
    if "| Company |" not in existing:
        existing = "# Watchlist\n\n| Company | Category | Badge | First Seen | India Equivalent |\n|---|---|---|---|---|\n"
    rows = []
    for e in entries:
        r = e["research"]
        rows.append(
            f"| {sanitize_cell(r['company_name'], 60)} | {sanitize_cell(r['category'], 40)} | "
            f"{sanitize_cell(r['badge_guess'], 20)} | {TODAY} | {sanitize_cell(r['india_equivalent_exists'], 100)} |"
        )
    with open(watchlist_path, "w") as f:
        f.write(existing.rstrip() + "\n" + "\n".join(rows) + "\n")


def dedupe_by_company(entries):
    tracked = load_tracked_companies()
    kept = []
    for e in entries:
        norm = normalize_company_name(e["research"]["company_name"])
        if norm in tracked:
            print(f"  [dedup] skipping '{e['research']['company_name']}' -- already tracked")
            continue
        tracked.add(norm)
        kept.append(e)
    save_tracked_companies(tracked)
    return kept


def run():
    print(f"[{TODAY}] Fetching new articles...")
    articles = fetch_new_articles()
    print(f"Found {len(articles)} new articles.")

    kept_entries = []
    for article in articles:
        if filter_article(article):
            research = extract_research(article)
            if research:
                kept_entries.append({"article": article, "research": research})
        time.sleep(4)  # ~15 calls/min max -- stays under Gemini free tier's ~10-15 RPM ceiling

    print(f"{len(kept_entries)} articles passed the filter and were researched.")

    kept_entries = dedupe_by_company(kept_entries)
    print(f"{len(kept_entries)} are genuinely new companies after dedup.")

    if kept_entries:
        write_daily_log(kept_entries)
        for e in kept_entries:
            write_company_file(e)
        update_watchlist(kept_entries)

    print("Done.")


if __name__ == "__main__":
    run()
