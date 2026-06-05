# Datacenter Site Planning Map

Interactive map app for finding and evaluating datacenter sites in the US. Draw a search area, score candidates on power + connectivity, toggle transmission/water overlays, and use an AI assistant to compare sites, check constraints, and generate IC memos.

## Repo structure

| Directory | Stack | Role |
|-----------|-------|------|
| `datacenter/` | Next.js 15, React 19, Mapbox, OpenAI | Map UI, chat sidebar, LLM tool routes |
| `fiber_api/` | FastAPI, DuckDB, external geospatial APIs | Scoring engine, overlays, data aggregation |

## Run locally

**Backend** (port 8000):

```bash
cd fiber_api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

**Frontend** (port 3000):

```bash
cd datacenter
# create .env with OPENAI_API_KEY, optional NEXT_PUBLIC_MAPBOX_TOKEN
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Environment variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `OPENAI_API_KEY` | `datacenter/.env` | Chat agent + site explanations + memos |
| `NEXT_PUBLIC_MAPBOX_TOKEN` | `datacenter/.env` | Map tiles (required for map UI) |
| `MAPBOX_TOKEN` | `fiber_api/.env` | Geocoding via Mapbox (optional; falls back to Nominatim) |
| `NEXT_PUBLIC_API_URL` | `datacenter/.env` | Backend URL (defaults to `http://localhost:8000`) |

## Features

- **Rectangle search** — drag a box on the map; backend scores a grid (fast mode: local DuckDB for transmission + broadband)
- **Heatmap + top markers** — colored suitability cells, click for subscores and AI blurbs
- **US-wide overlays** — transmission lines and USGS water sites (disk-cached after first load)
- **AI chat** — agentic loop with tools for geocoding, site search, climate/water/power data, comparisons, deal-breakers, reweighting, and IC memos
- **Map-aware context** — pin sites, discuss draw results, reference “site 2” in follow-ups

## Tests

```bash
cd datacenter
npm test              # unit + chat tool integration
npm run test:e2e      # live /api/chat smoke test (needs dev server + OpenAI key)
```

---

## How I used AI coding tools (Cursor)

I built most of this project with **Cursor** (Agent mode) as a pair programmer — not as a one-shot code generator. The workflow was: I described the product goal, the agent explored the repo, proposed a plan, implemented in small diffs, and I verified with tests and the running app.

### What I used Cursor for

1. **Codebase exploration** — Onboarding into a repo with two apps (`datacenter/` + `fiber_api/`). The agent mapped existing endpoints, scoring logic, and what was already wired to the LLM vs. what was missing.

2. **Vertical slices, not throwaway prototypes** — Example flow the agent implemented end-to-end:
   - `findSiteCandidates` API client methods
   - drag-rectangle search on the Mapbox map
   - score-colored markers + popup with subscores
   - chat sidebar seeded with selected site context

3. **Backend debugging with real failures** — When scores looked wrong or requests were slow, I pasted symptoms and the agent traced root causes, e.g.:
   - climate subscore always 0.5 (wrong feature key mapping)
   - water always 0 (bad USGS URL)
   - draw-box taking 60s+ (36 cells × slow external APIs → added `fast` mode)
   - geocoding returning wrong cities (Mapbox + seed cache + prompt guardrails)
   - DuckDB thread safety (`con.cursor()` per concurrent query)

4. **LLM product features (Tiers 1–3)** — I asked for structured capability tiers; the agent added:
   - **Tier 1:** chat tools wired to existing APIs (`get_climate`, `get_water_resources`, `get_transmission_lines`, `get_broadband`, `compare_sites`)
   - **Tier 2:** map context in chat (history, pinned sites, draw-box summary, click-to-ask)
   - **Tier 3:** analyst tools (`apply_site_constraints`, `check_deal_breakers`, `reweight_sites`, `generate_site_memo`) plus unit/e2e tests

5. **UI polish** — Markdown rendering in chat (`remark-gfm` + styled components), overlay toggles, memo download, clearer chat error messages when the dev server or API key was misconfigured.

6. **Test harnesses** — Scripts under `datacenter/scripts/` so the agent (and I) could verify logic without clicking through the UI every time.


I basically had a plan already on how I would make this project, and I asked the agents to implement it for me. I designed how the apis would work and what we would need and how the communication would work, and the agent just implemented the code. The features were also something I made and told the agent in detail after using the competitor tools myself.

### Honest limitations

- AI sped up boilerplate and wiring; it still needed **live verification** (browser, API logs, test scripts).
- External API flakiness (Overpass, Nominatim rate limits) required neutral fallbacks and caching — the agent suggested fixes, but judging production readiness is on me.
- Long agent sessions sometimes needed **conversation summarization**; re-stating the current goal helped avoid drift.

### Tooling summary

| Tool | Use in this project |
|------|---------------------|
| **Cursor Agent** | Feature implementation, debugging, tests, README |
| **Cursor chat** | Design questions (LLM tiers, map UX), quick fixes |
| **OpenAI API** | In-app chat agent (`gpt-4o-mini`), site blurbs, IC memos |
| **Terminal / curl / npm test** | Validation loop the agent ran repeatedly |

If you’re reproducing this approach: treat the AI as a fast junior engineer with repo access — give it a clear outcome, require tests or a demo path, and review every diff.
