"""The sixteen DNS Doctor tools as LangChain ``BaseTool`` instances.

Definitions come ONLY from ``tools.json`` - the fixture the hosted MCP server
generates, byte-pinned by the backend suite - so no tool name, description or
schema is written here. ``routes.json`` maps each tool to the REST endpoint it
calls, and the arguments travel unchanged: the argument names ARE the
endpoint's field names (pinned server-side as well).
"""

import base64
import binascii
import json
import re
from importlib.resources import files
from typing import Any
from urllib.parse import quote

from langchain_core.tools import BaseTool, ToolException
from langchain_core.tools.base import BaseToolkit

from langchain_dnsdoctor.api import ApiError, request

_PACKAGE = files("langchain_dnsdoctor")
TOOL_DEFINITIONS: list[dict[str, Any]] = json.loads(
    _PACKAGE.joinpath("tools.json").read_text("utf-8")
)
ROUTES: dict[str, dict[str, str]] = json.loads(_PACKAGE.joinpath("routes.json").read_text("utf-8"))
INSTRUCTIONS: str = _PACKAGE.joinpath("instructions.txt").read_text("utf-8").strip()

# OpenAI rejects a function description longer than this; two of the hosted
# descriptions are longer. They are cut at a sentence boundary and the FULL
# text travels in `dnsdoctor_instructions()` instead, so nothing is lost for an
# agent that reads the instructions - which every agent should.
DESCRIPTION_CAP = 1024
_DEFAULT_REPORT_FILENAME = "report.xml"
# The API refuses a report over 2 MiB; base64 is 4/3 of that plus padding, so an
# encoded string past this bound cannot be accepted and is refused BEFORE decoding
# rather than decoded into memory first.
_MAX_REPORT_ENCODED = 3 * 1024 * 1024


def _fit(description: str, cap: int = DESCRIPTION_CAP) -> str:
    if len(description) <= cap:
        return description
    end = description.rfind(". ", 0, cap)
    return description[: end + 1] if end > 0 else description[:cap]


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"'{key}' is required and must be a non-empty string", None, False)
    return value


def call_tool(name: str, args: dict[str, Any]) -> Any:
    """Run one tool against the API and return the parsed body, untouched."""
    route = ROUTES[name]
    kind = route["kind"]
    if kind == "report":
        domain = _require_str(args, "domain")
        return request("GET", f"/api/v1/report/{quote(domain, safe='')}")
    if kind == "query":
        # Absent filters stay absent: the server owns every default.
        return request(
            "GET", route["path"], params={k: v for k, v in args.items() if v is not None}
        )
    if kind == "upload":
        encoded = _require_str(args, "content_base64")
        if len(encoded) > _MAX_REPORT_ENCODED:
            raise ApiError("'content_base64' is larger than the 2 MiB report limit", None, False)
        # The same tolerance as Node's decoder in the TypeScript clients: MIME
        # line wrapping, the base64url alphabet and dropped padding all decode;
        # anything else is refused locally, before a byte goes on the wire.
        normalized = re.sub(r"\s+", "", encoded).replace("-", "+").replace("_", "/")
        normalized += "=" * (-len(normalized) % 4)
        try:
            content = base64.b64decode(normalized, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ApiError(f"'content_base64' is not valid base64 ({exc})", None, False) from exc
        filename = args.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            filename = _DEFAULT_REPORT_FILENAME
        upload = {route["field"]: (filename, content, "application/octet-stream")}
        return request("POST", route["path"], files=upload)
    return request("POST", route["path"], json_body=args)


class DnsDoctorTool(BaseTool):
    """One hosted DNS Doctor tool.

    ``name``, ``description`` and ``args_schema`` are the fixture entry's;
    ``_run`` sends the arguments to the tool's endpoint and returns the response
    JSON as text - verbatim, never edited. A transport failure surfaces as the
    tool's text output (``handle_tool_error``) carrying the not-a-verdict rule,
    never as an exception that ends the run.
    """

    def _run(self, **kwargs: Any) -> str:
        try:
            return json.dumps(call_tool(self.name, kwargs), indent=2)
        except ApiError as exc:
            raise ToolException(str(exc)) from exc


def dnsdoctor_tools(names: list[str] | None = None) -> list[DnsDoctorTool]:
    """Every hosted tool, or the named subset, in the fixture's sorted order."""
    known = {entry["name"] for entry in TOOL_DEFINITIONS}
    wanted = None if names is None else set(names)
    if wanted is not None and not wanted <= known:
        raise ValueError(f"unknown DNS Doctor tool(s): {sorted(wanted - known)}")
    return [
        DnsDoctorTool(
            name=entry["name"],
            description=_fit(entry["description"]),
            args_schema=entry["inputSchema"],
            handle_tool_error=True,
        )
        for entry in TOOL_DEFINITIONS
        if wanted is None or entry["name"] in wanted
    ]


def dnsdoctor_instructions() -> str:
    """The hosted server's own guidance, for the agent's system prompt.

    Records verbatim, ``temperror`` is not a failure, ``not_registered`` is not
    health, SPF is diagnose-only, a human approves every DNS write - plus the
    full text of any description abridged for ``DESCRIPTION_CAP``.
    """
    full = [
        f"Full description of the `{entry['name']}` tool:\n{entry['description']}"
        for entry in TOOL_DEFINITIONS
        if len(entry["description"]) > DESCRIPTION_CAP
    ]
    return "\n\n".join([INSTRUCTIONS, *full])


class DnsDoctorToolkit(BaseToolkit):
    """All sixteen tools (or ``tools=[...]`` for a subset) plus their instructions."""

    tools: list[str] | None = None

    def get_tools(self) -> list[BaseTool]:
        return list(dnsdoctor_tools(self.tools))

    @property
    def instructions(self) -> str:
        return dnsdoctor_instructions()
