"""Entity resolution — the core of the engine.

Every incoming record from every collector passes through `resolve()`, which
returns the ONE canonical entity id for it. Order of attempts:

  1. provider id      — exact, authoritative, free
  2. normalized name  — within a country/type scope
  3. fuzzy            — transliteration-tolerant, above a threshold, unambiguous
  4. provisional      — create it, flag for review, never guess silently

Nothing downstream matches on names, so a wrong-country namesake (the
"Al Hilal -> South Sudan" bug that motivated this project) cannot happen: a
scope mismatch fails to a provisional entity instead of a confident wrong one.
"""
from __future__ import annotations

from dataclasses import dataclass

from kooora.resolve.normalize import norm, script_of, similarity, xkey

FUZZY_THRESHOLD = 0.86      # below this we create a provisional entity instead
FUZZY_MARGIN = 0.05         # best must beat runner-up by this, else ambiguous


@dataclass
class Resolution:
    entity_id: str
    method: str             # provider_id|name|fuzzy|created
    confidence: float
    provisional: bool = False


class Resolver:
    """Resolves provider records to canonical entity ids.

    `store` must provide:
      find_by_provider(provider, provider_id) -> entity_id | None
      find_by_norm(type, country, norm_name)  -> [entity_id]
      candidates(type, country)               -> [(entity_id, name)]
      create_entity(type, names, country, provisional) -> entity_id
      add_alias(entity_id, provider, provider_id, name_variant, script)
    """

    def __init__(self, store):
        self.store = store

    def resolve(self, *, type: str, provider: str, provider_id=None,
                name=None, name_ar=None, name_en=None, country=None) -> Resolution:
        names = [n for n in (name, name_ar, name_en) if n]

        # 1. provider id — authoritative
        if provider_id is not None:
            hit = self.store.find_by_provider(provider, str(provider_id))
            if hit:
                self._learn(hit, provider, provider_id, names)
                return Resolution(hit, "provider_id", 1.0)

        # 2. normalized name within scope — same script, then cross-script
        for n in names:
            key = norm(n)
            if not key:
                continue
            found = self.store.find_by_norm(type, country, key, cross_script=xkey(n))
            if len(found) == 1:
                self._learn(found[0], provider, provider_id, names)
                return Resolution(found[0], "name", 0.98)
            if len(found) > 1:
                # ambiguous even after scoping — refuse to guess
                return self._create(type, names, country, provider, provider_id,
                                    reason="ambiguous_exact")

        # 3. fuzzy, scoped, and only when it clearly wins
        best, second, best_id = 0.0, 0.0, None
        for cand_id, cand_name in self.store.candidates(type, country):
            for n in names:
                s = similarity(n, cand_name)
                if s > best:
                    best, second, best_id = s, best, cand_id
                elif s > second:
                    second = s
        if best_id and best >= FUZZY_THRESHOLD and (best - second) >= FUZZY_MARGIN:
            self._learn(best_id, provider, provider_id, names)
            return Resolution(best_id, "fuzzy", best)

        # 4. provisional — surfaced for review, never a silent wrong match
        return self._create(type, names, country, provider, provider_id,
                            reason="no_match")

    # ── helpers ─────────────────────────────────────────────────────────────
    def _create(self, type, names, country, provider, provider_id, reason) -> Resolution:
        by_script = {script_of(n): n for n in names}
        entity_id = self.store.create_entity(
            type=type, name_ar=by_script.get("ar"), name_en=by_script.get("en"),
            country=country, provisional=True)
        self._learn(entity_id, provider, provider_id, names)
        return Resolution(entity_id, "created", 0.0, provisional=True)

    def _learn(self, entity_id, provider, provider_id, names) -> None:
        """Record every id/spelling we saw, so the next pass resolves at step 1."""
        for n in names:
            self.store.add_alias(entity_id, provider,
                                 str(provider_id) if provider_id is not None else None,
                                 n, script_of(n))
