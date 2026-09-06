"""The standard integration tests against the live API (LLM-free, scan-free)."""

import pytest
from langchain_core.tools import BaseTool
from langchain_tests.integration_tests import ToolsIntegrationTests

from langchain_dnsdoctor import dnsdoctor_tools

pytestmark = pytest.mark.integration


class TestValidateDmarcRecordIntegration(ToolsIntegrationTests):
    @property
    def tool_constructor(self) -> BaseTool:
        return dnsdoctor_tools(["validate_dmarc_record"])[0]

    @property
    def tool_invoke_params_example(self) -> dict[str, str]:
        return {"record": "v=DMARC1; p=none"}
