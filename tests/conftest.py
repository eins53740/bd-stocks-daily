"""Suite-wide guards.

WHY THIS FILE EXISTS. `run_daily.run_step` records a per-node timing on every call, and
`node_timing.record` writes to the REAL `StocksDaily/_timings/<today>.jsonl` -- the operational
instrumentation the pipeline is judged by. The order-contract tests call `run_step` with stub
steps named "A" and "X", so **every test run injected fake nodes into production data**: measured
2026-08-19, 12 rows on 08-17, 54 on 08-18 and 21 on 08-19, tracking test activity rather than
pipeline activity. The rows were spotted while auditing the day's timings and looked at first like
a mystery caller; they were us.

`BD_TIMINGS=0` is `node_timing`'s own documented escape hatch, and it is read at IMPORT time -- so
it has to be set before any test module imports the module, which is exactly what a conftest is
for. pytest imports this file before collecting tests.

Do not replace this with a monkeypatch inside one test class: the point is that NO test, present or
future, can write to the operational log by accident.
"""
import os

os.environ["BD_TIMINGS"] = "0"
