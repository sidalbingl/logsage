"""
LogSage - Elasticsearch Data Ingestion Script
===============================================
Reads logs from data/logs.json and sends them to Elasticsearch via Bulk API.
Configuration is read from .env file.
"""

import json
import os
import sys
import urllib.request
import urllib.error

# --- Load .env manually (no external dependencies needed) ---
def load_env(path=".env"):
    if not os.path.exists(path):
        print(f"ERROR: {path} file not found!")
        print(f"Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

load_env()

ES_URL = os.environ.get("ELASTICSEARCH_URL", "").rstrip("/")
API_KEY = os.environ.get("ELASTICSEARCH_API_KEY", "")
INDEX_NAME = "logsage-logs"
LOG_FILE = "data/logs.json"
BATCH_SIZE = 500  # Send 500 logs per bulk request


def check_config():
    if not ES_URL or "your-project" in ES_URL:
        print("ERROR: ELASTICSEARCH_URL is not set in .env")
        sys.exit(1)
    if not API_KEY or "your-encoded" in API_KEY:
        print("ERROR: ELASTICSEARCH_API_KEY is not set in .env")
        sys.exit(1)


def es_request(method, path, body=None):
    """Make a request to Elasticsearch."""
    url = f"{ES_URL}/{path}"
    headers = {
        "Authorization": f"ApiKey {API_KEY}",
        "Content-Type": "application/json",
    }
    data = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"HTTP {e.code}: {error_body}")
        return None


def create_index():
    """Create the index with proper mappings."""
    mapping = {
        "mappings": {
            "properties": {
                "@timestamp": {"type": "date"},
                "service": {"type": "keyword"},
                "level": {"type": "keyword"},
                "message": {"type": "text"},
                "event_type": {"type": "keyword"},
                "latency_ms": {"type": "integer"},
                "memory_mb": {"type": "integer"},
                "request_id": {"type": "keyword"},
            }
        }
    }

    # Delete index if exists
    print(f"Creating index '{INDEX_NAME}'...")
    es_request("DELETE", INDEX_NAME)
    result = es_request("PUT", INDEX_NAME, json.dumps(mapping))
    if result and result.get("acknowledged"):
        print(f"  Index '{INDEX_NAME}' created successfully.")
    else:
        print(f"  Failed to create index: {result}")
        sys.exit(1)


def ingest_logs():
    """Read logs from file and send to Elasticsearch via Bulk API."""
    if not os.path.exists(LOG_FILE):
        print(f"ERROR: {LOG_FILE} not found. Run generate_logs.py first.")
        sys.exit(1)

    # Read all logs
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        logs = [json.loads(line) for line in f if line.strip()]

    print(f"Ingesting {len(logs)} logs into '{INDEX_NAME}'...")

    # Send in batches
    total_sent = 0
    for i in range(0, len(logs), BATCH_SIZE):
        batch = logs[i:i + BATCH_SIZE]

        # Build bulk request body (NDJSON: action\ndata\n)
        bulk_body = ""
        for log in batch:
            bulk_body += json.dumps({"index": {"_index": INDEX_NAME}}) + "\n"
            bulk_body += json.dumps(log) + "\n"

        result = es_request("POST", "_bulk", bulk_body)
        if result and not result.get("errors"):
            total_sent += len(batch)
            print(f"  Sent {total_sent}/{len(logs)} logs...")
        else:
            errors = [item for item in result.get("items", []) if "error" in item.get("index", {})] if result else []
            print(f"  Batch error! {len(errors)} failed documents.")
            if errors:
                print(f"  First error: {errors[0]['index']['error']}")

    print(f"\nDone! {total_sent}/{len(logs)} logs ingested into '{INDEX_NAME}'.")


def verify():
    """Quick check: count documents in the index."""
    result = es_request("GET", f"{INDEX_NAME}/_count")
    if result:
        print(f"Verification: {result['count']} documents in '{INDEX_NAME}'.")


def main():
    check_config()
    create_index()
    ingest_logs()
    verify()


if __name__ == "__main__":
    main()
