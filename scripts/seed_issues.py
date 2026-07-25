"""Create the GitHub label taxonomy + the Theme/Initiative/Epic/Story issues.

The backlog in `docs/product/BACKLOG.md` is the source; this turns it into issues
with the same hierarchy nolog uses (Atlassian model: theme → initiative → epic →
story), wiring each child's parent reference once the parent's number is known.

    python scripts/seed_issues.py --dry-run     # print what would be created
    python scripts/seed_issues.py               # create for real (needs `gh auth`)

Idempotent-ish: it skips any issue whose exact title already exists.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

# Titles and bodies carry Arabic and arrows; a cp1252 console would crash on them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_LABELS = [
    ("type:theme", "6f42c1", "A long-running strategic area"),
    ("type:initiative", "8250df", "A collection of epics driving one release goal"),
    ("type:epic", "0969da", "A large body of work broken into stories"),
    ("type:story", "1f883d", "One user-visible increment"),
    ("theme:arab-football-data", "5a32a3", ""),
    ("initiative:v0.1-foundation", "8250df", ""),
    ("epic:identity", "0969da", "Entity resolution & the canonical registry"),
    ("epic:collectors", "0969da", "Source adapters & ingestion"),
    ("epic:derivation", "0969da", "Derived form, H2H, squads, careers"),
    ("epic:api", "0969da", "The bundled read API"),
    ("epic:distribution", "0969da", "Snapshots & publishing"),
    ("epic:testing", "bf8700", ""),
    ("epic:docs", "bf8700", ""),
    ("size:S", "d4c5f9", "<= half a day"),
    ("size:M", "d4c5f9", "~1 day"),
    ("size:L", "d4c5f9", "1.5-2 days"),
    ("p1-high", "d73a4a", ""),
    ("p2-medium", "fbca04", ""),
    ("p3-low", "0e8a16", ""),
]


def gh(*args: str, check: bool = True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{r.stderr.strip()}")
    return (r.stdout or "").strip()


def existing_titles() -> dict[str, int]:
    out = gh("issue", "list", "--limit", "500", "--state", "all",
             "--json", "number,title", check=False)
    try:
        return {i["title"]: i["number"] for i in json.loads(out or "[]")}
    except json.JSONDecodeError:
        return {}


def ensure_labels(dry: bool) -> None:
    for name, color, desc in REPO_LABELS:
        if dry:
            print(f"  label: {name}")
            continue
        gh("label", "create", name, "--color", color, "--description", desc,
           "--force", check=False)


# ── the backlog tree ────────────────────────────────────────────────────────
# Bodies are intentionally terse here: BACKLOG.md holds the full text, and each
# issue links back to it rather than duplicating it wholesale.
THEME = {
    "title": "[THEME] Arab-football data infrastructure",
    "labels": ["type:theme", "theme:arab-football-data"],
    "body": """## Theme

Own the data layer for Arab and Gulf football — the region every commercial API
covers worst — and publish it openly so any developer can build on it without
rebuilding the ingestion.

**Initiatives**

- v0.1.0 Foundation — entity spine + first collector
- v0.2.0 All-time backfill
- v0.3.0 Breadth & monthly publishing
- v0.4.0 News enrichment

Full backlog: `docs/product/BACKLOG.md`
""",
}

INITIATIVE = {
    "title": "[INITIATIVE v0.1.0] Foundation — entity spine + first collector",
    "labels": ["type:initiative", "theme:arab-football-data",
               "initiative:v0.1-foundation", "p1-high"],
    "body": """## Initiative — v0.1.0

**Goal.** Stand up the language-neutral entity registry and the bilingual
resolver, prove them against the failures that motivated the project, and land one
real collector end-to-end (Saudi Pro League via 365Scores). **If identity is
wrong, everything built on top is wrong** — so identity ships first and correct.

**Target release.** `v0.1.0`

**Outcomes / definition of done**

