# Arab Football Unified API — Backlog (Theme → Initiative → Epic → Story)

The Atlassian hierarchy used across MHutatah projects. This document is the
**source** for the GitHub issues; `scripts/seed_issues.py` creates them from it.

- **Theme** — a long-running strategic area
- **Initiative** — a collection of epics driving toward one release goal
- **Epic** — a large body of work broken into stories
- **Story** — one user-visible increment: "As a … I want … so that …"

Requirement ids (**FR-N**) come from [`PRD.md`](./PRD.md) · phases from
[`ROADMAP.md`](./ROADMAP.md) · status from
[`../requirements-traceability.md`](../requirements-traceability.md).

### Label taxonomy

| Label group | Values |
|---|---|
| `type:` | `theme` · `initiative` · `epic` · `story` |
| `theme:` | `arab-football-data` |
| `initiative:` | `v0.1-foundation` · `v0.2-backfill` · `v0.3-publish` · `v0.4-enrichment` |
| `epic:` | `identity` · `collectors` · `derivation` · `api` · `distribution` · `testing` · `docs` |
| `size:` | `S` (≤½ day) · `M` (1 day) · `L` (1.5–2 days) |
| priority | `p1-high` · `p2-medium` · `p3-low` |

### Personas (for story voice)

`app developer` (external consumer) · `data practitioner` · `Armchair Pundit`
(first-party consumer) · `maintainer`

---

# [THEME] Arab-football data infrastructure

`type:theme` · `theme:arab-football-data`

**Goal.** Own the data layer for Arab and Gulf football — the region every
commercial API covers worst — and publish it openly so any developer can build on
it without rebuilding the ingestion.

**Initiatives**

- [ ] **v0.1.0** — Foundation: entity spine + first collector *(this initiative)*
- [ ] v0.2.0 — All-time backfill
- [ ] v0.3.0 — Breadth & monthly publishing
- [ ] v0.4.0 — News enrichment

---

# [INITIATIVE v0.1.0] Foundation — entity spine + first collector

`type:initiative` · `theme:arab-football-data` · `initiative:v0.1-foundation`

> **Parent theme:** [THEME] Arab-football data infrastructure

## Initiative — v0.1.0

**Goal.** Stand up the language-neutral entity registry and the bilingual resolver,
prove them against the exact failures that motivated the project, and land one real
collector end-to-end (Saudi Pro League via 365Scores) so the pipeline is
demonstrably real. Depth, breadth and enrichment come later — **if identity is
wrong, everything built on top is wrong**, so identity ships first and ships correct.

**Target release.** `v0.1.0`

**Outcomes / definition of done**

- [ ] `الهلال`, `Al-Hilal`, `Al Hilal`, `AlHilal SFC` and 365Scores id `5457` resolve to **one** entity
- [ ] Saudi vs Sudanese "Al Hilal", and three "Al Ahli"s in three countries, stay **separate**
- [ ] An unresolvable record becomes a **provisional** entity in the review queue — never a wrong match
- [ ] A full Roshn Saudi League season is ingested, resolved and stored
- [ ] Form, H2H, squad and career are **derived from the store** with zero network calls
- [ ] A stamped SQLite snapshot round-trips in a fresh process
- [ ] FR-1…FR-5 ✅ in the traceability matrix

**Dependencies**

- 365Scores web backend (mapped: plural params, Saudi competition id **649**)
- No armchair changes in this initiative

_An initiative is a collection of epics driving toward one goal (Atlassian model)._

---

### Epics (5)

- [x] **E1.1** — Canonical entity registry & bilingual resolution ✅ *delivered in scaffold*
- [ ] **E1.2** — Collector framework & Saudi ingestion
- [ ] **E1.3** — Appearance spine & derivation
- [ ] **E1.4** — Bundled read API
- [ ] **E1.5** — Snapshot & distribution

---

## [EPIC 1.1] Canonical entity registry & bilingual resolution

