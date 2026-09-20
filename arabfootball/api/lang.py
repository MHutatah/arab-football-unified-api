"""Bilingual response shape — both names always, one display language.

Identity here is language-neutral: a name is a label, never a key. So every
entity payload carries **both** `name_ar` and `name_en`, and `?lang=` only
decides which of them is echoed as `display_name`. A caller building an Arabic
UI never has to map names itself, and a caller that wants the other script
still has it in the same response.

Two deliberate choices:

* **Arabic is the default.** This is an Arab-football dataset; a client that
  sends no preference gets the region's own script.
* **A missing translation falls back to the other script.** Half of this data
  starts life in Arabic-language sources and the transliteration may simply not
  exist yet; returning `null` would push that fallback into every consumer.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping

DEFAULT_LANG = "ar"
SUPPORTED_LANGS = ("ar", "en")

# Apps hand us whatever locale their UI is set to ("ar-SA", "en_GB"); the
# region subtag carries no naming information here, so only the language is read.
_SUBTAG = re.compile(r"[-_]")


def parse_lang(raw: str | None) -> str:
    """Normalize a `?lang=` value, defaulting to Arabic.

    Raises `ValueError` for a language we hold no names in — silently serving
    Arabic to someone who asked for French would look like a translation.
    """
    if raw is None or not str(raw).strip():
        return DEFAULT_LANG
    lang = _SUBTAG.split(str(raw).strip())[0].lower()
    if lang not in SUPPORTED_LANGS:
        raise ValueError(
            f"unsupported lang {raw!r}: supported languages are "
            f"{', '.join(SUPPORTED_LANGS)}"
        )
    return lang


def _usable(name: str | None) -> bool:
    return bool(name and str(name).strip())


def display_name(name_ar: str | None, name_en: str | None,
                 lang: str = DEFAULT_LANG) -> str | None:
    """The name to show, in `lang` when we have it, in the other script when not.

    `None` only when the entity has no name at all in either script.
    """
    preferred, fallback = (name_ar, name_en) if lang == "ar" else (name_en, name_ar)
    for name in (preferred, fallback):
        if _usable(name):
            return name
    return None


def entity_payload(entity: Mapping | None, lang: str = DEFAULT_LANG) -> dict | None:
    """Shape one stored entity row for the API: both names plus `display_name`."""
    if entity is None:
        return None
    name_ar, name_en = entity.get("name_ar"), entity.get("name_en")
    meta = entity.get("meta")
    if isinstance(meta, str):
        meta = json.loads(meta) if meta else None
    return {
        "id": entity.get("id"),
        "type": entity.get("type"),
        # Both scripts, always — present even when one of them is null.
        "name_ar": name_ar,
        "name_en": name_en,
        "display_name": display_name(name_ar, name_en, lang),
        "country": entity.get("country"),
        "provisional": bool(entity.get("provisional")),
        "meta": meta,
    }