- [ ] الهلال / Al-Hilal / Al Hilal / AlHilal SFC / 365Scores `5457` → one entity
- [ ] Saudi vs Sudanese "Al Hilal", and three "Al Ahli"s, stay separate
- [ ] Unresolvable input becomes a provisional entity, never a wrong match
- [ ] A full Roshn Saudi League season ingested, resolved and stored
- [ ] Form, H2H, squad, career derived from the store with zero network calls
- [ ] A stamped SQLite snapshot round-trips in a fresh process
- [ ] FR-1…FR-5 ✅ in `docs/requirements-traceability.md`

**Dependencies**

- 365Scores web backend (plural params; Saudi competition id 649)
- No armchair changes in this initiative

_An initiative is a collection of epics driving toward one goal (Atlassian model)._
""",
}

EPICS = [
    {
        "key": "E1.1",
        "title": "[EPIC 1.1] Canonical entity registry & bilingual resolution",
        "labels": ["type:epic", "epic:identity", "size:L", "p1-high",
                   "initiative:v0.1-foundation"],
        "body": """## Epic

Give every club, player and competition a **language-neutral canonical id**, and
resolve any incoming record — any provider, any script, any spelling — onto it.
Every commercial API fails here for Arab football, and every derived fact inherits
the error.

**FRs:** FR-1 … FR-5 · **Status:** delivered in the scaffold

**In scope**
- Portable `entities` / `aliases` schema (Postgres + SQLite)
- Arabic + Latin normalization, cross-script matching, bounded fuzzy
- Resolution ladder with a provisional/review outcome instead of guessing
- Alias learning

**Out of scope**
- Manual curation UI (CLI review is enough for v0.1)
- Player disambiguation beyond name+country (needs squad context — Epic 1.3)

**Epic acceptance criteria**
- [x] One club across 3 providers and 2 scripts resolves to a single id
- [x] Wrong-country namesakes never merge
- [x] Unresolvable input creates a provisional entity, surfaced for review
- [x] Every provider id and spelling seen is learned as an alias

**Key files / surfaces**
- `kooora/store/schema.sql`, `kooora/resolve/normalize.py`,
  `kooora/resolve/resolver.py`, `kooora/store/db.py`

**Dependencies** — none (root of the build)

