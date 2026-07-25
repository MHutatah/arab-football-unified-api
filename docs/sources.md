# Source register

Every source the engine ingests, what it provides, and — critically — **whether its
license permits redistribution** in our ODbL snapshot.

## The license gate (non-negotiable)

We publish an open database, so a source's license decides how its data may be used:

| License | Redistribute in the snapshot? | Handling |
|---|---|---|
| **CC0** / Public Domain | ✅ yes | Ingest freely; attribute as courtesy |
| **ODbL** / ODC-BY | ✅ yes | Ingest; attribution **required**; share-alike already matches ours |
| **CC-BY** | ✅ yes | Ingest; attribution **required** |
| **CC-BY-SA** | ✅ yes | Compatible with our share-alike stance |
| **CC-BY-NC** | ❌ no | Non-commercial restricts downstream users — refuse |
| **Unknown / unstated** | ❌ no | Never redistribute. May be used privately to *cross-check*, never to publish |
| Scraped API output | ⚠️ facts only | Publish derived facts, never verbatim source text; attribute |

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
| [`rossi14/saudi-pro-league-transfers`](https://www.kaggle.com/datasets/rossi14/saudi-pro-league-transfers) | **Unknown** | Saudi Pro League transfers since 2000 | ❌ **Do not redistribute.** Exactly on-topic, so worth asking the author to relicense; until then use only to *validate* our own data privately. |
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

1. **License first.** No dataset enters the pipeline before its license is recorded.
2. **Bulk fills history; APIs keep it fresh.** Dumps are a one-shot backfill, then live
   collectors maintain the head.
3. **The resolver is the only door.** Bulk rows go through the same entity resolution as
   API records — a CSV club name gets no shortcut.
4. **Never trust a dump's ids.** External ids become aliases, never our canonical ids.
5. **Cross-check, don't overwrite.** When a dump disagrees with a live source on a
   result, prefer the live source and flag the conflict rather than silently replacing.
