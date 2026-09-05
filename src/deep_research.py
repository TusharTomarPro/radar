"""
deep_research.py

This is the "second pass" the plan always called for -- the RSS pipeline only ever
guesses a badge from a single article. This script actually searches the web to:
  1. Verify whether a named competitor is real, alive, funded, dead, or pivoted
  2. Re-check "no competitor found" (black badge) claims against a real search
  3. Attach a shelf-life note to black badges: is the absence structural (regulation,
     culture, infra) or temporal (a cost curve about to flip)?
  4. Produce a numeric risk score with real reasoning
  5. Maintain research/top-ideas.md, a single ranked shortlist sorted by risk

Runs once a day (separate workflow from the frequent RSS scan) because it's slower
and burns a real, budgeted resource: Tavily's free search API (1,000 credits/month,
no card). We cap how many companies get deep-researched per run so a big backlog
can't blow the monthly quota in one day.
"""

import os
import re
import json
import time
import requests

from llm_router import call_llm

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RESEARCH_DIR = os.path.join(BASE_DIR, "research")
WATCHLIST_PATH = os.path.join(RESEARCH_DIR, "watchlist.md")
DEEP_SEEN_PATH = os.path.join(RESEARCH_DIR, "_deep_researched.json")
TOP_IDEAS_PATH = os.path.join(RESEARCH_DIR, "top-ideas.md")

MAX_PER_RUN = 15  # keeps us well under Tavily's 1,000/month free credits (2 searches per company)


def sanitize_cell(text, max_len=200):
    """Strip characters that would break a markdown table row: literal pipes and newlines.
    Also caps length so one verbose field doesn't blow up the whole row."""
    if not text:
        return ""
    text = str(text).replace("|", "/").replace("\n", " ").replace("\r", " ").strip()
    if len(text) > max_len:
        text = text[:max_len - 1].rstrip() + "…"
    return text


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return s.strip("-")[:60] or "unnamed"


def load_deep_seen():
    if os.path.exists(DEEP_SEEN_PATH):
        with open(DEEP_SEEN_PATH) as f:
            return json.load(f)
    return {}


def save_deep_seen(data):
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    with open(DEEP_SEEN_PATH, "w") as f:
        json.dump(data, f, indent=2)


def parse_watchlist():
    if not os.path.exists(WATCHLIST_PATH):
        return []
    with open(WATCHLIST_PATH) as f:
        lines = [l.strip() for l in f if l.strip().startswith("|")]
    if len(lines) < 3:
        return []
    rows = []
    for line in lines[2:]:  # skip header + separator
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 5:
            continue
        company, category, badge, first_seen, india_eq = cells
        if not company:
            continue
        rows.append({
            "company": company, "category": category,
            "badge": badge.lower(), "first_seen": first_seen,
            "india_eq": india_eq, "slug": slugify(company)
        })
    return rows


def tavily_search(query):
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("no TAVILY_API_KEY set")
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": query,
            "search_depth": "basic",
            "max_results": 4,
            "include_answer": True,
        },
        timeout=25,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"tavily HTTP {resp.status_code}")
    data = resp.json()
    answer = data.get("answer", "")
    snippets = [r.get("content", "")[:400] for r in data.get("results", [])[:4]]
    return answer, snippets


def deep_research_one(row):
    company = row["company"]
    india_eq = row["india_eq"]
    badge = row["badge"]

    # Search 1: does a real competitor exist, and is it alive?
    q1 = f"{company} India competitors 2026" if badge == "black" else f"{india_eq} funding status shut down acquired 2026"
    try:
        answer1, snippets1 = tavily_search(q1)
    except Exception as e:
        return None, f"search failed: {e}"

    time.sleep(1)

    # Search 2: broader "graveyard" check -- has anyone tried and failed at this in India?
    q2 = f"{company} similar startup India failed shut down"
    try:
        answer2, snippets2 = tavily_search(q2)
    except Exception as e:
        answer2, snippets2 = "", []

    evidence = f"""Search 1 ("{q1}") answer: {answer1}
Search 1 snippets: {' | '.join(snippets1)}

Search 2 ("{q2}") answer: {answer2}
Search 2 snippets: {' | '.join(snippets2)}"""

    prompt = f"""You are doing real due diligence on a startup idea for a founder deciding whether to build an India-localized version.

Company being evaluated: {company}
Category: {row['category']}
AI's first-pass badge guess: {badge} (orange = competitor claimed to exist, black = no competitor found)
Competitor(s) claimed: {india_eq}

Here is real web search evidence gathered just now:
{evidence}

Based on this evidence (not your prior assumptions), return ONLY valid JSON with these exact keys:

{{
  "revised_badge": "orange or black -- your judgment after seeing real search evidence, may differ from the guess above",
  "competitor_status": "surviving, pivoted, dead, no-real-competitor-found, or unclear",
  "shelf_life_note": "ONLY if revised_badge is black: is the lack of a competitor structural (regulation, culture, infra -- unlikely to change soon) or temporal (a cost/behavior curve that's shifting, meaning a window is opening)? One sentence. If revised_badge is orange, put 'n/a'.",
  "regulatory_flag": "none, moderate, or high -- does this business model hit real Indian regulatory walls? Consider: FDI rules in multi-brand retail/inventory-based ecommerce, RBI rules on lending/payments/NBFC licensing, labor law for gig workers, data localization requirements, sector-specific licensing (healthcare, education, insurance, drone/aviation). Give the specific law or rule if you know one, not just a vague risk label.",
  "capital_intensity": "low, medium, or high -- is this a VC-subsidized cash-burn model (heavy discounting, dark-store real estate, delivery fleet subsidies -- needs years of runway before unit economics work) or a bootstrappable model (software-margin, asset-light, can reach profitability on modest capital)? One sentence of reasoning.",
  "risk_score": 1-10 as an integer. 1 = low risk / most promising, 10 = high risk / avoid. Weigh competitor status, regulatory_flag, and capital_intensity together -- a black badge with high regulatory risk and high capital intensity is a bad combination even with no competitor.
  "risk_reasoning": "2-3 sentences explaining the score, referencing what the search evidence actually showed and any regulatory/capital factors"
}}"""

    try:
        text, provider = call_llm(prompt, tier="extract")
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
        result = json.loads(cleaned)
        return result, None
    except Exception as e:
        return None, f"LLM reasoning failed: {e}"


