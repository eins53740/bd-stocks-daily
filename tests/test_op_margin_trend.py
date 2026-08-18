"""N2: op_margin_3y_delta -- an additive field, never a score input."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_ticker as at  # noqa: E402


def _frame(op_income, revenue, dates):
    return pd.DataFrame({d: {"Operating Income": oi, "Total Revenue": rv}
                         for d, oi, rv in zip(dates, op_income, revenue)})


DATES = ["2025-12-31", "2024-12-31", "2023-12-31"]


def test_expanding_margin_is_positive():
    fs = _frame([250, 220, 200], [1000, 1000, 1000], DATES)
    out = at.op_margin_3y_delta(fs)
    assert out["op_margin_3y_delta_pp"] == pytest.approx(5.0)
    assert "2025-12-31" in out["op_margin_3y_basis"] and "2023-12-31" in out["op_margin_3y_basis"]


def test_compressing_margin_is_negative():
    fs = _frame([150, 180, 200], [1000, 1000, 1000], DATES)
    assert at.op_margin_3y_delta(fs)["op_margin_3y_delta_pp"] == pytest.approx(-5.0)


def test_the_basis_is_auditable_not_a_bare_number():
    """R15's lesson applied at birth: a delta a reader cannot check is a number on trust."""
    fs = _frame([250, 220, 200], [1000, 1000, 1000], DATES)
    basis = at.op_margin_3y_delta(fs)["op_margin_3y_basis"]
    assert "25.00%" in basis and "20.00%" in basis
    assert "annual operating income / revenue" in basis


def test_two_year_filer_says_which_year_is_missing():
    fs = _frame([250, 220], [1000, 1000], DATES[:2])
    out = at.op_margin_3y_delta(fs)
    assert out["op_margin_3y_delta_pp"] is None
    assert "not computable" in out["op_margin_3y_basis"]


def test_missing_frame_degrades_quietly_but_explains():
    out = at.op_margin_3y_delta(None)
    assert out["op_margin_3y_delta_pp"] is None
    assert "not computable" in out["op_margin_3y_basis"]


def test_zero_revenue_year_does_not_divide_by_zero():
    fs = _frame([250, 220, 200], [1000, 1000, 0], DATES)
    assert at.op_margin_3y_delta(fs)["op_margin_3y_delta_pp"] is None


def test_n_year_reader_never_backfills_a_gap():
    fs = _frame([250, None, 200], [1000, 1000, 1000], DATES)
    vals = at._stmt_n_years(fs, ("Operating Income",), 3)
    assert vals == [250.0, None, 200.0], "a hole stays a hole"


def test_field_is_not_referenced_by_any_scoring_code():
    """The whole point of shipping it additive: it must not be able to move the composite."""
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("finalize_score.py", "technical_score.py"):
        src = (scripts / name).read_text(encoding="utf-8")
        assert "op_margin_3y_delta" not in src, f"{name} must not consume it (G1 gate)"
    weights_src = (scripts / "analyze_ticker.py").read_text(encoding="utf-8")
    i = weights_src.index("WEIGHTS_V2_DEEP")
    assert "op_margin_3y_delta" not in weights_src[i:i + 4000], "not in the weight table"
