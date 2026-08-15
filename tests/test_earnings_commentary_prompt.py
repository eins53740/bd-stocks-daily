"""
Contract tests for prompts/08_earnings_commentary.md (v4.3 wave 2.4a).

There is no Python module to unit-test here — the deliverable is a prompt plus its
wiring in SKILL.md. What CAN break silently is the wiring: a prompt that no phase
invokes, a substitution the phase never supplies, or an output section that does
not exist. These tests pin exactly that.

They also pin the two decisions this item turned on, because both are the kind
that quietly get undone:
 - the commentary lands in §2.7/§2.8, which already exist for this job, NOT in a
   new section beside them,
 - it is opt-in, because it costs a WebFetch plus an LLM call per ticker on a job
   already running at 22-24 minutes of a 30-minute ceiling.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "08_earnings_commentary.md"
SKILL = ROOT / "SKILL.md"


@pytest.fixture(scope="module")
def prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_the_prompt_exists():
    assert PROMPT.is_file()


@pytest.mark.parametrize("sub", [
    "{COMPANY}", "{TICKER}", "{FILING_META}", "{FILING_TEXT}",
    "{NUMBERS_JSON}", "{PRIOR_SUMMARY}", "{STYLE_RULES}",
])
def test_every_declared_substitution_appears_in_the_body(prompt, sub):
    # A substitution named in the header but absent from the fenced prompt is a
    # value the caller assembles and throws away.
    body = prompt.split("```", 1)[1]
    assert sub in body


def test_the_ground_truth_rule_is_restated_where_it_is_most_at_risk(prompt):
    """This prompt hands an LLM a document full of numbers and asks for prose.
    It is the single most likely place in the skill to leak an LLM-read figure
    into a report, so the rule is restated inside it, not merely inherited."""
    assert "{NUMBERS_JSON}" in prompt
    low = prompt.lower()
    assert "ground-truth rule" in low
    assert "may not" in low or "never" in low


def test_the_filing_text_is_declared_narrative_only(prompt):
    assert "narrative source ONLY" in prompt or "never read a number off this" in prompt


def test_it_creates_no_third_ground_truth_exception(skill):
    # SKILL.md documents exactly two exceptions (segments, macro). This item must
    # not quietly become a third.
    assert "não** cria uma terceira excepção" in skill or \
        "não cria uma terceira excepção" in skill


def test_the_output_carries_the_filing_date_so_staleness_is_visible(prompt):
    assert "{FORM}, {PERIOD}, filed {DATE}" in prompt


def test_a_missing_filing_degrades_to_one_explicit_line(prompt):
    assert "Latest filing not available." in prompt


def test_the_tone_comparison_is_required(prompt):
    assert "Tone vs prior print" in prompt


def test_new_risk_language_must_be_named_explicitly(prompt):
    # The MPWR 10-Q that motivated this carries "remediate our material weakness"
    # — precisely the sentence a summary would smooth away.
    low = prompt.lower()
    for phrase in ("going concern", "material weakness", "covenant", "restatement"):
        assert phrase in low


# --- wiring -----------------------------------------------------------------

def test_a_phase_actually_invokes_the_prompt(skill):
    assert "08_earnings_commentary.md" in skill


def test_the_prompt_is_in_the_prompt_registry_table(skill):
    row = [ln for ln in skill.splitlines()
           if ln.startswith("| `08_earnings_commentary.md`")]
    assert len(row) == 1


def test_it_is_opt_in_and_off_on_the_scheduled_path(skill, prompt):
    assert "BD_EARNINGS_COMMENT" in skill
    assert "BD_EARNINGS_COMMENT" in prompt
    assert "opt-in" in prompt.lower()


def test_it_targets_the_sections_that_already_exist(skill, prompt):
    """§2.7 and §2.8 have always been 'what changed last quarter'. Adding a third
    section beside them while they kept printing 'narrative unavailable' was the
    trap; these assertions are what stops a later edit walking back into it."""
    assert "2.8" in prompt and "2.7" in prompt
    assert "NÃO é uma secção nova" in skill
    assert "2.6d" not in prompt


def test_edgar_is_the_us_source_and_get_narrative_is_the_fallback(skill):
    i_edgar = skill.find("edgar.py` --text") if "edgar.py` --text" in skill \
        else skill.find("edgar.py --text")
    assert i_edgar != -1
    # The Phase 4 text must no longer instruct the yfinance blurb unconditionally.
    assert "when EDGAR was unavailable" in skill