`type:epic` · `epic:identity` · `size:L` · `p1-high` · `initiative:v0.1-foundation`
**FRs:** FR-1 … FR-5 · **Status:** ✅ delivered in the scaffold

> **Parent initiative:** [INITIATIVE v0.1.0] Foundation

## Epic

Give every club, player and competition a **language-neutral canonical id**, and
resolve any incoming record — any provider, any script, any spelling — onto it.
This is the moat: every commercial API fails here for Arab football, and every
derived fact downstream inherits the error.

**In scope**

- Portable schema (`entities`, `aliases`) usable in Postgres and SQLite
- Arabic + Latin normalization, cross-script matching, bounded fuzzy fallback
- Resolution ladder with a provisional/review outcome instead of guessing
- Alias learning so later passes resolve exactly

**Out of scope**

- Manual curation UI (CLI review is enough for v0.1)
- Player-level disambiguation beyond name+country (needs squad context — Epic 1.3)

**Epic acceptance criteria**

- [x] One club across 3 providers and 2 scripts resolves to a single id
- [x] Wrong-country namesakes never merge
- [x] Unresolvable input creates a provisional entity, surfaced for review
- [x] Every provider id and spelling seen is learned as an alias

**Key files / surfaces**

- `arabfootball/store/schema.sql`
- `arabfootball/resolve/normalize.py`
- `arabfootball/resolve/resolver.py`
- `arabfootball/store/db.py`

**Dependencies** — none (this is the root of the build)

_An epic is a large body of work broken into stories._

### Stories (6)

#### [STORY 1.1.1] Portable bilingual schema — `size:M` `p1-high` `epic:identity` ✅

> **Parent epic:** [EPIC 1.1]

**User story**

> As a **maintainer**, I want **one schema that runs in both Postgres and SQLite** so that **the database I build is the database I publish**.

**Acceptance criteria**

- [x] `entities` carries a language-neutral id, `name_ar`, `name_en`, country, meta, provisional flag
- [x] `aliases` maps (provider, provider_id, name_variant) → entity, uniquely
- [x] Archive tables exist: `matches`, `appearances`, `team_seasons`, `transfers`, `honours`
- [x] `source_runs` + `snapshot_meta` exist for provenance
- [x] No vendor-specific types; applies cleanly via `Store()`

#### [STORY 1.1.2] Arabic + Latin name normalization — `size:M` `p1-high` `epic:identity` ✅

> **Parent epic:** [EPIC 1.1]

**User story**

> As a **maintainer**, I want **every spelling of a club to reduce to one comparable key** so that **the same team from two sources isn't stored twice**.

**Acceptance criteria**

- [x] Arabic: diacritics stripped, letter variants folded (أ/إ/آ→ا, ة→ه, ى→ي), ال prefix removed
- [x] Latin: accents stripped, punctuation dropped, stopwords removed (`fc`, `sc`, `club`…)
- [x] Fused article handled: `AlHilal` → `hilal`
- [x] Transliteration variance folded: `Ahly`/`Ahli`, `Faysaly`/`Faisaly`
- [x] `xkey()` produces a cross-script consonant skeleton so `الهلال` and `Al Hilal` meet

#### [STORY 1.1.3] Resolution ladder that refuses to guess — `size:L` `p1-high` `epic:identity` ✅

> **Parent epic:** [EPIC 1.1]

**User story**

> As an **app developer**, I want **the dataset to never contain a wrong-country club** so that **my app doesn't cite a Sudanese team's results for a Saudi match**.

**Acceptance criteria**

- [x] Order: provider id → normalized name in scope → cross-script → bounded fuzzy
- [x] Fuzzy requires a threshold **and** a margin over the runner-up
- [x] Ambiguity or no match ⇒ provisional entity, never a confident wrong match
- [x] All matching is scoped by type + country

#### [STORY 1.1.4] SQLite store & review queue — `size:M` `p1-high` `epic:identity` ✅

> **Parent epic:** [EPIC 1.1]

**User story**

