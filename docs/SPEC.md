# Arab Football Unified API — Design Spec

**v1.0 · decisions locked 2026-07-25**

Product requirements live in [`product/PRD.md`](./product/PRD.md); this document is
the *architecture* — how the engine is built and why it's built that way.

---

## 1. The gap

Arab and Gulf football is the worst-covered corner of world football in every
available data API. Concretely, from building against them:

- The Roshn Saudi League returned **zero fixtures** from one "supported" provider,
  and a squad of **English League One clubs** from another.
- `"Al Hilal"` resolved to a **South Sudanese** club; `"Al Ahli"` to a **Jordanian**
  one — a football pundit citing the wrong country's results.
- Head-to-head and recent form were missing or wrong.
- Deep history — careers, transfers, honours — effectively doesn't exist at usable
  depth for these leagues anywhere.

The cause isn't negligence by those providers: the data is fragmented across
**Arabic-language sources**, with inconsistent transliteration and rampant
namesakes, and nobody has done the normalization work.

That gap is the opportunity. Instead of duplicating well-covered European data, go
**narrow and deep**: own the Arab world completely — every club and player, all-time,
resolved across both scripts.

## 2. Shape

```
sources ──► collectors ──► ENTITY RESOLUTION ──► store ──► snapshot + read API
(365Scores,  (adapters,     (language-neutral      (all-time    (monthly SQLite
 ESPN,        fail-soft,     canonical ids;         archive;     on GitHub +
 API-Football, rate-budgeted) Arabic ↔ English)     appearances  a bundled
 bulk dumps,        │                               spine)       /v1 server)
 Arabic news)       │
                    ▼
            ENRICHMENT (LLM via the gateway):
            article ──► {transfer|injury|suspension, entities,
                         date, source, confidence}
```

Apps read the **store**, never the raw feeds — one cached database instead of six
live fan-outs per request.

## 3. Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| **Delivery** | MIT code + **monthly ODbL SQLite snapshot**, not a hosted API | Nobody depends on our uptime; a dataset outlives a service |
| **Coverage** | The **whole Arab world**, high resolution | Narrow and deep beats broad and shallow; this is the underserved region |
| **History** | **All-time**, built competition-by-competition | Depth is the differentiator; sequencing keeps it shippable |
| **Identity** | **Language-neutral canonical id**; `name_ar` + `name_en` always returned | Names are labels, never keys — the only way both scripts coexist |
| **Data licence** | **ODbL** (code MIT) | Share-alike keeps derivative databases open |
| **Cadence** | Monthly auto-export box → GitHub | Armchair reads the live store directly, so it's never stale |

## 4. Core 1 — Bilingual entity resolution

The moat. The same club is written a dozen ways across scripts (`الهلال` /
`Al-Hilal` / `Al Hilal` / `AlHilal SFC`), and namesakes abound — three different
"Al Ahli"s in three countries.

Each entity gets a **language-neutral id**. Resolution ladder, always scoped by
type + country:

1. **Provider id** — exact, authoritative
2. **Normalized name** — Arabic folding (diacritics, أ/إ/آ→ا, ة→ه, ال prefix) and
   Latin folding (accents, punctuation, stopwords, fused article, `y`→`i`)
3. **Cross-script skeleton** — Arabic omits short vowels, so transliterate and drop
   vowels from both: `الهلال` and `Al Hilal` both reduce to `hll`
4. **Bounded fuzzy** — bigram similarity, above a threshold *and* clear of the
   runner-up by a margin
5. **Provisional** — otherwise create a flagged entity for review

> **Never guess.** An unresolvable record becomes a review-queue entry, not a
> confident wrong match. Every id and spelling seen is learned as an alias, so the
> next pass resolves at step 1.

Implementation: [`arabfootball/resolve/`](../arabfootball/resolve/) ·
guarded by the adversarial suite in [`tests/test_resolver.py`](../tests/test_resolver.py).

## 5. Core 2 — Derive, don't fetch

Careers, squads and head-to-head are **computed from a stored spine of match
appearances**, never pulled from per-entity endpoints.

