# Kooora API — Requirements Traceability Matrix

Links each requirement to the code that implements it and the tests that verify it.
Requirement ids come from [`product/PRD.md`](./product/PRD.md); sprint task ids
(**K-NN**) from [`sprint/`](./sprint/).

**Legend:** ✅ implemented + automated tests · 🟡 partially implemented · ⬜ not started (planned).

## Functional requirements

| Req | Requirement | Implementation | Verifying tests | Sprint | Status |
|---|---|---|---|---|:--:|
| FR-1 | Language-neutral canonical ids | `store/db.py::create_entity`, `schema.sql::entities` | `test_resolver.py` (all — every assertion compares ids, never names) | 1 · K-02/K-05 | ✅ |
| FR-2 | Carry + return `name_ar` and `name_en` | `schema.sql::entities`, `resolver.py::_create` | `test_same_club_across_providers_and_scripts_is_one_entity` | 1 · K-02 | ✅ |
| FR-3 | Resolution order: provider id → name → cross-script → fuzzy | `resolve/resolver.py::resolve`, `normalize.py::norm/xkey/similarity` | `test_provider_id_is_authoritative`, `test_learned_aliases_make_the_next_pass_exact`, `test_arabic_variants_normalize_together`, `test_latin_variants_normalize_together`, `test_similarity_tolerates_transliteration_noise` | 1 · K-03/K-04 | ✅ |
| FR-4 | Never guess — provisional + review queue | `resolver.py::_create`, `store/db.py::review_queue` | `test_unmatched_becomes_provisional_not_a_guess`, `test_wrong_country_namesake_never_matches`, `test_al_ahli_namesakes_stay_separate` | 1 · K-04 | ✅ |
| FR-5 | Learn every provider id and spelling | `resolver.py::_learn`, `schema.sql::aliases` | `test_learned_aliases_make_the_next_pass_exact` | 1 · K-04 | ✅ |
| FR-6 | All-time match archive with provenance | `schema.sql::matches` | _(ingest tests — K-09)_ | 1–2 · K-09 | 🟡 schema only |
| FR-7 | Appearance spine (player × match × team) | `schema.sql::appearances` | _(lineup tests — K-10)_ | 1 · K-10 | 🟡 schema only |
| FR-8 | Derive form / H2H / squad / career from the store | `derive/` _(planned)_ | _(K-12…K-14)_ | 1 · K-12–K-14 | ⬜ |
| FR-9 | Season records, honours, transfers | `schema.sql::team_seasons/honours/transfers` | _(backfill tests — Sprint 2)_ | 2 | 🟡 schema only |
| FR-10 | Forward-only match state | `collectors/ingest.py` _(planned)_ | _(K-09)_ | 1 · K-09 | ⬜ |
| FR-11 | Multi-source collectors, any may be absent/failing | `collectors/` _(planned)_ | _(K-07, canned payloads)_ | 1 · K-07/K-08 | ⬜ |
| FR-12 | Record every collector run | `schema.sql::source_runs` | _(K-07)_ | 1 · K-07 | 🟡 schema only |
| FR-13 | LLM typed-fact extraction (ar + en) | `enrich/` _(planned)_ | _(Sprint 4)_ | 4 | ⬜ |
| FR-14 | Drop facts whose entities don't resolve | `enrich/` _(planned)_ | _(Sprint 4)_ | 4 | ⬜ |
| FR-15 | Monthly stamped SQLite snapshot | `schema.sql::snapshot_meta`, `scripts/make_snapshot.py` _(planned)_ | _(K-17, K-18 round-trip)_ | 1 · K-17/K-18 | 🟡 schema only |
| FR-16 | Bundled bilingual read API `/v1` | `api/` _(planned)_ | _(K-15, K-16)_ | 1 · K-15/K-16 | ⬜ |
| FR-17 | MIT code · ODbL data · attribution · takedown | `LICENSE`, `LICENSE-DATA`, `README.md` | _(manual review)_ | 1 · K-01 | ✅ |

> **Sprint 1 gate:** FR-1…FR-5 must be ✅ before any depth work starts. A wrong
> entity id silently corrupts every derived fact built on top of it.

## Non-functional requirements

| Req | Requirement | Target | Verification | Status |
|---|---|---|---|:--:|
| NFR-identity | Namesake collisions in a published snapshot | **0** | Adversarial suite (`test_resolver.py`) + review queue audit | ✅ suite green |
| NFR-provisional | Provisional entities after a full-league ingest | < 5 % | Measured on the Saudi ingest (K-08/K-09) | ⬜ |
| NFR-offline | Test suite makes zero network calls | always | CI (`ci.yml`); collectors use canned payloads | ✅ |
| NFR-failsoft | Any single source down ⇒ pipeline still completes | always | Collector contract tests (K-07) | ⬜ |
| NFR-portable | Snapshot opens with stdlib `sqlite3`, no extensions | always | Round-trip test (K-18) | ⬜ |
| NFR-onboard | Clone → first query | < 5 min | Fresh-clone walkthrough (K-20) | ⬜ |

## Pain-point → requirement rollup

| Pain point (PRD §4) | Requirements |
|---|---|
| Five spellings across two scripts | FR-1, FR-2, FR-3, FR-5 |
| Wrong-country namesakes | FR-3, FR-4 |
| No usable Arab football history | FR-6, FR-9 |
| Careers / H2H not exposed by feeds | FR-7, FR-8 |
| One provider goes stale and breaks the app | FR-10, FR-11, FR-12 |
| Transfers and injuries only in Arabic news | FR-13, FR-14 |
| Don't want to depend on someone's uptime | FR-15, FR-16, FR-17 |
