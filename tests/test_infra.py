"""Keep the CloudFormation templates, deploy.sh and teardown.sh in step.

A template that deploy.sh never deploys, or that teardown.sh never deletes, would
either be missing from the stack or keep billing after a session (requirement N5).
"""

import re
from pathlib import Path

from injectshield_shared.config import Settings

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"
DEPLOY = (ROOT / "scripts" / "deploy.sh").read_text()
TEARDOWN = (ROOT / "scripts" / "teardown.sh").read_text()


def templates() -> set[str]:
    return {p.stem for p in INFRA.glob("*.yaml")}


def deploy_order() -> list[str]:
    return re.findall(r"^\s*deploy_stack (\w+)", DEPLOY, flags=re.MULTILINE)


def teardown_order() -> list[str]:
    match = re.search(r"^STACKS=\(([^)]*)\)", TEARDOWN, flags=re.MULTILINE)
    assert match, "teardown.sh must define STACKS=(...)"
    return match.group(1).split()


def test_every_template_is_deployed():
    assert set(deploy_order()) == templates()


def test_every_template_is_torn_down():
    assert set(teardown_order()) == templates()


def test_teardown_deletes_in_reverse_deploy_order():
    assert teardown_order() == list(reversed(deploy_order()))


def test_max_receives_match_across_queue_task_and_worker():
    queue = re.search(r"MaxReceiveCount:\s*\n(?:\s+\w+:.*\n)*?\s+Default: (\d+)", (INFRA / "queue.yaml").read_text())
    task = re.search(r"Name: WORKER_MAX_RECEIVES, Value: \"(\d+)\"", (INFRA / "compute.yaml").read_text())
    assert queue and task
    assert int(queue.group(1)) == int(task.group(1)) == Settings.model_fields["worker_max_receives"].default
