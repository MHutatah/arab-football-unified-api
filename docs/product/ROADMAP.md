# Arab Football Unified API — Roadmap & Scope Map

Phased delivery of the PRD. Requirement ids (**FR-N**) come from [`PRD.md`](./PRD.md);
sprint task ids (**K-NN**) from [`../sprint/`](../sprint/).

---

## Phase 1 — Foundation (Sprint 1, 2 weeks) · **in progress**

The entity spine plus one real collector, proving the pipeline end to end.

| Delivers | FRs | Sprint items |
|---|---|---|
| Language-neutral registry + bilingual resolver | FR-1…FR-5 | K-02…K-06 ✅ |
| Collector framework + 365Scores adapter (Saudi) | FR-11, FR-12 | K-07, K-08, K-11 |
| Match archive + appearance spine | FR-6, FR-7, FR-10 | K-09, K-10 |
| Derivation (form, H2H, squad, career) | FR-8 | K-12…K-14 |
| Read API skeleton, bilingual | FR-16 | K-15, K-16 |
| Snapshot round-trip | FR-15 | K-17, K-18 |

**Exit:** identity is provably correct (0 namesake collisions), one league ingested,
everything derivable offline from the store.

## Phase 2 — All-time backfill (Sprint 2) · **the v1 headline**

Depth, competition by competition — Saudi and the Gulf first, then outward.
**Bulk open datasets come first**: a license-clean dump delivers years of history in
one download, where paging an API for the same span takes thousands of calls.

- **Bulk dataset ingestion** — CC0/ODbL Kaggle dumps for international results,
  appearances and transfers (FR-18); license gate enforced (`docs/sources.md`)
- Historical seasons via 365Scores + API-Football history (FR-6, FR-9)
- `team_seasons`, `honours`, `transfers` populated (FR-9)
- Careers and squads derived across the full archive (FR-8)
- Wikipedia (ar/en) archival collector, LLM-normalized (FR-11)

**Exit:** a club profile matches or beats kooora.com depth for the seeded countries.

## Phase 3 — Breadth & publishing (Sprint 3)

- Remaining Arab-world competitions (Levant, Egypt, Maghreb)
- **Monthly snapshot automation**: box → export → GitHub Releases (FR-15, FR-17)
- Size management: compression, per-competition split if needed
- Public data dictionary + attribution/takedown process

**Exit:** the first public snapshot is downloadable and a stranger can use it.

## Phase 4 — Enrichment (Sprint 4)

- Arabic + English news collectors (FR-11)
- LLM typed-fact extraction via the LiteLLM gateway (FR-13, FR-14)
- Confidence gating, cross-outlet dedup, review queue for low confidence

**Exit:** transfers/injuries appear as first-class facts with provenance.

## Phase 5 — Consumers (Sprint 5)

- Armchair Pundit migrates off its embedded `app/truth/` layer onto the read API
- Public quickstart docs; first external-developer pass
- The engine becomes shared infrastructure for later projects

---

## Scope map — what's real vs. deferred

| Area | v1 (phases 1–4) | Deferred |
|---|---|---|
| Geography | Whole Arab world | Non-Arab leagues as primary data |
| History | All-time, derived | Pre-modern eras where no source exists |
| Entities | Clubs, players, competitions, venues, managers | Referees, agents, contracts |
| Live | Fixtures, results, form, H2H, odds | Minute-by-minute event streams |
| Enrichment | Transfers, injuries, suspensions from news | Sentiment, tactical analysis |
| Delivery | MIT code + monthly ODbL snapshot | Hosted SaaS API, SLA, auth |
| Sports | Football | Everything else |
