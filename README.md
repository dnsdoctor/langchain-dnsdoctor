# langchain-dnsdoctor

LangChain tools for [DNS Doctor](https://dnsdoctor.dev): scan, diagnose and fix a domain's
email authentication (SPF, DMARC, DKIM), check a DNS change from six locations on four
continents, audit an SPF include chain, and read monitoring alerts. Every verdict is
deterministic and every record comes from a validating engine, never from a language model.

Sixteen tools, the same set the hosted MCP server exposes. Tool names, descriptions and
input schemas are generated from that server and shipped in `tools.json`; this package
restates none of them.

## Install

```bash
pip install langchain-dnsdoctor
```

Python 3.10+, `langchain-core` 1.x. No API key is needed for the fourteen anonymous tools.

## Use

```python
from langchain.agents import create_agent
from langchain_dnsdoctor import DnsDoctorToolkit

toolkit = DnsDoctorToolkit()
agent = create_agent(
    model="claude-sonnet-4-6",
    tools=toolkit.get_tools(),
    system_prompt=toolkit.instructions,
)
agent.invoke({"messages": [{"role": "user", "content": "Is example.com spoofable? Fix it."}]})
```

`toolkit.instructions` is the hosted server's own guidance and belongs in the system prompt:
present records verbatim, a `temperror` status is transient and not a failure,
`not_registered: true` is not health, SPF is diagnose-only, a human approves every DNS
change. Two tool descriptions are longer than OpenAI's 1024-character limit for function
descriptions; those are cut at a sentence boundary on the tool and carried in full in the
instructions.

A subset, or a single tool:

```python
from langchain_dnsdoctor import dnsdoctor_tools

scan, upgrade = dnsdoctor_tools(["scan_domain", "build_dmarc_upgrade"])
print(scan.invoke({"domain": "example.com"}))
```

## Tools

| Tool | What it answers |
| --- | --- |
| `scan_domain`, `get_report` | The full report: SPF, DKIM, DMARC, MX, DNS health, blacklists, domain and TLS expiry, with copy-paste fix records |
| `build_dmarc_upgrade`, `generate_dmarc_record`, `validate_dmarc_record` | The next safe DMARC rung for a domain, a record from scratch, or a check of one you have |
| `count_spf_lookups`, `audit_spf_includes` | The 10-lookup budget, and who can transitively send as the domain |
| `check_dkim_selector`, `check_record`, `check_reverse_dns`, `check_propagation` | One selector, one record, one IP, or whether a change has gone global |
| `parse_dmarc_report` | An aggregate report (XML, gzip or zip, base64-encoded) as a source table |
| `build_parked_domain_records` | The three records that stop a non-sending domain being spoofed |
| `start_monitoring_signup` | A signup link that carries the domain into paid monitoring, for a human to open |
| `get_alerts`, `get_readiness` | Monitoring reads; need `DNSDOCTOR_API_TOKEN` |

## Environment

| Variable | Effect |
| --- | --- |
| `DNSDOCTOR_API_TOKEN` | Optional bearer token. Raises the anonymous rate limit and unlocks the two monitoring reads. Never prompted for. |
| `DNSDOCTOR_API_BASE` | Override the API origin (default `https://dnsdoctor.dev`). |

Past the free per-caller allowance the API answers `402` with an [x402](https://x402.org)
offer (USDC on Base). This package does not pay; the tool returns the offer text so an
agent with an x402 client can retry with payment, or wait.

## Rules the tools follow

- A transport failure (rate limit, 402, 503, 5xx, network) is returned as text that says it is
  not a verdict about the domain. It never raises.
- Responses are relayed byte-for-byte. The package composes no record and no URL.
- SPF is diagnose-only. The one SPF record the API ever emits is the constant `-all` inside the
  parked-domain pack, for a domain the server verified sends no mail.

## Development

```bash
pip install -e ".[test]"
pytest                      # unit tests, offline
pytest tests/integration_tests -m integration   # one live call against dnsdoctor.dev
```

Apache-2.0.