_An epic is a large body of work broken into stories._
""",
        "stories": [
            ("[STORY 1.1.1] Portable bilingual schema",
             ["size:M", "p1-high", "epic:identity"],
             "As a **maintainer**, I want **one schema that runs in both Postgres and SQLite** so that **the database I build is the database I publish**.",
             ["`entities` carries a language-neutral id, `name_ar`, `name_en`, country, meta, provisional",
              "`aliases` maps (provider, provider_id, name_variant) → entity, uniquely",
              "Archive tables exist: `matches`, `appearances`, `team_seasons`, `transfers`, `honours`",
              "`source_runs` + `snapshot_meta` exist for provenance",
              "No vendor-specific types; applies cleanly via `Store()`"], True),
            ("[STORY 1.1.2] Arabic + Latin name normalization",
             ["size:M", "p1-high", "epic:identity"],
             "As a **maintainer**, I want **every spelling of a club to reduce to one comparable key** so that **the same team from two sources isn't stored twice**.",
             ["Arabic: diacritics stripped, letter variants folded, ال prefix removed",
              "Latin: accents stripped, punctuation dropped, stopwords removed",
              "Fused article handled: `AlHilal` → `hilal`",
              "Transliteration variance folded: `Ahly`/`Ahli`, `Faysaly`/`Faisaly`",
              "`xkey()` cross-script skeleton so الهلال and Al Hilal meet"], True),
            ("[STORY 1.1.3] Resolution ladder that refuses to guess",
             ["size:L", "p1-high", "epic:identity"],
             "As an **app developer**, I want **the dataset to never contain a wrong-country club** so that **my app doesn't cite a Sudanese team's results for a Saudi match**.",
             ["Order: provider id → normalized name in scope → cross-script → bounded fuzzy",
              "Fuzzy requires a threshold **and** a margin over the runner-up",
              "Ambiguity or no match ⇒ provisional entity, never a confident wrong match",
              "All matching scoped by type + country"], True),
            ("[STORY 1.1.4] SQLite store & review queue",
             ["size:M", "p1-high", "epic:identity"],
             "As a **maintainer**, I want **provisional entities collected in one place** so that **I can adjudicate what the resolver couldn't**.",
             ["Store implements the resolver interface",
              "`review_queue()` lists provisional entities oldest-first",
              "Cross-script lookup guarded by a minimum skeleton length"], True),
            ("[STORY 1.1.5] Adversarial identity suite",
             ["size:M", "p1-high", "epic:testing"],
             "As a **maintainer**, I want **the known failure modes encoded as tests** so that **a regression in matching can never reach a published snapshot**.",
             ["Saudi vs Sudanese \"Al Hilal\" assert distinct",
              "Three \"Al Ahli\"s (SA/JO/EG) assert distinct",
              "One club across providers + scripts asserts identical",
              "Provisional path and alias learning asserted",
              "Suite makes zero network calls"], True),
            ("[STORY 1.1.6] Review-queue CLI",
             ["size:M", "p2-medium", "epic:identity"],
             "As a **maintainer**, I want **to merge a provisional entity into the right canonical one from the CLI** so that **corrections are a one-liner and are remembered forever**.",
             ["`make review` lists provisional entities with aliases and source",
              "A merge command repoints aliases and deletes the provisional",
              "The merged spelling is recorded as an alias for exact future resolution",
              "Merging is idempotent and logged"], False),
        ],
    },
    {
        "key": "E1.2",
        "title": "[EPIC 1.2] Collector framework & Saudi ingestion",
        "labels": ["type:epic", "epic:collectors", "size:L", "p1-high",
                   "initiative:v0.1-foundation"],
        "body": """## Epic

One interface every source implements, and the first real source behind it: the
365Scores web backend for the Roshn Saudi League. Any collector may be keyless,
absent or failing without stopping the pipeline — the store is the truth, not any
upstream.

**FRs:** FR-6, FR-10, FR-11, FR-12

**In scope**
- Collector interface, per-source rate budget, graceful-empty contract
- `source_runs` observability
- 365Scores adapter (competition 649)
- Ingest: raw → resolver → `matches`, forward-only status
- Seeding Saudi competition + club entities from standings

**Out of scope**
- Other countries (v0.3), historical seasons (v0.2), news (v0.4)
- Keyed providers — the free path must work alone first

**Epic acceptance criteria**
- [ ] `make collect-saudi` ingests the current season with every club resolved
- [ ] A failing source produces a `source_runs` row and an empty result, not an exception
- [ ] Re-running is idempotent — no duplicate matches
- [ ] A finished match is never reverted by a stale feed

**Key files / surfaces**
- `kooora/collectors/{base,scores365,ingest,run}.py`

**Dependencies** — Epic 1.1

