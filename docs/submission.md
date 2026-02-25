# LogSage — Hackathon Submission

## Description (~400 words)

**LogSage — Multi-Agent Incident Intelligence**

Modern distributed systems generate thousands of log entries per second, burying critical incidents in noise. On-call engineers spend hours manually sifting through dashboards, correlating events across services, and deciding whether an alert is a real incident or a false positive — time that should be spent fixing, not finding.

LogSage automates the entire detection-to-escalation pipeline using three specialized AI agents orchestrated via the Elastic Agent Builder's A2A (Agent-to-Agent) protocol.

**How It Works**

LogSage runs a four-phase pipeline triggered on demand:

1. **Investigator Agent** queries Elasticsearch using ES|QL tools to detect error spikes and latency anomalies across all microservices. It identifies the affected time window and collects raw log evidence.

2. **Analyst Agent** receives the investigation findings and uses correlation and metric tools to build a root cause hypothesis — linking events across services by request ID and establishing a failure sequence.

3. **Validator Agent** independently re-queries the data to verify or challenge the analyst's hypothesis, then assigns a Verdict (CONFIRMED / PARTIALLY CONFIRMED / UNCONFIRMED) and a Confidence Score from 0–100.

4. **Auto-Escalation** fires when a confirmed incident reaches confidence ≥ 70. The orchestrator writes an audit record to Elasticsearch and sends a rich Slack notification (Block Kit) with root cause, affected services, recommendation, and a direct link to the Kibana dashboard — so engineers can act without opening a single tab.

The pipeline is driven by a Python orchestrator that calls each agent sequentially via A2A JSON-RPC 2.0, handles exponential backoff for transient failures, and persists every incident report for historical analysis. A six-panel Kibana dashboard covers the full picture: error timelines, per-service breakdown, latency trends, log distribution, incident history, and action audit trail.

**Elastic Features Used**

- **Agent Builder** — three purpose-built agents with dedicated ES|QL and Search tools
- **A2A Protocol** — agents communicate as independent services, enabling true multi-agent chaining
- **Elastic Managed LLM** — zero-config reasoning, no external API keys or quotas
- **ES|QL** — time-series anomaly detection, event correlation, and metric aggregation
- **Kibana Lens** — auto-generated six-panel observability dashboard

**What We Liked**

The Elastic Managed LLM made iteration extremely fast — no token budgets, key rotation, or provider rate limits. ES|QL's aggregation syntax handled time-series queries that would require complex multi-stage pipelines in other systems.

**Challenges**

The A2A endpoint occasionally returned 502/503 under load, requiring retry logic with exponential backoff. The Kibana Cases API is not available on Elasticsearch Serverless (only Security/Observability project types), which led us to build a custom `logsage-actions` index as a more flexible and queryable audit trail.

---

## Checklist

- [ ] Devpost submission form dolduruldu
- [ ] GitHub repo public yapıldı + OSI lisansı eklendi (örn. MIT)
- [ ] ~3 dakika demo video kaydedildi ve yüklendi
- [ ] (Bonus) X/Twitter veya LinkedIn'de paylaşım yapıldı, @elastic_devs tag'lendi

---

## Demo Video Script (3 min)

**0:00–0:20** — Problem: Log yığını, alert yorgunluğu, manuel triage

**0:20–0:50** — Kibana Dashboard turu: 6 panel, logsage-logs verileri

**0:50–1:30** — `py scripts/orchestrate.py` çalıştır, terminali göster:
- Phase 1/4 → 2/4 → 3/4 → 4/4
- Verdict: CONFIRMED, Confidence: XX/100
- Slack notification sent

**1:30–2:00** — Slack'te gelen Block Kit mesajını göster:
- Renkli kenar, 4-field grid, root cause, affected services, recommendation, dashboard linki

**2:00–2:30** — Kibana Dashboard'a dön:
- Recent Incidents tablosunda yeni INC-XXXXXX
- Actions Taken tablosunda otomatik aksiyon kaydı

**2:30–3:00** — Özet: 3 agent + orchestrator + Slack = sıfır manuel müdahale ile incident triage
