# Agent Design

All agents are created and configured in Kibana via Elastic Agent Builder UI.
LLM: Elastic Managed LLM (default, zero-config).

---

## Orchestrator (`orchestrate.py`)

The Python orchestrator calls agents sequentially via the A2A endpoint
(`/api/agent_builder/a2a/{agent_id}`) using JSON-RPC 2.0. It:

- Passes context (investigation → analysis → validation) between agents
- Retries on 502/503 with exponential backoff (up to 5 attempts)
- Parses Verdict and Confidence Score from the Validator's response
- Triggers Phase 4 auto-escalation when conditions are met
- Saves full incident reports to `logsage-incidents` Elasticsearch index

---

## Investigator Agent (`logsage`)

**Responsibilities:**
- Detect anomalies (error spikes, latency jumps)
- Define investigation time window
- Collect raw log evidence

**Tools:**
- `detect_anomalies` (ES|QL) — groups errors and latency by service/time bucket
- `get_logs_by_timerange` (Search) — retrieves log events for a given window

**System Prompt:**
> You are an incident investigator. When given a service name or time range, use your tools to detect anomalies. Identify error spikes, latency increases, and unusual patterns. Report your findings clearly with specific service names, time ranges, and error counts.

---

## Analyst Agent (`logsage_analyst`)

**Responsibilities:**
- Interpret investigation findings
- Correlate events across services and time
- Generate root cause hypotheses with supporting evidence

**Tools:**
- `correlate_events` (ES|QL) — matches events by request_id or service across time windows
- `get_service_metrics` (ES|QL) — retrieves latency/error metrics for a specific service

**System Prompt:**
> You are a system analyst. Given investigation findings, correlate events across services and time. Identify causal relationships and generate root cause hypotheses with supporting evidence. Reply with: Root Cause, Evidence (3 bullet points), Failure Sequence.

---

## Validator Agent (`logsage_validator`)

**Responsibilities:**
- Re-query data independently to verify or challenge the hypothesis
- Identify weak assumptions or gaps in evidence
- Assign Verdict and Confidence Score

**Tools:**
- All tools from Investigator and Analyst (for independent re-verification)

**System Prompt:**
> You are a validation expert. Review the analyst's root cause hypothesis. Re-query the data independently using your tools. Check if evidence supports the conclusion. Identify gaps or weak assumptions. Assign a Verdict (CONFIRMED / PARTIALLY CONFIRMED / UNCONFIRMED) and a Confidence Score from 0 to 100, followed by a Final Recommendation.

---

## Phase 4: Auto-Escalation

Triggered by the orchestrator when:
- Verdict is `CONFIRMED` or `PARTIALLY CONFIRMED`
- Confidence Score ≥ 70

Actions taken:
1. Writes an audit record to `logsage-actions` Elasticsearch index (incident_id, verdict, confidence, severity, recommendation, timestamp)
2. Sends a Slack Block Kit notification including:
   - Verdict, Confidence, Severity, Detection time
   - Root cause (extracted from Analyst output)
   - Affected services (extracted from Investigator output)
   - Recommendation (extracted from Validator output)
   - Direct link to Kibana dashboard

Severity mapping:
- Confidence ≥ 85 → `CRITICAL` (red #E01E5A)
- Confidence 70–84 → `HIGH` (orange #E8A020)

---

## Output Structure (per incident)

| Field | Source |
|---|---|
| incident_id | Generated (INC-XXXXXX) |
| verdict | Parsed from Validator output |
| confidence_score | Parsed from Validator output |
| investigation | Investigator agent response |
| analysis | Analyst agent response |
| validation | Validator agent response |
| action_id | logsage-actions document ID (if escalated) |
| status | complete / partial / investigation_only |

---

## Agent Builder Configuration

Each agent is configured in Kibana > Agents with:
1. **Name**: Agent identifier (used as path in A2A endpoint)
2. **System Prompt**: Instructions defining behavior and output format
3. **Tools**: Selected from the tools created in Kibana > Agents > Tools
4. **LLM Connector**: Elastic Managed LLM (default)