> As a **maintainer**, I want **provisional entities collected in one place** so that **I can adjudicate what the resolver couldn't**.

**Acceptance criteria**

- [x] Store implements the resolver interface (`find_by_provider`, `find_by_norm`, `candidates`, `create_entity`, `add_alias`)
- [x] `review_queue()` lists provisional entities oldest-first
- [x] Cross-script lookup guarded by a minimum skeleton length

#### [STORY 1.1.5] Adversarial identity suite — `size:M` `p1-high` `epic:testing` ✅

> **Parent epic:** [EPIC 1.1]

**User story**

> As a **maintainer**, I want **the known failure modes encoded as tests** so that **a regression in matching can never reach a published snapshot**.

**Acceptance criteria**

- [x] Saudi vs Sudanese "Al Hilal" assert distinct
- [x] Three "Al Ahli"s (SA/JO/EG) assert distinct
- [x] One club across providers + scripts asserts identical
- [x] Provisional path asserted; alias learning asserted
- [x] Suite makes zero network calls

#### [STORY 1.1.6] Review-queue CLI — `size:M` `p2-medium` `epic:identity`

> **Parent epic:** [EPIC 1.1]

**User story**

> As a **maintainer**, I want **to merge a provisional entity into the right canonical one from the CLI** so that **corrections are a one-liner and are remembered forever**.

**Acceptance criteria**

- [ ] `make review` lists provisional entities with their aliases and source
- [ ] A merge command repoints aliases to the canonical entity and deletes the provisional
- [ ] The merged spelling is recorded as an alias so the next ingest resolves exactly
- [ ] Merging is idempotent and logged

---

## [EPIC 1.2] Collector framework & Saudi ingestion

`type:epic` · `epic:collectors` · `size:L` · `p1-high` · `initiative:v0.1-foundation`
**FRs:** FR-6, FR-10, FR-11, FR-12

> **Parent initiative:** [INITIATIVE v0.1.0] Foundation

## Epic

One interface every source implements, and the first real source behind it: the
365Scores web backend for the Roshn Saudi League. Any collector may be keyless,
absent, or failing without stopping the pipeline — the store is the truth, not
any upstream.

**In scope**

- Collector interface, per-source rate budget, graceful-empty contract
- `source_runs` observability for every run
- 365Scores adapter (fixtures/results, competition **649**)
- Ingest pipeline: raw → resolver → `matches`, forward-only status
- Seeding Saudi competition + club entities from standings

**Out of scope**

- Other countries (Initiative v0.3), historical seasons (v0.2), news (v0.4)
- Keyed providers — the free path must work alone first

**Epic acceptance criteria**

- [ ] `make collect-saudi` ingests the current season with every club resolved
- [ ] A failing source produces a `source_runs` row and an empty result, not an exception
- [ ] Re-running is idempotent — no duplicate matches
- [ ] A finished match is never reverted to scheduled by a stale feed

**Key files / surfaces**

- `arabfootball/collectors/base.py`, `arabfootball/collectors/scores365.py`
- `arabfootball/collectors/ingest.py`, `arabfootball/collectors/run.py`

**Dependencies** — Epic 1.1 (resolution)

### Stories (4)

#### [STORY 1.2.1] Collector base & run observability — `size:M` `p1-high` `epic:collectors`

> **Parent epic:** [EPIC 1.2]

**User story**

> As a **maintainer**, I want **every collector to report what it did and fail soft** so that **one dead source never takes the pipeline down or hides a problem**.

**Acceptance criteria**

- [ ] A `Collector` interface with a documented graceful-empty contract (returns `[]`, never raises)
- [ ] Every run writes a `source_runs` row: collector, start/finish, status, inserted, updated, errors
- [ ] A per-source rate budget is enforced
- [ ] Tested with a deliberately failing source

#### [STORY 1.2.2] 365Scores fixtures adapter — `size:M` `p1-high` `epic:collectors`

> **Parent epic:** [EPIC 1.2]

