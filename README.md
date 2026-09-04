# Research Radar

Runs 24/7 for free on GitHub's servers. Every few hours it:
1. Checks a list of tech news feeds (Western + Indian) for new articles
2. Uses a free AI model to filter out noise (keeps only "new product/business idea" articles)
3. Uses a slightly better free AI model to write a structured research note on each one
4. Saves everything as files in this repo, organized by day and by company

You review the results once a day (your 18:00-19:00 slot) by just reading the files.

---

## One-time setup (about 15 minutes)

### 1. Get free API keys
You don't need all of these -- even ONE working key will make the whole thing run.
More keys = more fallback capacity if one gets rate-limited.

- **Groq** (recommended, fast, generous free tier): https://console.groq.com/keys -- sign up, create key
- **Gemini** (Google, good quality free tier): https://aistudio.google.com/apikey -- sign in with Google, create key
- **Cerebras** (optional extra fallback): https://cloud.cerebras.ai/ -- sign up, create key
- **OpenRouter** (optional, has free models): https://openrouter.ai/keys -- sign up, create key

None of these should ask for a credit card for the free tier. If one does, skip it -- you have others.

### 2. Create a GitHub repo
- Go to https://github.com/new
- Name it e.g. `research-radar`, set it to **Public** (required for free unlimited Actions minutes) or Private (you get 2000 free minutes/month, still plenty)
- Don't initialize with a README (we already have one)

### 3. Upload this code
Easiest way since you're not deep into git:
- On your new repo's GitHub page, click "uploading an existing file"
- Drag in all the files/folders from this project (keep the folder structure exactly as-is: `.github/workflows/scan.yml` must stay at that exact path)
- Commit directly to the `main` branch

### 4. Add your API keys as secrets (this keeps them private, not in your code)
- In your repo, go to **Settings > Secrets and variables > Actions**
- Click **New repository secret** for each key you got in step 1:
  - Name: `GROQ_API_KEY`, Value: (paste your key)
  - Name: `GEMINI_API_KEY`, Value: (paste your key)
  - Name: `CEREBRAS_API_KEY`, Value: (paste your key) -- optional
  - Name: `OPENROUTER_API_KEY`, Value: (paste your key) -- optional

### 5. Turn it on
- Go to the **Actions** tab in your repo
- You'll see "Research Radar Scan" -- click it, then click **Run workflow** to test it manually once
- Check it worked: after a minute or two, look in the `research/` folder in your repo -- you should see new dated folders and files appear
- After that, it runs automatically every 3 hours, forever, for free, and commits results straight to this repo

---

## Your daily routine (18:00-19:00)
1. Open `research/watchlist.md` -- see everything found so far in one table
2. Open today's `research/<date>/daily-log.md` -- see what's new today
3. For anything interesting, open `research/companies/<name>/your-notes.md` and add your human-intuition take, dated
4. Manually correct the `badge_guess` if the AI got it wrong (it's a first-pass guess, not gospel)

---

## Tuning it
- **Change how often it runs:** edit the `cron` line in `.github/workflows/scan.yml`. Every 3 hours is `0 */3 * * *`. Every hour is `0 * * * *`. (Cron times are UTC, so IST is UTC+5:30.)
- **Add/remove news sources:** edit `config/feeds.yaml`
- **Change which AI models get tried and in what order:** edit `FILTER_TIER` and `EXTRACT_TIER` lists in `src/llm_router.py`
- **Check API usage/failures:** look at `research/_call_log.jsonl` -- one line per AI call, tells you which provider handled it and if anything failed

## If everything is rate-limited some days
The pipeline just logs the failure and skips that article -- it won't crash. Check `_call_log.jsonl`
to see which providers are getting hit. If one provider fails a lot, reorder it lower in the tier
lists in `llm_router.py`, or get a key from a provider you haven't added yet.
