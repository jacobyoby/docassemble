"""Load the exact checkout runtime without installation or PYTHONPATH setup."""

import importlib.util
from pathlib import Path


RUNTIME = Path(__file__).resolve().parent / "reference/log_aggregate.py"
SPEC = importlib.util.spec_from_file_location("reviewed_log_aggregate", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load the checkout's privacy aggregator")
AGGREGATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGGREGATE)

LogAggregator = AGGREGATE.LogAggregator
_MAX_LINE = AGGREGATE._MAX_LINE
_COUNTER_MAX = AGGREGATE._COUNTER_MAX
_SCHEMA_VERSION = AGGREGATE._SCHEMA_VERSION
