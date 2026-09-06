"""The two rules that keep this package honest, checked structurally.

1. Definitions come only from `tools.json`: no tool name, description or
   record literal is written in the package source.
2. The package never composes a record - the source carries no record-shaped
   string, and a tool's output is the API body serialized, byte-for-byte.
"""

import ast
import json
from pathlib import Path
from unittest import mock

from langchain_dnsdoctor import dnsdoctor_tools
from langchain_dnsdoctor.tools import TOOL_DEFINITIONS

PACKAGE = Path(__file__).resolve().parents[2] / "langchain_dnsdoctor"
SOURCES = sorted(PACKAGE.glob("*.py"))


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_source_carries_no_tool_name_description_or_record_literal() -> None:
    names = {entry["name"] for entry in TOOL_DEFINITIONS}
    descriptions = {entry["description"] for entry in TOOL_DEFINITIONS}
    record_markers = ("v=spf1", "v=DMARC1", "v=DKIM1")
    assert SOURCES, "no package sources found"
    for path in SOURCES:
        for value in _string_constants(path):
            assert value not in names, f"{path.name} names a tool inline: {value!r}"
            assert value not in descriptions, f"{path.name} restates a description"
            lowered = value.lower()
            assert not any(m.lower() in lowered for m in record_markers), (
                f"{path.name} carries a record-shaped literal: {value!r}"
            )


def test_tool_definitions_are_the_fixture_entries() -> None:
    fixture = json.loads((PACKAGE / "tools.json").read_text())
    tools = {tool.name: tool for tool in dnsdoctor_tools()}
    assert set(tools) == {entry["name"] for entry in fixture}
    for entry in fixture:
        assert tools[entry["name"]].args_schema == entry["inputSchema"]


def test_output_is_the_api_body_verbatim() -> None:
    body = {"record": "v=DMARC1; p=reject; np=reject", "nested": {"raw": "  keep  spacing  "}}
    with mock.patch("langchain_dnsdoctor.tools.request", return_value=body):
        out = dnsdoctor_tools(["build_dmarc_upgrade"])[0].invoke({"domain": "example.com"})
    assert json.loads(out) == body
