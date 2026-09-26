"""Paid Anthropic calls are opt-in: no workflow, scheduled or not, may hand the runner a model credential."""

from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).parents[2] / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_carries_no_anthropic_credential(workflow):
    assert "ANTHROPIC" not in workflow.read_text(encoding="utf-8").upper()


def test_workflows_found():
    assert WORKFLOWS
