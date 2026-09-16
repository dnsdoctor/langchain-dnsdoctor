"""Dispatch and relay, with the request layer stubbed out."""

import base64
import json
from typing import Any
from unittest import mock

import pytest

from langchain_dnsdoctor import (
    DESCRIPTION_CAP,
    ApiError,
    DnsDoctorToolkit,
    dnsdoctor_instructions,
    dnsdoctor_tools,
)
from langchain_dnsdoctor.tools import ROUTES, TOOL_DEFINITIONS

SENTINEL = {"domain": "example.com", "fix_record": "v=DMARC1; p=quarantine; np=reject"}


def _tool(name: str) -> Any:
    return dnsdoctor_tools([name])[0]


def test_every_fixture_tool_is_built_and_routed() -> None:
    names = [tool.name for tool in dnsdoctor_tools()]
    assert names == [entry["name"] for entry in TOOL_DEFINITIONS]
    assert set(names) == set(ROUTES)
    assert len(names) == 20


def test_unknown_name_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown DNS Doctor tool"):
        dnsdoctor_tools(["scan_domain", "nope"])


def test_json_kind_posts_the_arguments_unchanged() -> None:
    with mock.patch("langchain_dnsdoctor.tools.request", return_value=SENTINEL) as req:
        out = _tool("scan_domain").invoke({"domain": "example.com"})
    req.assert_called_once_with("POST", "/api/v1/scan", json_body={"domain": "example.com"})
    assert out == json.dumps(SENTINEL, indent=2)  # relayed verbatim, never edited


def test_report_kind_puts_the_domain_in_the_path() -> None:
    with mock.patch("langchain_dnsdoctor.tools.request", return_value=SENTINEL) as req:
        _tool("get_report").invoke({"domain": "bücher.example/x"})
    req.assert_called_once_with("GET", "/api/v1/report/b%C3%BCcher.example%2Fx")


def test_query_kind_drops_absent_filters_only() -> None:
    with mock.patch("langchain_dnsdoctor.tools.request", return_value={"alerts": []}) as req:
        _tool("get_alerts").invoke({"domain": "example.com", "since": None, "limit": 5})
    req.assert_called_once_with(
        "GET", "/api/v1/alerts", params={"domain": "example.com", "limit": 5}
    )


def test_upload_kind_decodes_base64_into_a_multipart_file() -> None:
    raw = b"<feedback/>"
    with mock.patch("langchain_dnsdoctor.tools.request", return_value={"ok": True}) as req:
        _tool("parse_dmarc_report").invoke({"content_base64": base64.b64encode(raw).decode()})
    _method, path = req.call_args.args
    assert path == "/api/tools/dmarc-report-parse"
    assert req.call_args.kwargs["files"] == {
        "file": ("report.xml", raw, "application/octet-stream")
    }


def test_wrapped_and_base64url_report_input_decode_like_the_other_clients() -> None:
    raw = bytes(range(256)) * 3  # exercises every base64url-only character
    wrapped = base64.encodebytes(raw).decode()  # MIME line-wrapped, padded
    urlsafe = base64.urlsafe_b64encode(raw).decode().rstrip("=")  # -_ alphabet, no padding
    for encoded in (wrapped, urlsafe):
        with mock.patch("langchain_dnsdoctor.tools.request", return_value={"ok": True}) as req:
            _tool("parse_dmarc_report").invoke({"content_base64": encoded})
        assert req.call_args.kwargs["files"]["file"][1] == raw


def test_malformed_or_oversized_report_input_is_refused_before_decoding() -> None:
    tool = _tool("parse_dmarc_report")
    with mock.patch("langchain_dnsdoctor.tools.request") as req:
        bad = tool.invoke({"content_base64": "this is plainly not base64!!"})
        huge = tool.invoke({"content_base64": "A" * (3 * 1024 * 1024 + 1)})
    req.assert_not_called()
    assert "not valid base64" in bad
    assert "2 MiB" in huge


def test_a_transient_failure_is_text_the_model_reads_not_a_crash() -> None:
    err = ApiError("rate limited - slow down and retry", 429, True)
    with mock.patch("langchain_dnsdoctor.tools.request", side_effect=err):
        out = _tool("scan_domain").invoke({"domain": "example.com"})
    assert out == "rate limited - slow down and retry"


def test_descriptions_fit_the_openai_cap_and_lose_nothing() -> None:
    by_name = {entry["name"]: entry["description"] for entry in TOOL_DEFINITIONS}
    long_ones = [name for name, text in by_name.items() if len(text) > DESCRIPTION_CAP]
    assert long_ones, "the cap is untested until a fixture description exceeds it"
    instructions = dnsdoctor_instructions()
    for tool in dnsdoctor_tools():
        full = by_name[tool.name]
        assert len(tool.description) <= DESCRIPTION_CAP
        if tool.name in long_ones:
            assert full.startswith(tool.description) and tool.description.endswith(".")
            assert full in instructions  # the cut text travels in the instructions
        else:
            assert tool.description == full


def test_toolkit_exposes_tools_and_instructions() -> None:
    kit = DnsDoctorToolkit(tools=["check_record", "scan_domain"])
    assert [t.name for t in kit.get_tools()] == ["check_record", "scan_domain"]
    assert "PRESENT ANY RETURNED RECORD VERBATIM" in kit.instructions
    assert len(DnsDoctorToolkit().get_tools()) == 20
