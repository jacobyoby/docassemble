"""Synthetic differential-test oracle; never imported by production services."""

import base64
import hashlib
import json
from pathlib import Path
import sys

from native_support import LogAggregator


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "tests/privacy_native/reference/log_aggregate.py"
    cases = json.loads(sys.stdin.buffer.read(8 * 1024 * 1024))
    result = []
    for case in cases:
        aggregate = LogAggregator(case["component"])
        steps = [aggregate.snapshot()]
        for operation in case["operations"]:
            if operation["finish"]:
                aggregate.finish(operation["stream"])
            else:
                aggregate.feed(operation["stream"], base64.b64decode(operation["data"] or "", validate=True))
            steps.append(aggregate.snapshot())
        result.append(steps)
    json.dump({"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "snapshots": result}, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
