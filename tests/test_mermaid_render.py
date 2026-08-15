"""
Unit tests for mermaid_render — extraction, cache keying and the fallback contract.

No browser is spawned anywhere in this file. `render()` is exercised with `mmdc`
stubbed out, because the one property that actually matters for the 13:30 job is
that **every failure mode returns False instead of raising**, and that is testable
without Chromium. The real render was measured by hand (7.3 s cold, 3.6 s warm,
~94 KB PNG) and is recorded in the module docstring rather than in a test — a
network-and-browser-free suite is worth more than a slow assertion.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import mermaid_render as mr  # noqa: E402


SANKEY = """sankey-beta

Revenue,COGS,1467
Revenue,Gross Profit,1807
Gross Profit,Operating Income,1014
"""

REPORT = f"""### 2.1 Business model — money engine

Some prose about the company.

**Money-flow Sankey** (TTM, USD millions):

```mermaid
{SANKEY}```

*Legend: the flow reads left to right.*

### 2.2 Industry snapshot
"""


# --- extraction -------------------------------------------------------------

class TestExtraction:
    def test_a_report_sankey_is_found_with_its_kind(self):
        blocks = mr.extract_mermaid_blocks(REPORT)
        assert len(blocks) == 1
        kind, src = blocks[0]
        assert kind == "sankey-beta"
        assert "Revenue,COGS,1467" in src

    def test_find_sankey_returns_the_source(self):
        assert "Gross Profit,Operating Income" in mr.find_sankey(REPORT)

    def test_a_report_without_a_diagram_yields_none(self):
        assert mr.find_sankey("# Just prose\n\nNo diagrams here.") is None
        assert mr.extract_mermaid_blocks("# Just prose") == []

    def test_multiple_blocks_come_back_in_document_order(self):
        md = ("```mermaid\nflowchart TD\nA-->B\n```\n\ntext\n\n"
              "```mermaid\nsankey-beta\nA,B,1\n```\n")
        kinds = [k for k, _ in mr.extract_mermaid_blocks(md)]
        assert kinds == ["flowchart", "sankey-beta"]

    def test_find_sankey_skips_a_leading_flowchart(self):
        md = ("```mermaid\nflowchart TD\nA-->B\n```\n"
              "```mermaid\nsankey-beta\nA,B,1\n```\n")
        assert mr.find_sankey(md).startswith("sankey-beta")

    def test_a_non_mermaid_fence_is_not_picked_up(self):
        """A python block that happens to mention sankey must not be rendered."""
        md = "```python\n# sankey-beta is just a word here\nprint(1)\n```\n"
        assert mr.extract_mermaid_blocks(md) == []

    def test_an_indented_fence_inside_a_list_still_matches(self):
        md = "- item\n\n  ```mermaid\n  sankey-beta\n  A,B,1\n  ```\n"
        blocks = mr.extract_mermaid_blocks(md)
        assert len(blocks) == 1 and blocks[0][0] == "sankey-beta"

    def test_an_unterminated_fence_does_not_hang_or_raise(self):
        """A truncated report is a real failure mode — the run that produced it was
        killed mid-write. It must not take the renderer down with it."""
        blocks = mr.extract_mermaid_blocks("```mermaid\nsankey-beta\nA,B,1\n")
        assert blocks and blocks[0][0] == "sankey-beta"

    def test_an_empty_fence_is_ignored_rather_than_rendered(self):
        assert mr.extract_mermaid_blocks("```mermaid\n\n```\n") == []

    def test_extraction_tolerates_none_and_empty_input(self):
        assert mr.extract_mermaid_blocks(None) == []
        assert mr.extract_mermaid_blocks("") == []


class TestRealWorldPreambles:
    """Both variants below are on disk. Running the extractor over all 114 sankeys in
    the report corpus is what surfaced them; one sample would have found neither."""

    def test_a_yaml_config_frontmatter_does_not_hide_the_diagram(self):
        # 2026-08-12_FAE.MC_review.md
        src = ('---\nconfig:\n  sankey:\n    nodeColors:\n      Revenue: "#2563eb"\n'
               '    linkColor: source\n---\nsankey-beta\nRevenue,COGS,247.7\n')
        assert mr.diagram_kind(src) == "sankey-beta"
        assert mr.find_sankey(f"```mermaid\n{src}```\n") is not None

    def test_an_init_directive_does_not_hide_the_diagram(self):
        # 2026-06-15_SFTBY_fair.md
        src = '%%{init: {"theme":"base"}}%%\nsankey-beta\n\nRevenue,COGS,3782300\n'
        assert mr.diagram_kind(src) == "sankey-beta"
        assert mr.find_sankey(f"```mermaid\n{src}```\n") is not None

    def test_a_preamble_with_nothing_after_it_is_not_a_diagram(self):
        assert mr.diagram_kind("---\nconfig: {}\n---\n") == ""
        assert mr.diagram_kind("%%{init: {}}%%\n") == ""

    def test_an_unclosed_yaml_preamble_does_not_hang(self):
        assert mr.diagram_kind("---\nconfig:\n  sankey:\n") == ""


# --- cache keying -----------------------------------------------------------

class TestCacheKey:
    def test_the_same_diagram_hashes_the_same(self):
        cfg = mr.build_config()
        assert mr.cache_key(SANKEY, cfg, 100, 50) == mr.cache_key(SANKEY, cfg, 100, 50)

    def test_a_changed_diagram_misses(self):
        cfg = mr.build_config()
        assert mr.cache_key(SANKEY, cfg, 100, 50) != mr.cache_key(SANKEY + "\nA,B,2", cfg, 100, 50)

    def test_changed_dimensions_miss(self):
        cfg = mr.build_config()
        assert mr.cache_key(SANKEY, cfg, 100, 50) != mr.cache_key(SANKEY, cfg, 200, 50)

    def test_a_changed_theme_invalidates_the_cache(self):
        """Without this, a palette change leaves old PNGs in place and the report
        silently mixes two visual systems."""
        cfg = mr.build_config()
        other = mr.build_config()
        other["themeVariables"]["textColor"] = "#000000"
        assert mr.cache_key(SANKEY, cfg, 100, 50) != mr.cache_key(SANKEY, other, 100, 50)

    def test_surrounding_whitespace_is_not_a_cache_miss(self):
        """`render()` strips before handing the source to mmdc, so the key must strip
        too — otherwise a caller that reconstructs the key from its own copy of the
        diagram never hits the cache and every run pays for a fresh browser."""
        cfg = mr.build_config()
        assert mr.cache_key(SANKEY, cfg, 10, 10) == mr.cache_key("\n\n" + SANKEY + "\n ", cfg, 10, 10)

    def test_bumping_the_renderer_version_invalidates_the_cache(self, monkeypatch):
        cfg = mr.build_config()
        before = mr.cache_key(SANKEY, cfg, 100, 50)
        monkeypatch.setattr(mr, "RENDERER_VERSION", "999")
        assert mr.cache_key(SANKEY, cfg, 100, 50) != before


# --- the fallback contract --------------------------------------------------

class TestNeverBreaksTheJob:
    def test_disabled_by_env_returns_false_without_looking_for_mmdc(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BD_MERMAID", "0")
        monkeypatch.setattr(mr, "find_mmdc", lambda: (_ for _ in ()).throw(
            AssertionError("must not probe for mmdc when disabled")))
        assert mr.render(SANKEY, tmp_path / "x.png") is False

    def test_missing_mmdc_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mr, "find_mmdc", lambda: None)
        assert mr.render(SANKEY, tmp_path / "x.png") is False
        assert not (tmp_path / "x.png").exists()

    def test_empty_source_returns_false(self, tmp_path):
        assert mr.render("   ", tmp_path / "x.png") is False

    def test_a_nonzero_exit_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mr, "find_mmdc", lambda: "mmdc")

        class Proc:
            returncode = 1
            stdout = ""
            stderr = "Parse error on line 3"
        monkeypatch.setattr(mr.subprocess, "run", lambda *a, **k: Proc())
        assert mr.render(SANKEY, tmp_path / "x.png") is False

    def test_exit_zero_with_no_file_written_still_returns_false(self, monkeypatch, tmp_path):
        """mmdc has been observed to exit 0 and write nothing. Trusting the return
        code alone would hand the report a path to a file that does not exist."""
        monkeypatch.setattr(mr, "find_mmdc", lambda: "mmdc")

        class Proc:
            returncode = 0
            stdout = "Generating single mermaid chart"
            stderr = ""
        monkeypatch.setattr(mr.subprocess, "run", lambda *a, **k: Proc())
        assert mr.render(SANKEY, tmp_path / "x.png") is False

    def test_a_timeout_returns_false_rather_than_propagating(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mr, "find_mmdc", lambda: "mmdc")

        def boom(*a, **k):
            raise mr.subprocess.TimeoutExpired(cmd="mmdc", timeout=90)
        monkeypatch.setattr(mr.subprocess, "run", boom)
        assert mr.render(SANKEY, tmp_path / "x.png") is False

    def test_an_unexpected_exception_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mr, "find_mmdc", lambda: "mmdc")

        def boom(*a, **k):
            raise OSError("no such executable")
        monkeypatch.setattr(mr.subprocess, "run", boom)
        assert mr.render(SANKEY, tmp_path / "x.png") is False


# --- the cache actually short-circuits --------------------------------------

class TestCacheBehaviour:
    def test_a_cache_hit_never_spawns_a_browser(self, monkeypatch, tmp_path):
        cache = tmp_path / "_mermaid"
        cache.mkdir()
        key = mr.cache_key(SANKEY, mr.build_config(), mr.DEFAULT_WIDTH, mr.DEFAULT_HEIGHT)
        (cache / f"{key}.png").write_bytes(b"\x89PNG-cached")
        monkeypatch.setattr(mr, "find_mmdc", lambda: (_ for _ in ()).throw(
            AssertionError("cache hit must not reach mmdc")))
        out = tmp_path / "IMG" / "x.png"
        assert mr.render(SANKEY, out, cache_dir=cache) is True
        assert out.read_bytes() == b"\x89PNG-cached"

    def test_a_zero_byte_cache_entry_is_not_trusted(self, monkeypatch, tmp_path):
        """A render killed mid-write leaves an empty file. Serving it would embed a
        broken image in every future report for that ticker."""
        cache = tmp_path / "_mermaid"
        cache.mkdir()
        key = mr.cache_key(SANKEY, mr.build_config(), mr.DEFAULT_WIDTH, mr.DEFAULT_HEIGHT)
        (cache / f"{key}.png").write_bytes(b"")
        monkeypatch.setattr(mr, "find_mmdc", lambda: None)   # forces the miss path
        assert mr.render(SANKEY, tmp_path / "x.png", cache_dir=cache) is False

    def test_a_successful_render_populates_the_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mr, "find_mmdc", lambda: "mmdc")
        written = {}

        def fake_run(cmd, **kw):
            out = Path(cmd[cmd.index("-o") + 1])
            out.write_bytes(b"\x89PNG-fresh")
            written["cmd"] = cmd

            class P:
                returncode = 0
                stdout = stderr = ""
            return P()
        monkeypatch.setattr(mr.subprocess, "run", fake_run)
        cache = tmp_path / "_mermaid"
        out = tmp_path / "IMG" / "x.png"
        assert mr.render(SANKEY, out, cache_dir=cache) is True
        assert out.read_bytes() == b"\x89PNG-fresh"
        key = mr.cache_key(SANKEY, mr.build_config(), mr.DEFAULT_WIDTH, mr.DEFAULT_HEIGHT)
        assert (cache / f"{key}.png").read_bytes() == b"\x89PNG-fresh"

    def test_the_render_is_transparent_backed(self, monkeypatch, tmp_path):
        """Every PNG in this system is transparent so one image reads on a light HTML
        report and a dark Obsidian theme alike. A background flag would break that."""
        monkeypatch.setattr(mr, "find_mmdc", lambda: "mmdc")
        seen = {}

        def fake_run(cmd, **kw):
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"\x89PNG")
            seen["cmd"] = cmd

            class P:
                returncode = 0
                stdout = stderr = ""
            return P()
        monkeypatch.setattr(mr.subprocess, "run", fake_run)
        mr.render(SANKEY, tmp_path / "x.png", cache_dir=tmp_path / "c")
        cmd = seen["cmd"]
        assert cmd[cmd.index("-b") + 1] == "transparent"


# --- anti-drift -------------------------------------------------------------

def test_the_ink_matches_chart_theme():
    """mermaid_render copies chart_theme's ink instead of importing it, to keep
    render_report free of matplotlib. This test is the price of that copy: it fails
    the moment the two visual systems diverge."""
    matplotlib = pytest.importorskip("matplotlib")  # noqa: F841 — chart_theme needs it
    import chart_theme as th
    assert mr.INK == th.INK
    assert mr.INK_SECONDARY == th.INK_SECONDARY


def test_the_config_does_not_pretend_to_set_sankey_node_colours():
    """cScale* was measured to have NO effect on sankey-beta (it uses a hard-coded d3
    scheme). Shipping those keys anyway would look like the palette was under control
    when it is not — and the report legend would go on lying about it."""
    cfg = mr.build_config()
    assert not [k for k in cfg["themeVariables"] if k.startswith("cScale")]