def append_to_company_file(row, result):
    company_dir = os.path.join(RESEARCH_DIR, "companies", row["slug"])
    file_path = os.path.join(company_dir, f"{row['first_seen']}-research.md")
    if not os.path.exists(file_path):
        return  # original file missing, skip silently
    with open(file_path, "a") as f:
        f.write("\n---\n\n## Deep Research (search-grounded)\n\n")
        f.write(f"**Revised badge:** {result['revised_badge']}\n\n")
        f.write(f"**Competitor status:** {result['competitor_status']}\n\n")
        f.write(f"**Shelf-life note:** {result['shelf_life_note']}\n\n")
        f.write(f"**Regulatory flag:** {result.get('regulatory_flag', 'unknown')}\n\n")
        f.write(f"**Capital intensity:** {result.get('capital_intensity', 'unknown')}\n\n")
        f.write(f"**Risk score:** {result['risk_score']}/10\n\n")
        f.write(f"**Reasoning:** {result['risk_reasoning']}\n\n")


def rebuild_top_ideas(all_scored):
    all_scored.sort(key=lambda r: r["risk_score"])
    lines = [
        "# Top Ideas (ranked by risk score, low to high)\n",
        "Auto-generated by deep_research.py. Lower risk score = more promising after real search evidence.\n",
        "| Rank | Company | Category | Revised Badge | Competitor Status | Regulatory | Capital | Risk Score | Reasoning |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(all_scored, 1):
        lines.append(
            f"| {i} | {sanitize_cell(r['company'], 60)} | {sanitize_cell(r['category'], 40)} | "
            f"{sanitize_cell(r['revised_badge'], 20)} | {sanitize_cell(r['competitor_status'], 40)} | "
            f"{sanitize_cell(r.get('regulatory_flag', 'unknown'), 120)} | "
            f"{sanitize_cell(r.get('capital_intensity', 'unknown'), 120)} | "
            f"{r['risk_score']}/10 | {sanitize_cell(r['risk_reasoning'], 150)} |"
        )
    with open(TOP_IDEAS_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


def run():
    rows = parse_watchlist()
    deep_seen = load_deep_seen()

    pending = [r for r in rows if f"{r['slug']}::{r['first_seen']}" not in deep_seen]
    print(f"{len(rows)} total tracked, {len(pending)} pending deep research, processing up to {MAX_PER_RUN}.")

    batch = pending[:MAX_PER_RUN]
    for row in batch:
        key = f"{row['slug']}::{row['first_seen']}"
        result, err = deep_research_one(row)
        if err:
            print(f"[warn] skipped {row['company']}: {err}")
            continue
        append_to_company_file(row, result)
        deep_seen[key] = {
            "company": row["company"], "category": row["category"],
            "revised_badge": result["revised_badge"],
            "competitor_status": result["competitor_status"],
            "regulatory_flag": result.get("regulatory_flag", "unknown"),
            "capital_intensity": result.get("capital_intensity", "unknown"),
            "risk_score": result["risk_score"],
            "risk_reasoning": result["risk_reasoning"],
        }
        print(f"  {row['company']}: risk {result['risk_score']}/10, {result['competitor_status']}, "
              f"reg={result.get('regulatory_flag','?')}, capital={result.get('capital_intensity','?')}")
        time.sleep(2)

    save_deep_seen(deep_seen)

    all_scored = list(deep_seen.values())
    if all_scored:
        rebuild_top_ideas(all_scored)

    print("Done.")


if __name__ == "__main__":
    run()