_An epic is a large body of work broken into stories._
""",
        "stories": [
            ("[STORY 1.2.1] Collector base & run observability",
             ["size:M", "p1-high", "epic:collectors"],
             "As a **maintainer**, I want **every collector to report what it did and fail soft** so that **one dead source never takes the pipeline down or hides a problem**.",
             ["A `Collector` interface with a graceful-empty contract (returns `[]`, never raises)",
              "Every run writes a `source_runs` row with counts and errors",
              "A per-source rate budget is enforced",
              "Tested with a deliberately failing source"], False),
            ("[STORY 1.2.2] 365Scores fixtures adapter",
             ["size:M", "p1-high", "epic:collectors"],
             "As **Armchair Pundit**, I want **Saudi fixtures and results from a source that actually has them** so that **the lobby isn't empty for the league my users care about most**.",
             ["Fetches via `/web/games/?competitions=649&startDate&endDate` (plural param)",
              "Maps to normalized records: teams, kickoff UTC, status, score, provider ids",
              "Date-window paging over a season",
              "Tested against a canned payload — no live network in CI"], False),
            ("[STORY 1.2.3] Ingest pipeline with forward-only state",
             ["size:M", "p1-high", "epic:collectors"],
             "As an **app developer**, I want **a stale feed to never un-finish a match** so that **a result I already saw doesn't disappear from the data**.",
             ["Each raw record resolves both clubs before insert",
              "Upsert by provider id, else (teams, kickoff date)",
              "Status only moves scheduled → live → finished",
              "A recorded score survives a resync that reports none",
              "Re-ingesting the same payload inserts nothing new"], False),
            ("[STORY 1.2.4] Seed Saudi competition & clubs",
             ["size:S", "p1-high", "epic:identity"],
             "As a **maintainer**, I want **the league's clubs seeded from standings before fixtures load** so that **ingestion resolves against real entities instead of creating provisionals**.",
             ["Competition entity created with both names",
              "All 18 clubs seeded from `/web/standings/?competitions=649` with ids as aliases",
              "Provisional rate on the subsequent fixture ingest measured and recorded"], False),
        ],
    },
    {
        "key": "E1.3",
        "title": "[EPIC 1.3] Appearance spine & derivation",
        "labels": ["type:epic", "epic:derivation", "size:L", "p1-high",
                   "initiative:v0.1-foundation"],
        "body": """## Epic

The project's defining technical bet: **derive, don't fetch**. Careers, squads and
head-to-head are computed from a stored spine of match appearances rather than
pulled from per-entity endpoints that are gated, fragile or dead. Feeds die; a
store doesn't.

**FRs:** FR-7, FR-8

**In scope**
- Harvest lineups into `appearances` (player × match × team)
- Derive recent form and head-to-head from `matches`
- Derive squad-by-season and career path from `appearances`

**Out of scope**
- All-time depth (v0.2) — correctness of the derivation is what ships here
- Per-90 / advanced stats

**Epic acceptance criteria**
- [ ] Every derivation runs offline against the store, zero network calls
- [ ] H2H for two clubs matches hand-checked real results
- [ ] A player's career path is assembled purely from appearances + transfers

**Key files / surfaces**
- `kooora/collectors/lineups.py`, `kooora/derive/{form,h2h,squad,career}.py`

**Dependencies** — Epic 1.2

_An epic is a large body of work broken into stories._
""",
        "stories": [
            ("[STORY 1.3.1] Lineups → appearances",
             ["size:M", "p1-high", "epic:collectors"],
             "As a **data practitioner**, I want **every player's participation stored per match** so that **I can compute careers and squads myself without any API**.",
             ["Reads `/web/game/?gameId=&withLineups=true` and parses `members[]`",
              "Each player resolves to a canonical entity scoped by club, not globally",
              "Writes `appearances` with team, minutes, goals, cards where available",
              "Idempotent per (player, match)"], False),
            ("[STORY 1.3.2] Derive recent form",
             ["size:S", "p1-high", "epic:derivation"],
             "As **Armchair Pundit**, I want **a club's last-N results from the store** so that **the Pundit's opening odds are grounded in real form and never in a wrong club's record**.",
             ["`form(team, n)` returns the last N finished matches, most recent first",
              "Points (W=3, D=1) and W/D/L computed correctly from either side",
              "Zero network calls; empty (never raises) when there's no history"], False),
            ("[STORY 1.3.3] Derive head-to-head",
             ["size:S", "p1-high", "epic:derivation"],
             "As an **app developer**, I want **the meeting history between any two clubs** so that **I get the H2H no free API exposes**.",
             ["`h2h(a, b)` returns past meetings, most recent first, with a W/D/L summary",
              "Correct regardless of which club was home",
              "Empty result when they've never met — not an error"], False),
            ("[STORY 1.3.4] Derive squads & career paths",
             ["size:M", "p1-high", "epic:derivation"],
             "As a **data practitioner**, I want **a player's full career assembled from appearances** so that **I have the club-by-club history no Arab-football API provides**.",
             ["`squad(team, season)` lists players with appearance counts",
              "`career(player)` returns ordered stints (club, first/last appearance, apps, goals)",
              "Stints derive from appearance runs, reconciled with `transfers` when present"], False),
        ],
    },
    {
        "key": "E1.4",
        "title": "[EPIC 1.4] Bundled read API",
        "labels": ["type:epic", "epic:api", "size:M", "p2-medium",
                   "initiative:v0.1-foundation"],
        "body": """## Epic

