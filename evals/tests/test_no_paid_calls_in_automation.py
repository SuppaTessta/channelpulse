"""No model calls from automation (decisions D29): no workflow, scheduled or not, may hand the runner a model
service's credential or endpoint, Anthropic's or any other vendor's."""

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).parents[2] / ".github" / "workflows").glob("*.yml"))
# Every variable that could reach a model service, by the names the common vendors' SDKs read.
PROVIDER_VARS = re.compile(r"ANTHROPIC|GEMINI|GOOGLE_API_KEY|OLLAMA|OPENAI", re.IGNORECASE)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_carries_no_model_provider_credential(workflow):
    text = workflow.read_text(encoding="utf-8")
    assert not PROVIDER_VARS.search(text), PROVIDER_VARS.findall(text)


def test_workflows_found():
    assert WORKFLOWS


@pytest.mark.parametrize("line", ["ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}", "ANTHROPIC_AUTH_TOKEN: x",
                                  "GOOGLE_API_KEY: x", "OPENAI_API_KEY: x"])
def test_the_pattern_catches_each_provider(line):
    assert PROVIDER_VARS.search(line)