**User story**

> As **Armchair Pundit**, I want **Saudi fixtures and results from a source that actually has them** so that **the lobby isn't empty for the league my users care about most**.

**Acceptance criteria**

- [ ] Fetches via `/web/games/?competitions=649&startDate&endDate` (plural param)
- [ ] Maps to normalized records: teams, kickoff UTC, status, score, provider ids
- [ ] Date-window paging over a season
- [ ] Tested against a canned payload — no live network in CI

#### [STORY 1.2.3] Ingest pipeline with forward-only state — `size:M` `p1-high` `epic:collectors`

> **Parent epic:** [EPIC 1.2]

**User story**

> As an **app developer**, I want **a stale feed to never un-finish a match** so that **a result I already saw doesn't disappear from the data**.

**Acceptance criteria**

- [ ] Each raw record resolves both clubs through the resolver before insert
- [ ] Upsert by provider id, else (teams, kickoff date)
- [ ] Status only moves scheduled → live → finished, never backwards
- [ ] A recorded score survives a resync that reports none
- [ ] Re-ingesting the same payload inserts nothing new

#### [STORY 1.2.4] Seed Saudi competition & clubs — `size:S` `p1-high` `epic:identity`

> **Parent epic:** [EPIC 1.2]

**User story**

> As a **maintainer**, I want **the league's clubs seeded from standings before fixtures load** so that **ingestion resolves against real entities instead of creating provisionals**.

**Acceptance criteria**

- [ ] Competition entity created for the Roshn Saudi League with both names
- [ ] All 18 clubs seeded from `/web/standings/?competitions=649` with 365Scores ids as aliases
- [ ] Provisional rate on the subsequent fixture ingest is measured and recorded

---

## [EPIC 1.3] Appearance spine & derivation

`type:epic` · `epic:derivation` · `size:L` · `p1-high` · `initiative:v0.1-foundation`
**FRs:** FR-7, FR-8

> **Parent initiative:** [INITIATIVE v0.1.0] Foundation

## Epic

The project's defining technical bet: **derive, don't fetch**. Careers, squads and
head-to-head are computed from a stored spine of match appearances rather than
pulled from per-entity endpoints that are gated, fragile, or dead. Feeds die; a
store doesn't.

**In scope**

- Harvest lineups into `appearances` (player × match × team)
- Derive recent form and head-to-head from `matches`
- Derive squad-by-season and player career path from `appearances`

**Out of scope**

- All-time depth (Initiative v0.2) — correctness of the derivation is what ships here
- Per-90 / advanced stats

**Epic acceptance criteria**

- [ ] Every derivation runs offline against the store, with zero network calls
- [ ] H2H for two clubs matches hand-checked real results
- [ ] A player's career path is assembled purely from appearances + transfers

**Key files / surfaces**

- `arabfootball/collectors/lineups.py`
- `arabfootball/derive/` (`form.py`, `h2h.py`, `squad.py`, `career.py`)

**Dependencies** — Epic 1.2 (matches must exist to derive from)

### Stories (4)

#### [STORY 1.3.1] Lineups → appearances — `size:M` `p1-high` `epic:collectors`

> **Parent epic:** [EPIC 1.3]

**User story**

> As a **data practitioner**, I want **every player's participation stored per match** so that **I can compute careers and squads myself without any API**.

**Acceptance criteria**

- [ ] Reads `/web/game/?gameId=&withLineups=true` and parses `members[]`
- [ ] Each player resolves to a canonical entity (scoped by the club, not global)
- [ ] Writes `appearances` with team, minutes, goals, cards where available
- [ ] Idempotent per (player, match)

#### [STORY 1.3.2] Derive recent form — `size:S` `p1-high` `epic:derivation`

> **Parent epic:** [EPIC 1.3]

**User story**

> As **Armchair Pundit**, I want **a club's last-N results from the store** so that **the Pundit's opening odds are grounded in real form and never in a wrong club's record**.

