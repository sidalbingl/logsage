# System Architecture

## High-Level Overview

LogSage runs on Elastic Cloud Serverless and consists of four main layers:
- Data generation (local Python scripts)
- Storage & search (Elasticsearch Serverless)
- Agent reasoning (Agent Builder + Elastic Managed LLM)
- Orchestration & action (Python orchestrator + Slack webhook)
- Visualization (Kibana Dashboards)

---

## Components

### 1. Data Layer
Synthetic microservice logs generated locally using Python scripts, ingested into
Elasticsearch via Bulk API. Five services: `auth-service`, `payment-service`,
`api-gateway`, `user-service`, `notification-service`.

Indices:
- `logsage-logs` — raw log events (timestamp, service, level, message, latency_ms)

### 2. Storage & Query Layer
Elasticsearch Serverless provides:
- Time-series analytics and aggregations
- Full-text search
- ES|QL querying for anomaly detection and correlation

### 3. Agent Layer
Elastic Agent Builder hosts three specialized agents:

| Agent | Role | Tools |
|---|---|---|
| Investigator | Detect anomalies, collect raw evidence | `detect_anomalies` (ES\|QL), `get_logs_by_timerange` (Search) |
| Analyst | Correlate events, build root cause hypothesis | `correlate_events` (ES\|QL), `get_service_metrics` (ES\|QL) |
| Validator | Verify hypothesis, assign confidence score | All tools from Investigator + Analyst |

Agents are called sequentially by the Python orchestrator via the A2A endpoint
(`/api/agent_builder/a2a/{agent_id}`) using JSON-RPC 2.0.

### 4. Orchestration Layer (`orchestrate.py`)
Four-phase pipeline:

1. **Phase 1 — Investigate**: Investigator agent detects anomalies and collects log evidence
2. **Phase 2 — Analyze**: Analyst agent correlates events and generates root cause hypothesis
3. **Phase 3 — Validate**: Validator agent re-queries data independently, assigns Verdict + Confidence Score
4. **Phase 4 — Escalate**: If Verdict is CONFIRMED/PARTIALLY CONFIRMED and Confidence ≥ 70:
   - Writes audit record to `logsage-actions` index
   - Sends rich Slack notification (Block Kit: root cause, affected services, recommendation, dashboard link)

Incident reports saved to `logsage-incidents` after every run.

### 5. Visualization
Kibana dashboard (`logsage-dashboard-001`) with 6 panels:

| Panel | Type | Data Source |
|---|---|---|
| Error Spike Timeline | Bar stacked | logsage-logs |
| Errors by Service | Bar | logsage-logs |
| Average Latency Over Time | Line | logsage-logs |
| Log Level Distribution | Donut | logsage-logs |
| Recent Incidents | Datatable | logsage-incidents |
| Actions Taken | Datatable | logsage-actions |

---

## Architecture Flow

```
[Local]  Python Log Generator
              ↓  (Bulk API)
[Cloud]  Elasticsearch — logsage-logs
              ↓
[Cloud]  orchestrate.py (Phase 1)
              ↓  A2A JSON-RPC 2.0
[Cloud]  Agent Builder — Investigator Agent
              ↓
[Cloud]  orchestrate.py (Phase 2)
              ↓  A2A JSON-RPC 2.0
[Cloud]  Agent Builder — Analyst Agent
              ↓
[Cloud]  orchestrate.py (Phase 3)
              ↓  A2A JSON-RPC 2.0
[Cloud]  Agent Builder — Validator Agent
              ↓
[Cloud]  orchestrate.py (Phase 4 — if confidence ≥ 70)
         ├─→  Elasticsearch — logsage-incidents (full report)
         ├─→  Elasticsearch — logsage-actions (audit record)
         └─→  Slack Webhook (Block Kit notification)
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Data generation | Python |
| Data ingestion | Elasticsearch Bulk API |
| Storage & search | Elasticsearch Serverless |
| Agent framework | Elastic Agent Builder |
| LLM | Elastic Managed LLM |
| Agent protocol | A2A (JSON-RPC 2.0) |
| Query language | ES\|QL |
| Orchestrator | Python (`orchestrate.py`) |
| Dashboard setup | Python (`setup_dashboard.py`) |
| Notifications | Slack Incoming Webhooks (Block Kit) |
| UI & dashboards | Kibana Lens + Agent Chat |