This isn't only a robustness preference — it's forced by reality. The endpoints that
would serve those directly are gated behind app-only parameters, and Kooora's own app
backend (`kapi.kooora.ws`) is **dead**, killed by the 365Scores merger. A thin wrapper
over one upstream dies with it; a store doesn't.

| Derived | From |
|---|---|
| Recent form | `matches` |
| Head-to-head | `matches` |
| Squad by season | `appearances` |
| Player career path | `appearances` + `transfers` |

## 6. Core 3 — Facts from news

Structured feeds don't carry "signed a striker" or "keeper out six weeks" — and for
Arab football most of that lives in **Arabic-language reporting**. Article text
(Arabic + English) goes through the LiteLLM gateway to extract *typed* facts, each
with resolved entities, a date, a source URL and a confidence score, deduplicated
across outlets.

Guardrails: a fact whose entities don't resolve is **dropped** (no invented clubs);
low confidence goes to review; every fact keeps its source link.

## 7. Sources and the licence tier model

Full register: [`sources.md`](./sources.md).

Because we republish an open database, each source's licence decides how its data may
be used — not merely whether we may read it:

| Tier | Licences | Role |
|---|---|---|
| **A — Publishable** | CC0 · ODbL · CC-BY · CC-BY-SA | Ingested **and exported** |
| **B — Reference** | Unstated / unknown | Ingested for discovery and cross-checking; **excluded from every export** until an independent source corroborates the fact |
| **C — Refused** | CC-BY-NC · explicit no-redistribution | Not ingested |

Tier B is legitimate because copyright protects a *compilation*, not the individual
facts inside it: a reference source may point us at what to verify; it may never be
copied wholesale into what we publish. Enforced by `transfers.tier` and tested in
[`tests/test_source_tiers.py`](../tests/test_source_tiers.py).

**Endpoint note.** The 365Scores web backend takes **plural** parameters
(`competitions=`, `competitors=`, `athletes=`); singular forms are silently ignored.
Saudi Pro League = competition **649**.

## 8. Store

Postgres on the producer, exported as a portable **SQLite** snapshot — one file, zero
setup, the thing a developer downloads. Schema:
[`arabfootball/store/schema.sql`](../arabfootball/store/schema.sql).

Everything carries provenance and a freshness stamp. Match state is **forward-only**:
a stale feed can never un-finish a game.

## 9. Distribution

Two artefacts ship:

- **The code** (MIT) — collectors, resolver, schema, and a bundled `/v1` read server
- **The data** (ODbL) — a monthly SQLite snapshot on GitHub, stamped in
  `snapshot_meta` with version, generation time, licence, coverage and row counts

```bash
git clone https://github.com/MHutatah/arab-football-unified-api
make pull-db && make serve      # or just open the .db
```

Two audiences: **Armchair Pundit** reads the continuously-updated store on the box, so
it's never a month stale; **everyone else** gets the monthly snapshot.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Cross-script skeleton over-collapses | Scoped by country+type, min length 3, never sole evidence; adversarial suite gates it |
| Fuzzy threshold wrong | Explicit threshold + margin-over-runner-up; provisional rate measured on a real ingest and tuned once |
| Unofficial endpoints change shape | Thin wrappers, `source_runs` health, fail soft |
| LLM hallucinates entities | Must resolve or drop; confidence gate; review queue |
| All-time × whole-Arab is a huge backfill | The largest cost by far — phased competition-by-competition, derived from the appearance spine, built in the background while live data ships |
| Redistribution of aggregated data | Publish facts not verbatim text; tier model; ODbL + attribution; takedown path |

## 11. Prior art

[`n-eq/kooora-unofficial-api`](https://github.com/n-eq/kooora-unofficial-api) reverse-
engineered Kooora's Android backend. Its entity-centric endpoints and fields
(`IsArchived`, `Year`, `Established`, `NationalNumber`) validate this schema — and its
**death** validates the architecture: it was a thin wrapper over one upstream, and when
that upstream was retired the project stopped working. Owning a stored, resolved copy
is the whole point.
