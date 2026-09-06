"""LangChain's standard tool tests, run against one representative tool.

`validate_dmarc_record` is deterministic, LLM-free and scan-free, so the
integration twin (`tests/integration_tests/`) can hit the live API cheaply.
"""

from langchain_core.tools import BaseTool
from langchain_tests.unit_tests import ToolsUnitTests

from langchain_dnsdoctor import dnsdoctor_tools


class TestValidateDmarcRecordUnit(ToolsUnitTests):
    @property
    def tool_constructor(self) -> BaseTool:
        return dnsdoctor_tools(["validate_dmarc_record"])[0]

    @property
    def tool_invoke_params_example(self) -> dict[str, str]:
        return {"record": "v=DMARC1; p=none"}