**Acceptance criteria**

- [ ] `form(team, n)` returns the last N finished matches, most recent first
- [ ] Points (W=3, D=1) and a W/D/L record computed correctly from either side
- [ ] Zero network calls; returns empty (never raises) when there's no history

#### [STORY 1.3.3] Derive head-to-head — `size:S` `p1-high` `epic:derivation`

> **Parent epic:** [EPIC 1.3]

**User story**

> As an **app developer**, I want **the meeting history between any two clubs** so that **I get the H2H no free API exposes**.

**Acceptance criteria**

- [ ] `h2h(a, b)` returns past meetings, most recent first, with a W/D/L summary from a's perspective
- [ ] Correct regardless of which club was home
- [ ] Empty result when they've never met — not an error

#### [STORY 1.3.4] Derive squads & career paths — `size:M` `p1-high` `epic:derivation`

> **Parent epic:** [EPIC 1.3]

**User story**

> As a **data practitioner**, I want **a player's full career assembled from appearances** so that **I have the club-by-club history that no Arab-football API provides**.

**Acceptance criteria**

- [ ] `squad(team, season)` lists players with appearance counts
- [ ] `career(player)` returns ordered stints (club, first/last appearance, apps, goals)
- [ ] Stints derive from appearance runs, reconciled with `transfers` when present

---

## [EPIC 1.4] Bundled read API

`type:epic` · `epic:api` · `size:M` · `p2-medium` · `initiative:v0.1-foundation`
**FRs:** FR-2, FR-16

> **Parent initiative:** [INITIATIVE v0.1.0] Foundation

## Epic

The read server that ships **with** the code — a consumer runs it themselves
against the snapshot. No hosted service, no keys, no rate limits. Bilingual by
construction: both names always present, display language a caller's choice.

**In scope** — `/v1/search`, `/v1/teams/{id}`, `/v1/matches`, `/v1/h2h`, `?lang=`
**Out of scope** — auth, write endpoints, hosting, `/v1/players/{id}` depth (v0.2)

**Epic acceptance criteria**

- [ ] `make serve` runs against a snapshot with no configuration
- [ ] Every entity response carries `name_ar` and `name_en`
- [ ] Endpoints answer from the store only

**Key files / surfaces** — `arabfootball/api/main.py`, `arabfootball/api/routes/`

**Dependencies** — Epics 1.1–1.3

### Stories (2)

#### [STORY 1.4.1] `/v1` read endpoints — `size:L` `p2-medium` `epic:api`

> **Parent epic:** [EPIC 1.4]

**User story**

> As an **app developer**, I want **to query the dataset over HTTP without deploying anything** so that **I can prototype in minutes instead of writing SQL**.

**Acceptance criteria**

- [ ] `GET /v1/search?q=` resolves an Arabic **or** English name to entities
- [ ] `GET /v1/teams/{id}` returns the profile with derived form
- [ ] `GET /v1/matches?competition=&from=&to=` filters correctly
- [ ] `GET /v1/h2h?a=&b=` returns the derived record
- [ ] Unknown ids return 404 with a clear message

#### [STORY 1.4.2] Bilingual responses & `?lang=` — `size:S` `p2-medium` `epic:api`

> **Parent epic:** [EPIC 1.4]

**User story**

> As an **app developer building an Arabic UI**, I want **to pick the display language per request** so that **I don't have to map names myself**.

**Acceptance criteria**

- [ ] `name_ar` + `name_en` always present in entity payloads
- [ ] `?lang=ar|en` sets a `display_name`; Arabic is the default
- [ ] Missing translations fall back to the other script rather than null

---

## [EPIC 1.5] Snapshot & distribution

`type:epic` · `epic:distribution` · `size:M` · `p1-high` · `initiative:v0.1-foundation`
**FRs:** FR-15, FR-17

> **Parent initiative:** [INITIATIVE v0.1.0] Foundation

## Epic

