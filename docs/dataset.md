# Dataset Design

## Purpose
The dataset simulates real-world system incidents in a controlled and reproducible way.

---

## Log Schema

- @timestamp (datetime)
- service (keyword)
- level (INFO | WARN | ERROR)
- message (text)
- event.type (log | deploy | metric)
- latency_ms (integer)
- memory_mb (integer)
- request_id (keyword)

---

## Scenarios

### Scenario 1 – Normal Operation
Stable logs with no anomalies.

### Scenario 2 – Deployment-Induced Failure
A deployment event followed by increased latency and error spikes.

### Scenario 3 – Database Timeout
Gradual latency increase leading to timeout errors.

(Optional)
### Scenario 4 – Cascading Failure
One service failure triggering downstream errors.

---

## Generation Method
Python scripts generate JSON logs locally and ingest them into Elasticsearch Serverless via Bulk API using an API key.

### Ingestion Steps
1. Generate logs as JSON using Python
2. Create an API key from Kibana (Management > API Keys)
3. Push data to Elasticsearch Serverless endpoint via Bulk API
4. Verify data in Kibana Discover
