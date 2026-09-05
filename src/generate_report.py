"""
generate_report.py

Combines everything the system has learned into one readable document:
research/SHORTLIST.md -- the top 20 ideas by risk score, each with the AI's
full research, deep-research findings, AND your own human-intuition notes
pulled in side by side.

This is the actual deliverable the plan was building toward -- not a raw
table to parse, but something you could hand to someone or use to decide.

Runs automatically after every deep-research pass (no extra API cost --
pure aggregation of files that already exist). Also runnable anytime via
`python generate_report.py` to get a fresh snapshot on demand.
"""

import os
import re
import json
from datetime import datetime

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RESEARCH_DIR = os.path.join(BASE_DIR, "research")
DEEP_SEEN_PATH = os.path.join(RESEARCH_DIR, "_deep_researched.json")
WATCHLIST_PATH = os.path.join(RESEARCH_DIR, "watchlist.md")
SHORTLIST_PATH = os.path.join(RESEARCH_DIR, "SHORTLIST.md")

TOP_N = 20


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return s.strip("-")[:60] or "unnamed"


def load_deep_seen():
    if not os.path.exists(DEEP_SEEN_PATH):
        return {}
    with open(DEEP_SEEN_PATH) as f:
        return json.load(f)


def load_first_seen_dates():
    """Map normalized company name -> first_seen date, by reading the watchlist,
    so we can find each company's research file (named by that date)."""
    mapping = {}
    if not os.path.exists(WATCHLIST_PATH):
        return mapping
    with open(WATCHLIST_PATH) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or "Company" in line or set(line) <= set("|-"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) < 4:
                continue
            company, _, _, first_seen = cells[0], cells[1], cells[2], cells[3]
            mapping[slugify(company)] = first_seen
    return mapping


def read_your_notes(slug):
    path = os.path.join(RESEARCH_DIR, "companies", slug, "your-notes.md")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        content = f.read().strip()
    # Strip the boilerplate header line so we only surface real notes
    lines = [l for l in content.split("\n") if l.strip() and not l.startswith("#") and "Add your daily" not in l]
    real_notes = "\n".join(lines).strip()
    return real_notes if real_notes else None


def risk_badge_label(score):
    if score <= 3:
        return "LOW RISK"
    if score <= 6:
        return "MODERATE RISK"
    return "HIGH RISK"


def generate():
    deep_seen = load_deep_seen()
    first_seen_map = load_first_seen_dates()

    if not deep_seen:
        print("No deep-research data yet -- nothing to build a shortlist from.")
        return

    scored = list(deep_seen.values())
    scored.sort(key=lambda r: r["risk_score"])
    top = scored[:TOP_N]

    lines = [
        f"# Top {len(top)} Shortlist",
        f"_Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} -- auto-updated after every deep-research pass._",
        "",
        f"Ranked by risk score (lower = more promising) out of {len(scored)} companies deep-researched so far, "
        f"{len(load_first_seen_dates())} tracked total.",
        "",
        "---",
        "",
    ]

    for i, r in enumerate(top, 1):
        slug = slugify(r["company"])
        notes = read_your_notes(slug)
        first_seen = first_seen_map.get(slug, "")

        lines.append(f"## {i}. {r['company']} -- {risk_badge_label(r['risk_score'])} ({r['risk_score']}/10)")
        lines.append("")
        lines.append(f"**Category:** {r['category']}  ")
        lines.append(f"**Badge:** {r['revised_badge']}  ")
        lines.append(f"**Competitor status:** {r['competitor_status']}  ")
        lines.append(f"**Regulatory:** {r.get('regulatory_flag', 'unknown')}  ")
        lines.append(f"**Capital intensity:** {r.get('capital_intensity', 'unknown')}  ")
        lines.append("")
        lines.append(f"**AI reasoning:** {r['risk_reasoning']}")
        lines.append("")
        if notes:
            lines.append(f"**Your notes:** {notes}")
        else:
            lines.append("**Your notes:** _(none added yet -- click through from the dashboard to add your take)_")
        lines.append("")
        if first_seen:
            lines.append(
                f"[Full research file](companies/{slug}/{first_seen}-research.md) -- "
                f"[Add notes](companies/{slug}/your-notes.md)"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(SHORTLIST_PATH, "w") as f:
        f.write("\n".join(lines))

    print(f"Wrote {SHORTLIST_PATH} with top {len(top)} of {len(scored)} scored companies.")


if __name__ == "__main__":
    generate()