Turn the store into the product: a single stamped SQLite file a stranger can
download and use, with the provenance to know what they hold and the licensing to
know what they may do with it.

**In scope** — export + stamping, round-trip verification, quickstart, data
dictionary, monthly-publish workflow **stub**
**Out of scope** — the live monthly automation box → Releases (Initiative v0.3)

**Epic acceptance criteria**

- [ ] `make snapshot` produces a file that opens with stdlib `sqlite3`, no extensions
- [ ] `snapshot_meta` records version, generated-at, license, coverage and row counts
- [ ] A fresh clone reaches its first query in under 5 minutes

**Key files / surfaces** — `scripts/make_snapshot.py`, `scripts/pull_db.py`,
`docs/data-dictionary.md`, `.github/workflows/snapshot.yml`

**Dependencies** — Epics 1.1–1.3

### Stories (4)

#### [STORY 1.5.1] Export a stamped snapshot — `size:M` `p1-high` `epic:distribution`

> **Parent epic:** [EPIC 1.5]

**User story**

> As a **data practitioner**, I want **the database to tell me what it is** so that **I can cite its version, date and license in my work**.

**Acceptance criteria**

- [ ] `make snapshot` writes `dist/arabfootball-YYYY-MM.db`
- [ ] `snapshot_meta` stamped: version, generated_at, license (ODbL), coverage, per-table counts
- [ ] Vacuumed/compact; no provider keys or internal-only rows included

#### [STORY 1.5.2] Snapshot round-trip test — `size:S` `p1-high` `epic:testing`

> **Parent epic:** [EPIC 1.5]

**User story**

> As an **app developer**, I want **the published file to behave exactly like the source database** so that **what I download is what was tested**.

**Acceptance criteria**

- [ ] A fresh process opens the exported file and reproduces resolution, form and H2H answers
- [ ] Opens with stdlib `sqlite3` only
- [ ] Test runs in CI with no network

#### [STORY 1.5.3] Quickstart & data dictionary — `size:S` `p2-medium` `epic:docs`

> **Parent epic:** [EPIC 1.5]

**User story**

> As an **app developer**, I want **to go from clone to first query in minutes** so that **evaluating this project costs me nothing**.

**Acceptance criteria**

- [ ] README quickstart verified on a clean clone
- [ ] `docs/data-dictionary.md` documents every table and column
- [ ] Attribution + takedown process stated

#### [STORY 1.5.4] Monthly publish workflow (stub) — `size:S` `p3-low` `epic:distribution`

> **Parent epic:** [EPIC 1.5]

**User story**

> As a **maintainer**, I want **the publishing path scaffolded now** so that **turning on monthly releases later is configuration, not a build**.

**Acceptance criteria**

- [ ] `.github/workflows/snapshot.yml` exists, manual-dispatch only
- [ ] Documents the box-side cron + export → release flow
- [ ] Does not publish anything until enabled in Initiative v0.3

---

# [INITIATIVE v0.2.0] All-time backfill *(next — scoped ahead)*

`type:initiative` · `theme:arab-football-data` · `initiative:v0.2-backfill`

Depth is the v1 headline. Only the epic that changes the Sprint-1 design is
detailed here; the rest is scoped when Sprint 1 closes with real numbers.

## [EPIC 2.1] Bulk open-dataset ingestion

`type:epic` · `epic:collectors` · `size:L` · `p1-high` · `initiative:v0.2-backfill`
**FRs:** FR-18, FR-6, FR-7, FR-9

> **Parent initiative:** [INITIATIVE v0.2.0] All-time backfill

## Epic

Years of history arrive in one download. A license-clean bulk dataset (Kaggle and
equivalents) backfills decades where paging a live API would take thousands of
calls — **international results since 1872, a ready-made appearance spine, and a
transfer archive**, all CC0 or ODbL. Bulk rows earn no shortcut: they pass through
the same resolver as live records.

**In scope**

- A bulk-dataset collector class (download → CSV → resolver → store)
- **License gating** — only CC0 / ODbL / CC-BY / CC-BY-SA are ingested; the
  dataset id, version and license are recorded with the rows
