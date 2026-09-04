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


def filter_article(article):
    prompt = f"""You are screening news articles for a startup-idea research tracker focused on spotting new consumer product or business-model innovations that could be adapted for the Indian market.

Article title: {article['title']}
Article summary: {article['summary']}

Answer with ONLY one word: YES if this describes a new product, app, business model, or consumer service innovation worth researching further. NO if it's generic news, opinion, funding-round-only-with-no-new-idea, politics, or unrelated.
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
        rows.append(f"| {r['company_name']} | {r['category']} | {r['badge_guess']} | {TODAY} | {r['india_equivalent_exists']} |")
    with open(watchlist_path, "w") as f:
        f.write(existing.rstrip() + "\n" + "\n".join(rows) + "\n")


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
        time.sleep(1)  # be gentle on free-tier rate limits

    print(f"{len(kept_entries)} articles passed the filter and were researched.")

    if kept_entries:
        write_daily_log(kept_entries)
        for e in kept_entries:
            write_company_file(e)
        update_watchlist(kept_entries)

    print("Done.")


if __name__ == "__main__":
    run()
