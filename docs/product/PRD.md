# Arab Football Unified API — Product Requirements Document

**Status:** v1.0 · decisions locked Jul 25, 2026
**Design spec:** `docs/SPEC.md` · **Roadmap:** `ROADMAP.md` · **Traceability:** `../requirements-traceability.md`

---

## 1. Problem

Arab and Gulf football is the **worst-covered corner of world football** in every
available data API. Building Armchair Pundit proved it concretely:

- The Roshn Saudi League returned **zero fixtures** from one "supported" provider,
  and an **English League One squad** from another.
- `"Al Hilal"` resolved to a **South Sudanese** club; `"Al Ahli"` to a **Jordanian**
  one — producing a football pundit that cited the wrong country's results.
- Recent form and head-to-head were missing or wrong.
- **Deep history** — careers, transfers, honours, all-time records — effectively
  doesn't exist at usable depth for these leagues in any API.

The root cause isn't laziness by those providers; it's that the data is fragmented
across **Arabic-language sources** with inconsistent transliteration and rampant
namesakes, and no aggregator has done the normalization work.

## 2. Vision

> The definitive, open dataset for Arab football — every club and player, all-time,
> correctly identified across Arabic and English — published as a **downloadable
> database anyone can build on**, not a service anyone must depend on.

We do the messy gathering once and give away the result. Feeds die (Kooora's own
app API did); an open, stored, redistributable dataset doesn't.

## 3. Personas

| Persona | Goal | Primary surface |
|---|---|---|
| **App developer** (external) | Ship an Arab-football product without building an ingestion pipeline | `git clone` + `make pull-db` → the SQLite snapshot |
| **Data/ML practitioner** | Analyze or train on complete, correctly-identified historical data | The snapshot, queried directly with SQL/pandas |
| **Armchair Pundit** (first-party) | Always-fresh fixtures, form, H2H and context for live debates | The read API against the continuously-updated store |
| **Maintainer** (us) | Run collectors, adjudicate ambiguous entities, publish monthly | Collector CLI + review queue |

## 4. Pain points → features

| Pain point | Feature | Status |
|---|---|---|
| "The same club has five spellings across two scripts" | **Language-neutral canonical id** — every spelling and provider id is an alias | ✅ built |
| "'Al Hilal' returns a club from another country" | **Scoped resolution + provisional entities** — never a silent wrong match | ✅ built |
| "No API has Saudi/Gulf history worth using" | **All-time archive** — matches, seasons, honours, careers | Sprint 2 |
| "Paging an API for 20 years of history takes forever" | **Bulk open-dataset backfill** — license-clean dumps (Kaggle) for national teams, appearances and transfers | Sprint 2 |
| "Careers and H2H aren't exposed by any feed" | **Derived from an appearance spine** — computed, not fetched | Sprint 1–2 |
| "One provider goes stale and my app breaks" | **Multi-source collectors, fail-soft**, with the store as the truth | Sprint 1/3 |
| "Transfers and injuries only exist in Arabic news" | **LLM fact extraction** (Arabic + English) with provenance | Sprint 4 |
| "I don't want to depend on someone's uptime or API key" | **MIT code + ODbL monthly snapshot** — no key, no rate limit | Sprint 3 |

## 5. Functional requirements

### Identity (the foundation)
- **FR-1** Assign every club, player, competition, manager and venue a
  **language-neutral canonical id**; names are labels, never keys.
- **FR-2** Carry `name_ar` and `name_en` for every entity and return both.
- **FR-3** Resolve an incoming record to its canonical entity by, in order:
  provider id → normalized name in scope → cross-script skeleton → bounded fuzzy.
- **FR-4** **Never guess**: an unresolved or ambiguous record creates a
  **provisional** entity in a review queue rather than matching a wrong entity.
- **FR-5** Learn every provider id and spelling seen, so later passes resolve exactly.

### Archive & derivation
- **FR-6** Store an all-time **match archive** with per-provider ids and provenance.
- **FR-7** Store **appearances** (player × match × team) as the spine for derivation.
- **FR-8** **Derive** recent form, head-to-head, squads and career paths from the
  store — never from a gated or per-entity upstream endpoint.
- **FR-9** Store season records, honours and transfers per entity.
- **FR-10** Match state is **forward-only**: a stale feed can never un-finish a game.

### Collection
- **FR-11** Ingest from multiple sources behind one collector interface; any source
  may be absent, keyless, or failing without stopping the pipeline.
- **FR-12** Record every collector run (`source_runs`) with counts and errors.
- **FR-18** Ingest **bulk open datasets** (Kaggle and equivalents) as a one-shot
  historical backfill, through the same resolver as live records — and **only when
  the dataset's license permits redistribution** (CC0 / ODbL / CC-BY / CC-BY-SA).
  Record the dataset id, version and license with the imported rows. See
  [`../sources.md`](../sources.md).

### Enrichment
- **FR-13** Extract typed facts (transfer, injury, suspension) from Arabic and
  English news via the LLM gateway, each with entities, date, source URL and confidence.
- **FR-14** Drop any extracted fact whose entities don't resolve — no invented clubs.

### Distribution
- **FR-15** Publish a **monthly SQLite snapshot** stamped with version, generation
  time, license and row counts.
- **FR-16** Ship a bundled **read API** (`/v1`) that a consumer runs themselves;
  responses are bilingual with a `?lang=` display selector.
- **FR-17** License code **MIT** and data **ODbL**, with source attribution and a
  takedown path.

## 6. Success metrics

| Metric | Target |
|---|---|
| Wrong-entity matches (namesake collisions) in a published snapshot | **0** |
| Provisional rate after a full-league ingest | < 5 % of entities |
| Coverage — Arab-world leagues with all-time archive | 100 % of the v1 competition list |
| Time for a new developer to first query | < 5 min from `git clone` |
| Consumer dependency on our uptime | **none** (snapshot is self-contained) |
| Snapshot freshness | ≤ 1 month (armchair: continuous) |

## 7. Non-goals (v1)

- A hosted/managed SaaS API with an SLA — we publish data and tooling, not uptime.
- Non-Arab leagues as primary data (European clubs appear only as opponents or
  career stops).
- Minute-by-minute live event streams; sports other than football.
- User accounts, auth, or write APIs.
- Paid professional feeds (Opta, Sportmonks).

## 8. Constraints

- **Free-first sources.** Keyed providers are optional redundancy; the engine must
  work without any paid tier.
- **Unofficial endpoints are fragile** (365Scores) — wrap thin, monitor, fail soft.
- **No live network in the test suite** — collectors are tested against canned payloads.
- **Redistribution is a gray area** — publish *facts*, not verbatim source text;
  attribute sources; honor takedowns.
- **License gate on every source.** Because we republish an open database, a source
  whose license is unstated or non-commercial can never enter the snapshot — it may
  only be used privately to cross-check. The register in `docs/sources.md` is the
  authority, and no dataset is ingested before its license is recorded there.
- **Single maintainer.** Scope must survive being worked on part-time: automation
  over manual curation, review queue over exhaustive hand-checking.