The read server that ships **with** the code — a consumer runs it themselves
against the snapshot. No hosted service, no keys, no rate limits. Bilingual by
construction.

**FRs:** FR-2, FR-16

**In scope** — `/v1/search`, `/v1/teams/{id}`, `/v1/matches`, `/v1/h2h`, `?lang=`
**Out of scope** — auth, write endpoints, hosting, deep `/v1/players/{id}` (v0.2)

**Epic acceptance criteria**
- [ ] `make serve` runs against a snapshot with no configuration
- [ ] Every entity response carries `name_ar` and `name_en`
- [ ] Endpoints answer from the store only

**Key files / surfaces** — `kooora/api/main.py`, `kooora/api/routes/`

**Dependencies** — Epics 1.1–1.3

_An epic is a large body of work broken into stories._
""",
        "stories": [
            ("[STORY 1.4.1] /v1 read endpoints",
             ["size:L", "p2-medium", "epic:api"],
             "As an **app developer**, I want **to query the dataset over HTTP without deploying anything** so that **I can prototype in minutes instead of writing SQL**.",
             ["`GET /v1/search?q=` resolves an Arabic or English name to entities",
              "`GET /v1/teams/{id}` returns the profile with derived form",
              "`GET /v1/matches?competition=&from=&to=` filters correctly",
              "`GET /v1/h2h?a=&b=` returns the derived record",
              "Unknown ids return 404 with a clear message"], False),
            ("[STORY 1.4.2] Bilingual responses & ?lang=",
             ["size:S", "p2-medium", "epic:api"],
             "As an **app developer building an Arabic UI**, I want **to pick the display language per request** so that **I don't have to map names myself**.",
             ["`name_ar` + `name_en` always present in entity payloads",
              "`?lang=ar|en` sets `display_name`; Arabic is the default",
              "Missing translations fall back to the other script rather than null"], False),
        ],
    },
    {
        "key": "E1.5",
        "title": "[EPIC 1.5] Snapshot & distribution",
        "labels": ["type:epic", "epic:distribution", "size:M", "p1-high",
                   "initiative:v0.1-foundation"],
        "body": """## Epic

Turn the store into the product: a single stamped SQLite file a stranger can
download and use, with the provenance to know what they hold and the licensing to
know what they may do with it.

**FRs:** FR-15, FR-17

**In scope** — export + stamping, round-trip verification, quickstart, data
dictionary, monthly-publish workflow **stub**
**Out of scope** — the live monthly automation box → Releases (v0.3)

**Epic acceptance criteria**
- [ ] `make snapshot` produces a file that opens with stdlib `sqlite3`
- [ ] `snapshot_meta` records version, generated-at, license, coverage, row counts
- [ ] A fresh clone reaches its first query in under 5 minutes

**Key files / surfaces** — `scripts/make_snapshot.py`, `scripts/pull_db.py`,
`docs/data-dictionary.md`, `.github/workflows/snapshot.yml`

**Dependencies** — Epics 1.1–1.3

