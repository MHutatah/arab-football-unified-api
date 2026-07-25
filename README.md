# Arab Football Unified API

An open football **data engine for the Arab world** — the region every commercial
API covers worst.

This is **not a hosted API**. It's an MIT-licensed project plus a monthly,
downloadable database: clone the repo, pull the latest snapshot, and build.

```bash
git clone https://github.com/MHutatah/arab-football-unified-api
cd arab-football-unified-api
make pull-db        # latest snapshot (SQLite, ODbL)
make serve          # read API on :8100  — or just open the .db yourself
```

## What's in it

| | |
|---|---|
| **Coverage** | The whole Arab world — Gulf, Levant, Egypt, Maghreb — clubs, players, national teams, competitions |
| **History** | All-time, per entity: match archive, season records, honours, transfers, full career paths |
| **Identity** | A language-neutral canonical id; `name_ar` + `name_en` always returned |
| **Live** | Fixtures, results, form, head-to-head, odds |
| **Enriched** | Typed facts (transfers, injuries, suspensions) extracted from Arabic + English news |

## Why it exists

Every existing feed fails on Arab football. The Saudi Pro League returns zero
fixtures from one "supported" API and an English-League-One squad from another;
`"Al Hilal"` resolves to a South Sudanese club and `"Al Ahli"` to a Jordanian one;
deep history barely exists at all. The data is fragmented across Arabic-language
sources no aggregator bothers to normalize.

So this project does the messy part once — gather from many sources, resolve
identity across both scripts, store it — and publishes the result.

## Design

Two things ship: **the code** (collectors, resolver, schema, a bundled read API)
and **the data** (a SQLite snapshot, refreshed monthly).

```
sources ─► collectors ─► entity resolution ─► store ─► snapshot + read API
                              │                 │
                     Arabic ↔ English    all-time archive;
                     language-neutral    careers, squads and H2H are
                     canonical ids       DERIVED, never fetched
```

**Derive, don't fetch.** Player careers, squads and head-to-head aren't pulled
from fragile per-entity endpoints — they're computed from a stored spine of
match appearances. Feeds die (Kooora's own app API did); a store doesn't.

Full design: [`docs/SPEC.md`](docs/SPEC.md) · plan: [`docs/sprint/`](docs/sprint/)

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

## Licenses

- **Code** — MIT (`LICENSE`)
- **Data** — Open Database License, ODbL 1.0 (`LICENSE-DATA`). Use it, adapt it,
  redistribute it; keep derivative databases open and attribute the source.

Data is aggregated from public sources and published as **facts**, not verbatim
source text. Corrections and takedown requests: open an issue.
