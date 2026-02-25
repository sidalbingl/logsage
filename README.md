# LogSage — Multi-Agent Incident Intelligence

LogSage is a multi-agent AI system that automatically detects, investigates, and escalates incidents from microservice logs — built on Elastic Agent Builder.

## What It Does

On-call engineers spend hours sifting through dashboards and correlating log events to determine if an alert is real. LogSage automates the entire pipeline:

1. **Investigator Agent** — detects error spikes and latency anomalies using ES|QL
2. **Analyst Agent** — correlates events across services, builds a root cause hypothesis
3. **Validator Agent** — independently re-queries data, assigns a Verdict and Confidence Score (0–100)
4. **Auto-Escalation** — if Confidence ≥ 70, writes an audit record to Elasticsearch and sends a rich Slack notification

Every incident report is persisted to Elasticsearch. A 6-panel Kibana dashboard provides full observability.

## Architecture

```
Python Log Generator
        ↓  (Bulk API)
Elasticsearch — logsage-logs
        ↓
orchestrate.py  →  Investigator Agent  (A2A / JSON-RPC 2.0)
                →  Analyst Agent
                →  Validator Agent
                ↓
        logsage-incidents  (full report)
        logsage-actions    (audit trail)
        Slack              (Block Kit notification)
```

## Project Structure

```
├── scripts/
│   ├── generate_logs.py    # Generate synthetic microservice logs
│   ├── ingest.py           # Ingest logs into Elasticsearch
│   ├── setup_dashboard.py  # Create Kibana data views, visualizations, dashboard
│   └── orchestrate.py      # 4-phase multi-agent pipeline
├── data/
│   └── logs.json           # Generated log data (gitignored)
├── docs/
│   ├── architecture.md
│   ├── agentdesign.md
│   └── submission.md
├── .env.example
└── requirements.txt
```

## Prerequisites

- Python 3.10+
- Elastic Cloud Serverless project (Elasticsearch type)
- Agents created in Kibana Agent Builder (see [docs/agentdesign.md](docs/agentdesign.md))
- Slack Incoming Webhook URL (optional)

## Setup

**1. Clone and configure environment**

```bash
git clone https://github.com/your-username/logsage.git
cd logsage
cp .env.example .env
# Edit .env with your Elastic Cloud credentials
```

**2. Generate and ingest logs**

```bash
py scripts/generate_logs.py   # Creates data/logs.json
py scripts/ingest.py          # Ingests logs into Elasticsearch
```

**3. Set up Kibana dashboard**

```bash
py scripts/setup_dashboard.py
```

This creates all data views, visualizations, and the LogSage dashboard automatically.

**4. Create agents in Kibana**

Follow [docs/agentdesign.md](docs/agentdesign.md) to configure the three agents (`logsage`, `logsage_analyst`, `logsage_validator`) in Kibana Agent Builder.

**5. Run the orchestrator**

```bash
py scripts/orchestrate.py
```

Or with a custom prompt:

```bash
py scripts/orchestrate.py --prompt "Investigate auth-service errors in the last 24 hours"
```

## Environment Variables

| Variable | Description |
|---|---|
| `ELASTICSEARCH_URL` | Elasticsearch endpoint (from Elastic Cloud) |
| `KIBANA_URL` | Kibana endpoint (from Elastic Cloud) |
| `ELASTICSEARCH_API_KEY` | API key (Base64 encoded, from Stack Management → API Keys) |
| `WEBHOOK_URL` | Slack or Discord webhook URL (optional) |

## Dashboard Panels

| Panel | Description |
|---|---|
| Error Spike Timeline | ERROR log counts over time |
| Errors by Service | Per-service error breakdown |
| Average Latency Over Time | `latency_ms` trend |
| Log Level Distribution | INFO / WARN / ERROR ratio |
| Recent Incidents | AI-generated incident reports |
| Actions Taken | Auto-escalation audit trail |

## Tech Stack

- **Elastic Agent Builder** — agent hosting and tool orchestration
- **Elasticsearch Serverless** — log storage, ES|QL queries, time-series analytics
- **Elastic Managed LLM** — reasoning (zero-config, no external API key)
- **A2A Protocol** — JSON-RPC 2.0 agent-to-agent communication
- **Kibana Lens** — dashboard visualizations
- **Slack Incoming Webhooks** — Block Kit escalation notifications

## License

MIT — see [LICENSE](LICENSE)
