"""Internal documentation links must resolve.

The repo shipped publicly with `docs/SPEC.md` referenced from the README but never
committed — three dangling references a reader would hit immediately. Cheap to
prevent, embarrassing to leave: this walks every markdown file and asserts each
relative link points at something that exists.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]+\]\((?!https?:|mailto:|#)([^)]+)\)")


def _markdown_files():
    return [p for p in ROOT.rglob("*.md") if ".git" not in p.parts]


@pytest.mark.parametrize("md", _markdown_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_internal_links_resolve(md):
    broken = []
    for m in LINK.finditer(md.read_text(encoding="utf-8")):
        target = m.group(1).split("#")[0].strip()
        if not target:
            continue
        if not (md.parent / target).resolve().exists():
            broken.append(target)
    assert not broken, f"{md.relative_to(ROOT).as_posix()} links to missing: {broken}"


def test_spec_exists_and_is_referenced():
    """SPEC.md is the architecture doc the README points readers at."""
    spec = ROOT / "docs" / "SPEC.md"
    assert spec.exists(), "docs/SPEC.md is referenced by the README and must exist"
    assert "docs/SPEC.md" in (ROOT / "README.md").read_text(encoding="utf-8")
