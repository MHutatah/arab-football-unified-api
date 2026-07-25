# Kooora API — Sprint 1: Foundation (Phase 1)

**Sprint:** 01 · **Two weeks** · Drafted Jul 25, 2026
**Requirements:** `docs/product/PRD.md` (FR-1…FR-17) · **Roadmap:** `docs/product/ROADMAP.md`
**Traceability:** `docs/requirements-traceability.md` (FR → code → tests)
**Branch model:** every item ships on its own branch → PR → CI green → merge to `main`
**Repo:** `MHutatah/kooora-api` — public, MIT code / ODbL data

---

## 1. Sprint Goal & Acceptance Criteria

### Sprint Goal
> Stand up the **entity spine** — the language-neutral canonical registry and the
> resolver — and prove it against the exact failures that motivated this project.
> Land one real collector end-to-end (365Scores → Saudi Pro League) so the pipeline
> is demonstrably real, not scaffolding. **No armchair changes this sprint.**
> Depth, breadth and enrichment come later; if identity is wrong, everything built
> on top is wrong, so identity ships first and ships correct.

### Acceptance Criteria
A clean clone, following the README, must do all of this:

1. **Install & test** — `pip install -e ".[dev]" && pytest -q` passes, zero network calls in tests.
2. **Schema applies** — `make init-db` creates every table from `schema.sql` in SQLite.
3. **Cross-script identity** — `الهلال`, `Al-Hilal`, `Al Hilal`, `AlHilal SFC` and 365Scores id `5457` all resolve to **one** entity id.
4. **Namesakes stay separate** — Saudi vs Sudanese "Al Hilal"; Saudi vs Jordanian vs Egyptian "Al Ahli" → distinct entities, never merged.
5. **No silent guessing** — an unresolvable name creates a **provisional** entity that appears in the review queue; it is never matched to a wrong club.
6. **Real ingest** — `make collect-saudi` pulls the current Roshn Saudi League season from 365Scores, resolves every club, and writes `matches` rows.
7. **Appearances land** — game lineups produce `appearances` rows (the spine careers/squads/H2H will be derived from).
8. **Derivation works** — `form(team, n)` and `h2h(team_a, team_b)` return correct results computed *from the store*, with no live network call.
9. **Snapshot round-trips** — `make snapshot` exports a SQLite file; a fresh process opens it and answers 3, 4, 8 identically.
10. **Provenance is visible** — every collector run writes a `source_runs` row; `snapshot_meta` stamps version, generated-at, license and row counts.

**Hard gate:** items 3–5 (identity correctness) are non-negotiable. The sprint
does not close with a known namesake collision.

---

## 2. Epics mapped to SDLC roles

| Role | Epic ownership |
|---|---|
| **Product Owner** (you) | Scope calls, competition priority order, license/attribution wording, sprint sign-off |
| **Tech Lead** | Schema + resolver contract, derivation semantics, CI, PR review, snapshot format |
| **Data Eng** | Collector framework, 365Scores adapter, backfill runner, `source_runs` observability |
| **Identity Eng** | Normalization (Arabic/Latin/cross-script), matching thresholds, review queue, alias learning |
| **API Eng** | Read API skeleton, `/v1` contract, bilingual response shape, `?lang=` |
| **QA** | Fixture corpus of real Arab club names, adversarial namesake suite, snapshot round-trip, no-network guarantee |

---

## 3. Prioritized, sequenced backlog

Sizes: S ≈ ≤½ day, M ≈ 1 day, L ≈ 1.5–2 days. Sequencing respects dependencies (→).

### Wave 0 — The spine (days 1–4) — BLOCKS EVERYTHING
| # | Item | FRs | Owner | Size | Status |
|---|---|---|---|---|---|
| K-01 | Repo scaffold: package layout, `pyproject`, MIT + ODbL, CI, Makefile | FR-17 | Tech Lead | S | ✅ done |
| K-02 | `schema.sql` — entities, aliases, matches, appearances, team_seasons, transfers, honours, facts, source_runs, snapshot_meta | FR-1, FR-2, FR-6, FR-7, FR-9 | Tech Lead | M | ✅ done |
| K-03 | `normalize.py` — Arabic folding, Latin transliteration, fused-article strip, `xkey()` cross-script skeleton | FR-3 | Identity | M | ✅ done |
| K-04 | `resolver.py` — provider-id → name → cross-script → fuzzy → provisional; alias learning | FR-3, FR-4, FR-5 | Identity | L | ✅ done |
| K-05 | `store/db.py` — SQLite store implementing the resolver interface + review queue | FR-1, FR-4 | Tech Lead | M | ✅ done |
| K-06 | Adversarial identity suite (namesakes, scripts, provisional) | FR-3, FR-4 | QA | M | ✅ 9 passing |

**Exit gate (day 4):** acceptance items 1–5 pass; **FR-1…FR-5 ✅ in the traceability matrix**; CI green on `main`.

