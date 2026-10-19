"""CloudWatch metrics via Embedded Metric Format (EMF).

Printing one EMF JSON line to stdout is enough: the awslogs driver ships it to
CloudWatch Logs, which turns it into metrics. No PutMetricData call, no extra
IAM permission, no added latency.
"""

from __future__ import annotations

import json
import sys
import time

NAMESPACE = "InjectShield"


def emit(service: str, metrics: dict[str, tuple[float, str]]) -> None:
    """metrics maps name -> (value, unit), e.g. {"ScanLatency": (184, "Milliseconds")}."""
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [["Service"]],
                    "Metrics": [{"Name": name, "Unit": unit} for name, (_, unit) in metrics.items()],
                }
            ],
        },
        "Service": service,
        **{name: value for name, (value, _) in metrics.items()},
    }
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()
