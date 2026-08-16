"""Single source of the skill version.

Everything that displays a version reads it from here: the report footer watermark, the
HTML renderer, and the release checklist in docs/CHANGELOG.md. Nothing else hard-codes a
version string -- the SKILL.md H1 drifted a whole version (claiming v4.1 while the body
documented v4.2) precisely because the version lived in prose.

Bump this in the same commit that appends to docs/CHANGELOG.md and creates the git tag.
"""
from __future__ import annotations

__version__ = "4.3.1"

# Bumped to the release value when a wave set closes; "-dev" while a version is in flight,
# so a report rendered mid-wave is visibly not a released build.
SCHEMA_VERSION = "2.2"  # composite scoring schema -- frozen since v2.2, unchanged by v4.x


def version_string() -> str:
    """`4.3.0-dev` -- the bare version, for the footer watermark."""
    return __version__


def full_version_string() -> str:
    """`v4.3.0-dev (schema 2.2)` -- version plus the scoring schema it computes under.

    The pair matters: v4.x waves are overlay-only, so two different skill versions can and
    do produce the same composite. Showing both makes that explicit rather than implying a
    score changed because the version did.
    """
    return f"v{__version__} (schema {SCHEMA_VERSION})"