### Wave 1 — First real collector (days 4–7)
| # | Item | FRs | Owner | Size |
|---|---|---|---|---|
| K-07 | Collector base: interface, per-source rate budget, `source_runs` writes, graceful-empty contract | FR-11, FR-12 | Data Eng | M |
| K-08 | 365Scores adapter — fixtures/results via `competitions=` + date window (Saudi id **649**) | FR-11 | Data Eng | M |
| K-09 | Ingest pipeline: raw record → resolver → `matches` upsert (forward-only status) | FR-6, FR-10 | Data Eng + Tech Lead | M |
| K-10 | Lineups → `appearances` rows (`/web/game/?gameId=&withLineups=true`, `members[]`) | FR-7 | Data Eng | M |
| K-11 | Competition + season seeding for the Saudi league (entities for clubs from `/standings`) | FR-1, FR-2 | Identity | S |

### Wave 2 — Derivation + read surface (days 7–10)
| # | Item | FRs | Owner | Size |
|---|---|---|---|---|
| K-12 | `derive.form(team, n)` — last-N results computed from `matches` | FR-8 | Tech Lead | S |
| K-13 | `derive.h2h(a, b)` — past meetings + W/D/L record from `matches` | FR-8 | Tech Lead | S |
| K-14 | `derive.squad(team, season)` + `derive.career(player)` from `appearances` | FR-8 | Tech Lead | M |
| K-15 | Read API skeleton (FastAPI): `/v1/search`, `/v1/teams/{id}`, `/v1/matches`, `/v1/h2h` | FR-16 | API Eng | L |
| K-16 | Bilingual response shape + `?lang=ar\|en` display selection | FR-2, FR-16 | API Eng | S |

### Wave 3 — Snapshot + hardening (days 10–12)
| # | Item | FRs | Owner | Size |
|---|---|---|---|---|
| K-17 | `make snapshot` — export SQLite, stamp `snapshot_meta` (version, generated_at, license, counts) | FR-15 | Data Eng | M |
| K-18 | Snapshot round-trip test — fresh process, identical answers | FR-15 | QA | S |
| K-19 | Review-queue CLI: list provisional entities, merge into canonical, record the alias | FR-4, FR-5 | Identity | M |
| K-20 | README quickstart verified on a clean clone; `docs/data-dictionary.md` | FR-17 | PO + Tech Lead | S |
| K-21 | Ops: cron layout + monthly snapshot workflow **stub** (wired for real in Sprint 3) | FR-15 | Data Eng | S |

### Sequencing summary
`K-01→K-02→{K-03,K-05}→K-04→K-06` **[gate]** →
`K-07→{K-08,K-11}→K-09→K-10` → `{K-12,K-13,K-14}→K-15→K-16` →
`K-17→K-18` ∥ `K-19,K-20,K-21` → **sign-off**

---

## 4. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cross-script matching over-collapses (skeleton too lossy) | **High** | **Critical** | Skeleton only inside a country+type scope, min length 3, never sole evidence; adversarial suite is the gate; thresholds tunable in one place |
| Fuzzy threshold wrong → wrong merges or provisional flood | High | High | Explicit `FUZZY_THRESHOLD`/`FUZZY_MARGIN` constants + margin-over-runner-up rule; measure provisional rate on the real Saudi ingest and tune once |
| 365Scores unofficial endpoint changes shape | Med | High | Thin adapter, graceful-empty contract, `source_runs` health; the store already holds what was ingested |
| Arab club naming edge cases we haven't met (Maghreb French spellings) | Med | Med | Saudi-first this sprint; grow the QA fixture corpus per country before expanding |
| Scope creep into backfill/enrichment | **High** | Med | All-time backfill is Sprint 2, news extraction Sprint 4 — out of scope here by definition |
| Snapshot size grows past comfortable Git limits | Low | Med | Measure at Sprint 1 scale (one league); compression + per-competition split decided in Sprint 3 |
| Provider ToS / redistribution concerns | Med | High | Publish facts not verbatim text; ODbL + attribution; takedown path in README |

---

## 5. Definition of Done (per item)

1. Code on a **feature branch**, never direct to `main`.
2. Acceptance criteria for the item met.
3. **Tests written and passing**; new behavior has a regression test.
4. **No live network in the test suite** — collectors tested against canned payloads.
5. Bilingual data paths exercised with **real Arabic strings**, not placeholders.
6. **Traceability updated** — the item's FRs move to 🟡/✅ in
   `docs/requirements-traceability.md`, citing the implementing symbol and its tests.
7. **PR opened** referencing the item (`Closes K-NN`), reviewed by Tech Lead.
8. **CI green** on the PR (the merge gate).
9. Merged to `main`; branch deleted.
10. Anything touching identity additionally passes the full adversarial namesake suite.

**Sprint-level DoD:** acceptance 1–10 verified on a **fresh clone**; `main` CI green;
**FR-1…FR-5 ✅ and every other in-sprint FR at least 🟡** in the traceability matrix;
provisional rate on the Saudi ingest measured and recorded; Sprint 2 (all-time
backfill) scoped with the real numbers this sprint produced.

---

## 6. Out of scope (named, so it stays out)

All-time backfill · other Arab countries · news/LLM enrichment · odds · transfers
sources · the public monthly snapshot automation · armchair migration · any hosted
service. Each has its own later sprint.
