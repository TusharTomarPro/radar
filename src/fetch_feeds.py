"""
fetch_feeds.py
Pulls all RSS feeds listed in config/feeds.yaml, returns new (unseen) articles.
Keeps a record of seen article links in research/_seen.json so we never re-process the same article.
"""

import os
import json
import yaml
import feedparser

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
FEEDS_PATH = os.path.join(BASE_DIR, "config", "feeds.yaml")
SEEN_PATH = os.path.join(BASE_DIR, "research", "_seen.json")


def load_seen():
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH) as f:
            return set(json.load(f))
    return set()


def save_seen(seen_set):
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(sorted(seen_set), f, indent=2)


def fetch_new_articles():
    with open(FEEDS_PATH) as f:
        config = yaml.safe_load(f)

    all_feeds = config.get("western_feeds", []) + config.get("indian_feeds", [])
    seen = load_seen()
    new_articles = []

    for feed in all_feeds:
        try:
            parsed = feedparser.parse(feed["url"])
        except Exception as e:
            print(f"[warn] could not fetch {feed['name']}: {e}")
            continue

        for entry in parsed.entries:
            link = entry.get("link", "")
            if not link or link in seen:
                continue
            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            new_articles.append({
                "source": feed["name"],
                "title": title,
                "summary": summary,
                "link": link,
            })
            seen.add(link)

    save_seen(seen)
    return new_articles


if __name__ == "__main__":
    articles = fetch_new_articles()
    print(f"Found {len(articles)} new articles.")
    for a in articles[:5]:
        print(" -", a["source"], "|", a["title"])
