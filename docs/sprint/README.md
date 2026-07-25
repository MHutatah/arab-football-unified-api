# Sprint plans

The build sequence for Kooora API — the execution layer of the product docs.

| Layer | Document |
|---|---|
| **Why & what** — problem, personas, pain→feature, **FR-1…FR-17** | [`../product/PRD.md`](../product/PRD.md) |
| **When** — phased scope map, FRs per phase | [`../product/ROADMAP.md`](../product/ROADMAP.md) |
| **Proof** — FR → implementation → tests → status | [`../requirements-traceability.md`](../requirements-traceability.md) |
| **How** — sprint goal, waved backlog, risks, DoD | this directory |
| **Design** — architecture decisions | [`../SPEC.md`](../SPEC.md) |

Every sprint item carries the FRs it satisfies, and closing an item updates the
traceability matrix — so requirements never drift from the code.

| Sprint | Theme | Ships | Plan |
|---|---|---|---|
| **01** | **Foundation** | Entity spine (language-neutral registry + bilingual resolver), first real collector (Saudi/365Scores), derivation, read-API skeleton, snapshot round-trip | [sprint-01-foundation.md](sprint-01-foundation.md) |
| 02 | All-time backfill | Historical seasons competition-by-competition, `team_seasons`, honours, careers derived from the appearance spine; the depth that defines v1 | _tbd_ |
| 03 | Breadth + publish | Remaining Arab countries; monthly snapshot automation box → GitHub Releases; per-competition split if size demands | _tbd_ |
| 04 | Enrichment | Arabic + English news → LLM typed facts (transfers, injuries, suspensions) via the LiteLLM gateway, with provenance + confidence | _tbd_ |
| 05 | Consumers | Armchair Pundit migrates off its embedded `app/truth/` layer onto the snapshot/read API; public docs + first external-dev pass | _tbd_ |

## Principles carried across every sprint

1. **Identity before depth.** A wrong entity id poisons everything downstream, so
   resolution correctness gates each sprint.
2. **Derive, don't fetch.** Careers, squads and H2H come from the stored
   appearance spine — never from a gated or fragile per-entity endpoint.
3. **Never guess silently.** An unresolvable record becomes a provisional entity
   in the review queue, not a confident wrong match.
4. **No live network in tests.** Collectors are tested against canned payloads.
5. **Free-first, fail-soft.** Any single source can be down or dropped without
   taking the engine with it.
6. **Publish facts, attribute sources.** MIT code, ODbL data, takedown path.