- Priority datasets (see `docs/sources.md`): international results (CC0),
  Transfermarkt mirror `player-scores` (CC0), Egyptian league 2015–25 (ODbL),
  global transfers 2010–26 (CC0)
- Conflict handling: a dump never silently overwrites a live-sourced result

**Out of scope**

- Datasets with unstated licenses (e.g. `rossi14/saudi-pro-league-transfers`) —
  private cross-checking only, never redistribution
- Scraping Transfermarkt directly while a CC0 mirror exists

**Epic acceptance criteria**

- [ ] A dataset without a recorded, redistributable license **cannot** be ingested
- [ ] Imported rows carry dataset id + version + license into the snapshot
- [ ] Every imported club/player resolves through the resolver, no direct id reuse
- [ ] Arab-league coverage of each dataset is measured and recorded before it's trusted

**Key files / surfaces**

- `arabfootball/collectors/bulk.py`, `arabfootball/collectors/kaggle.py`
- `docs/sources.md` (the license register)

**Dependencies** — Epics 1.1 (resolution), 1.2 (ingest pipeline)

### Stories (4)

#### [STORY 2.1.1] Bulk collector with a license gate — `size:M` `p1-high` `epic:collectors`

> **Parent epic:** [EPIC 2.1]

**User story**

> As a **maintainer**, I want **the pipeline to refuse any dataset I haven't license-cleared** so that **the published snapshot can never contain data I'm not allowed to redistribute**.

**Acceptance criteria**

- [ ] A dataset is declared in `sources.md` with id, version and license before use
- [ ] Ingest **aborts** on an unknown/NC license, with a clear error
- [ ] Imported rows record dataset id, version and license
- [ ] Kaggle candidates can be triaged via the unauthenticated API (`/api/v1/datasets/list?search=`)

#### [STORY 2.1.2] International results backfill (CC0) — `size:M` `p1-high` `epic:collectors`

> **Parent epic:** [EPIC 2.1]

**User story**

> As a **data practitioner**, I want **every Arab national team's match history back to its first international** so that **I can analyze Gulf Cup, Arab Cup and Asian Cup history no API exposes**.

**Acceptance criteria**

- [ ] `martj42/international-football-results-…` (CC0) imported
- [ ] Filtered to Arab national teams + their opponents; competitions resolved as entities
- [ ] Country names in the dump resolve to canonical national-team entities
- [ ] Provisional rate measured; duplicates against live-sourced matches deduped

#### [STORY 2.1.3] Appearance-spine backfill from the Transfermarkt mirror — `size:L` `p1-high` `epic:collectors`

> **Parent epic:** [EPIC 2.1]

**User story**

> As an **app developer**, I want **player careers and squads to exist from day one of the archive** so that **profiles are deep immediately instead of filling in slowly as new matches are played**.

**Acceptance criteria**

- [ ] `davidcariboo/player-scores` (CC0) imported: players, clubs, games, appearances
- [ ] **Arab-league coverage measured and reported first** — if it skews European, scope drops to Arab players' career stops abroad
- [ ] Appearances land in the existing `appearances` table so derivation is unchanged
- [ ] Transfermarkt ids stored as aliases, never as canonical ids

#### [STORY 2.1.4] Transfer archive + conflict policy — `size:M` `p2-medium` `epic:collectors`

> **Parent epic:** [EPIC 2.1]

**User story**

> As a **maintainer**, I want **a dump to flag disagreements instead of overwriting live data** so that **a stale CSV can't quietly rewrite a result I already verified**.

**Acceptance criteria**

- [ ] Global transfers dataset (CC0) imported into `transfers`
- [ ] On conflict with a live-sourced row, the live value wins and the conflict is recorded
- [ ] Duplicate transfers across datasets are deduped by (player, date, from, to)
- [ ] Egyptian league dataset (ODbL) imported with attribution preserved
