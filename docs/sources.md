# Source register

Every source the engine ingests, what it provides, and — critically — **whether its
license permits redistribution** in our ODbL snapshot.

## Source tiers

We publish an open database, so a source's license decides *how* its data may be
used — not simply whether we may look at it. Three tiers:

| Tier | Licenses | Role |
|---|---|---|
| **A — Publishable** | CC0 · ODbL · ODC-BY · CC-BY · CC-BY-SA | Ingested and **redistributed** in the snapshot, with attribution |
| **B — Reference** | Unstated / unknown | Ingested into the **working** database for discovery and cross-checking. A fact it surfaces enters the snapshot **only once corroborated by a Tier-A or live source**, cited to that source |
| **C — Refused** | CC-BY-NC · explicit no-redistribution | Not ingested at all |

**Why Tier B is legitimate.** Copyright and database rights protect a *compilation*,
not the individual facts inside it. "Player X moved from club A to club B on
2023-07-01 for €X" is a fact, and re-deriving it from a corroborating source is not
redistribution of someone's database. So a reference source may point us at what to
verify — it may never be copied wholesale into what we publish.

**The corroboration rule.** A Tier-B row is stored with `tier='reference'` and is
excluded from every snapshot export. It becomes publishable only when an independent
Tier-A or live source confirms it; the published row then cites *that* source, and
the Tier-B origin is recorded internally as the discovery hint.

Every ingested row records `source` and, for bulk datasets, the dataset id + version,
so provenance and attribution survive into the published snapshot.

---

## Live collectors (recurring)

| Source | Access | Provides | Notes |
|---|---|---|---|
| **365Scores** (`webws.365scores.com`) | free, unofficial | Fixtures, results, lineups, standings for Arab leagues | Params are **plural** (`competitions=`, `competitors=`, `athletes=`). Saudi league = **649**. Wrap thin, fail soft. |
| **ESPN** (`site.api.espn.com`) | free, unofficial | Fixtures, results, team schedules; league-scoped ids | Correct club identity per league — good cross-check |
| **TheSportsDB** | free key | Supplementary fixtures, crests | Unreliable for Arab leagues; low trust |
| **API-Football** | free key | Fixtures, historical seasons, H2H | Free tier is **historical-only (2022–2024)** for most endpoints |
| **Arabic news RSS** | free | Articles → LLM fact extraction | Phase 4 |

## Bulk / archival datasets (one-shot, then topped up)

Kaggle and similar dumps are the fastest path to **all-time depth** — years of history
in one download instead of thousands of paged API calls. Only license-clean datasets
are ingested.

| Dataset | License | Provides | Verdict |
|---|---|---|---|
| [`martj42/international-football-results-…`](https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017) | **CC0** | 49,000+ international results, 1872→present | ✅ **Ingest.** The national-team gap-filler: Gulf Cup, Arab Cup, AFC Asian Cup, WC qualifiers, friendlies for every Arab nation. Tiny (1.3 MB), enormous historical reach. |
| [`davidcariboo/player-scores`](https://www.kaggle.com/datasets/davidcariboo/player-scores) | **CC0** | Transfermarkt mirror: players, clubs, **appearances**, games, valuations (223 MB) | ✅ **Ingest** — highest value. A ready-made appearance spine + player bios. **Verify Arab-league coverage at ingest**; may skew to top European competitions (Arab players abroad are still in scope as career stops). |
| [`ahmedaelgohary/10-seasons-egyptian-league`](https://www.kaggle.com/datasets/ahmedaelgohary/10-seasons-egyptian-league) | **ODbL** | Egyptian Premier League matches 2015–2025 | ✅ **Ingest.** Direct Arab-league history; license already matches ours. |
| [`sergionefedov/global-football-transfer-market-2010-2026`](https://www.kaggle.com/datasets/sergionefedov/global-football-transfer-market-2010-2026) | **CC0** | ~15,000 transfers 2010–2026, market values | ✅ **Ingest** for the `transfers` table; cross-check against news-extracted transfers. |
| [`rossi14/saudi-pro-league-transfers`](https://www.kaggle.com/datasets/rossi14/saudi-pro-league-transfers) (Steven Rossi) | **Unstated** → **Tier B** | Saudi Pro League transfers in/out since 2000 | ⚠️ **Keep as a reference source.** The single most on-topic dataset found — 25 years of Saudi transfer history, exactly our core league. Ingested into the working DB for **discovery and cross-checking**, `tier='reference'`, excluded from snapshot exports. Each transfer it surfaces is verified against a Tier-A/live source and published citing that source. **Action:** ask the author to apply CC0 — a one-line relicense promotes the whole set to Tier A. |
| [`alioh/Saudi-Professional-League-Datasets`](https://github.com/alioh/Saudi-Professional-League-Datasets) (GitHub) | check repo | Saudi league results since 2000 | ⚠️ Verify license before ingest. |

**Search note.** Kaggle's web search is JS-rendered, but the public API answers
unauthenticated:
`GET https://www.kaggle.com/api/v1/datasets/list?search=<terms>` returns titles,
`licenseNameNullable` and sizes — enough to triage new candidates automatically.

## Reference sources

| Source | License | Provides |
|---|---|---|
| **Wikipedia** (ar/en) | CC-BY-SA | Club/player history, honours, season tables — LLM-normalized |
| **Transfermarkt** (direct scrape) | restrictive | Careers, fees — prefer the CC0 Kaggle mirror above over scraping |

---

## Rules of engagement

1. **Tier first.** No dataset enters the pipeline before its license — and therefore
   its tier — is recorded here.
2. **Tier B never reaches a snapshot unverified.** The export filters
   `tier='reference'`; publishing requires independent corroboration.
3. **Bulk fills history; APIs keep it fresh.** Dumps are a one-shot backfill, then live
   collectors maintain the head.
4. **The resolver is the only door.** Bulk rows go through the same entity resolution as
   API records — a CSV club name gets no shortcut.
5. **Never trust a dump's ids.** External ids become aliases, never our canonical ids.
6. **Cross-check, don't overwrite.** When a dump disagrees with a live source on a
   result, prefer the live source and flag the conflict rather than silently replacing.
7. **Chase relicensing.** When a Tier-B source is valuable (Saudi transfers), ask the
   author for CC0 — the cheapest possible upgrade to Tier A.