_An epic is a large body of work broken into stories._
""",
        "stories": [
            ("[STORY 1.5.1] Export a stamped snapshot",
             ["size:M", "p1-high", "epic:distribution"],
             "As a **data practitioner**, I want **the database to tell me what it is** so that **I can cite its version, date and license in my work**.",
             ["`make snapshot` writes `dist/kooora-YYYY-MM.db`",
              "`snapshot_meta` stamped: version, generated_at, license, coverage, counts",
              "Vacuumed/compact; no provider keys or internal-only rows"], False),
            ("[STORY 1.5.2] Snapshot round-trip test",
             ["size:S", "p1-high", "epic:testing"],
             "As an **app developer**, I want **the published file to behave exactly like the source database** so that **what I download is what was tested**.",
             ["A fresh process reproduces resolution, form and H2H answers",
              "Opens with stdlib `sqlite3` only",
              "Runs in CI with no network"], False),
            ("[STORY 1.5.3] Quickstart & data dictionary",
             ["size:S", "p2-medium", "epic:docs"],
             "As an **app developer**, I want **to go from clone to first query in minutes** so that **evaluating this project costs me nothing**.",
             ["README quickstart verified on a clean clone",
              "`docs/data-dictionary.md` documents every table and column",
              "Attribution + takedown process stated"], False),
            ("[STORY 1.5.4] Monthly publish workflow (stub)",
             ["size:S", "p3-low", "epic:distribution"],
             "As a **maintainer**, I want **the publishing path scaffolded now** so that **turning on monthly releases later is configuration, not a build**.",
             ["`.github/workflows/snapshot.yml` exists, manual-dispatch only",
              "Documents the box-side cron + export → release flow",
              "Publishes nothing until enabled in v0.3"], False),
        ],
    },
]


def story_body(parent_ref: str, user_story: str, criteria: list[str], done: bool) -> str:
    box = "x" if done else " "
    lines = [f"> **Parent epic:** {parent_ref}", "", "**User story**", "",
             f"> {user_story}", "", "**Acceptance criteria**", ""]
    lines += [f"- [{box}] {c}" for c in criteria]
    return "\n".join(lines) + "\n"


def create(title: str, body: str, labels: list[str], dry: bool,
           seen: dict[str, int]) -> int | None:
    if title in seen:
        print(f"  = exists  #{seen[title]}  {title}")
        return seen[title]
    if dry:
        print(f"  + create  {title}   [{', '.join(labels)}]")
        return None
    url = gh("issue", "create", "--title", title, "--body", body,
             *sum((["--label", l] for l in labels), []))
    num = int(url.rstrip("/").split("/")[-1])
    print(f"  + created #{num}  {title}")
    return num


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    print("Labels:")
    ensure_labels(dry)
    seen = {} if dry else existing_titles()

    print("\nTheme:")
    theme_no = create(THEME["title"], THEME["body"], THEME["labels"], dry, seen)

    print("\nInitiative:")
    ref = f"#{theme_no} — {THEME['title']}" if theme_no else THEME["title"]
    init_body = f"> **Parent theme:** {ref}\n\n{INITIATIVE['body']}"
    init_no = create(INITIATIVE["title"], init_body, INITIATIVE["labels"], dry, seen)

    epic_numbers = []
    for epic in EPICS:
        print(f"\n{epic['key']}:")
        iref = f"#{init_no} — {INITIATIVE['title']}" if init_no else INITIATIVE["title"]
        body = f"> **Parent initiative:** {iref}\n\n{epic['body']}"
        epic_no = create(epic["title"], body, epic["labels"], dry, seen)
        epic_numbers.append((epic["title"], epic_no))
        eref = f"#{epic_no} — {epic['title']}" if epic_no else epic["title"]
        for title, labels, us, criteria, done in epic["stories"]:
            create(title, story_body(eref, us, criteria, done),
                   ["type:story", "initiative:v0.1-foundation", *labels], dry, seen)

    if dry:
        print("\n(dry run — nothing created)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
