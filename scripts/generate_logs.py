"""
LogSage - Synthetic Log Generator
==================================
Generates realistic system logs for 4 incident scenarios.
Output: data/logs.json (one JSON object per line - NDJSON format)
"""

import json
import random
import uuid
from datetime import datetime, timedelta, timezone

# --- Configuration ---
OUTPUT_FILE = "data/logs.json"
SERVICES = ["auth-service", "api-gateway", "payment-service", "user-service", "notification-service"]
# Start 6 days ago so 4 scenarios spread across the last 7 days
BASE_TIME = (datetime.now(timezone.utc) - timedelta(days=6)).replace(hour=8, minute=0, second=0, microsecond=0).replace(tzinfo=None)

# Realistic log messages per level
MESSAGES = {
    "INFO": [
        "Request processed successfully",
        "Health check passed",
        "Cache hit for user session",
        "Connection pool initialized",
        "Scheduled task completed",
        "Configuration reloaded",
    ],
    "WARN": [
        "Slow query detected",
        "Connection pool running low",
        "Retry attempt for external call",
        "Memory usage above 80%",
        "Rate limit approaching threshold",
    ],
    "ERROR": [
        "Connection timeout to database",
        "Failed to authenticate user",
        "Internal server error",
        "Service unavailable",
        "Out of memory exception",
        "Unhandled exception in request handler",
    ],
}


def make_log(timestamp, service, level, message=None, event_type="log", latency_ms=None, memory_mb=None):
    """Create a single log entry."""
    if message is None:
        message = random.choice(MESSAGES[level])
    if latency_ms is None:
        latency_ms = random.randint(10, 150) if level == "INFO" else random.randint(200, 800)
    if memory_mb is None:
        memory_mb = random.randint(200, 400) if level != "ERROR" else random.randint(450, 700)

    return {
        "@timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "service": service,
        "level": level,
        "message": message,
        "event_type": event_type,
        "latency_ms": latency_ms,
        "memory_mb": memory_mb,
        "request_id": f"req-{uuid.uuid4().hex[:8]}",
    }


def scenario_normal(start_time, duration_minutes=60):
    """Scenario 1: Normal operation - no anomalies."""
    logs = []
    current = start_time
    end = start_time + timedelta(minutes=duration_minutes)

    while current < end:
        service = random.choice(SERVICES)
        # Normal: 90% INFO, 8% WARN, 2% ERROR
        level = random.choices(["INFO", "WARN", "ERROR"], weights=[90, 8, 2])[0]
        logs.append(make_log(current, service, level))
        current += timedelta(seconds=random.randint(2, 15))

    return logs


def scenario_deployment_failure(start_time, duration_minutes=60):
    """
    Scenario 2: Deployment-induced failure.
    - First 20 min: normal
    - Min 20: deployment event
    - After deployment: error rate spikes on the deployed service
    """
    logs = []
    current = start_time
    end = start_time + timedelta(minutes=duration_minutes)
    deploy_time = start_time + timedelta(minutes=20)
    target_service = "payment-service"

    while current < end:
        if current >= deploy_time:
            # Deployment event marker
            if current == deploy_time:
                logs.append(make_log(
                    current, target_service, "INFO",
                    message=f"Deployment started: {target_service} v2.4.1",
                    event_type="deploy",
                ))

            # After deploy: payment-service has high error rate
            if random.random() < 0.5:
                service = target_service
                level = random.choices(["INFO", "WARN", "ERROR"], weights=[20, 25, 55])[0]
                latency = random.randint(800, 5000) if level == "ERROR" else random.randint(200, 600)
            else:
                service = random.choice(SERVICES)
                level = random.choices(["INFO", "WARN", "ERROR"], weights=[85, 10, 5])[0]
                latency = None
            logs.append(make_log(current, service, level, latency_ms=latency))
        else:
            # Before deploy: normal
            service = random.choice(SERVICES)
            level = random.choices(["INFO", "WARN", "ERROR"], weights=[90, 8, 2])[0]
            logs.append(make_log(current, service, level))

        current += timedelta(seconds=random.randint(2, 10))

    return logs


def scenario_db_timeout(start_time, duration_minutes=60):
    """
    Scenario 3: Database timeout - gradual degradation.
    - Latency increases over time for auth-service
    - Eventually leads to timeout errors
    """
    logs = []
    current = start_time
    end = start_time + timedelta(minutes=duration_minutes)
    target_service = "auth-service"

    while current < end:
        elapsed = (current - start_time).total_seconds() / 60  # minutes elapsed
        degradation = min(elapsed / duration_minutes, 1.0)  # 0.0 → 1.0

        if random.random() < 0.4:
            service = target_service
            base_latency = int(100 + degradation * 4900)  # 100ms → 5000ms
            latency = base_latency + random.randint(-50, 200)

            if degradation > 0.7:
                level = random.choices(["WARN", "ERROR"], weights=[30, 70])[0]
                message = "Connection timeout to database" if level == "ERROR" else "Slow query detected"
            elif degradation > 0.4:
                level = random.choices(["INFO", "WARN", "ERROR"], weights=[40, 40, 20])[0]
                message = None
            else:
                level = "INFO"
                message = None

            logs.append(make_log(current, service, level, message=message, latency_ms=latency))
        else:
            service = random.choice(SERVICES)
            level = random.choices(["INFO", "WARN", "ERROR"], weights=[90, 8, 2])[0]
            logs.append(make_log(current, service, level))

        current += timedelta(seconds=random.randint(2, 10))

    return logs


def scenario_cascading_failure(start_time, duration_minutes=60):
    """
    Scenario 4: Cascading failure.
    - auth-service fails first
    - api-gateway starts failing because it depends on auth
    - payment-service and user-service follow
    """
    logs = []
    current = start_time
    end = start_time + timedelta(minutes=duration_minutes)

    # Each service starts failing at a different time (cascade)
    cascade_timeline = {
        "auth-service": start_time + timedelta(minutes=15),
        "api-gateway": start_time + timedelta(minutes=22),
        "user-service": start_time + timedelta(minutes=28),
        "payment-service": start_time + timedelta(minutes=33),
    }

    while current < end:
        service = random.choice(SERVICES)
        fail_time = cascade_timeline.get(service)

        if fail_time and current >= fail_time:
            # This service is in failure mode
            minutes_since_fail = (current - fail_time).total_seconds() / 60
            error_weight = min(20 + minutes_since_fail * 5, 70)
            level = random.choices(
                ["INFO", "WARN", "ERROR"],
                weights=[max(100 - error_weight * 2, 5), 25, error_weight],
            )[0]
            latency = random.randint(1000, 8000) if level == "ERROR" else random.randint(300, 1500)

            if service == "auth-service" and level == "ERROR":
                message = "Connection timeout to database"
            elif level == "ERROR":
                message = f"Upstream dependency failed: auth-service"
            else:
                message = None

            logs.append(make_log(current, service, level, message=message, latency_ms=latency))
        else:
            # Normal operation
            level = random.choices(["INFO", "WARN", "ERROR"], weights=[90, 8, 2])[0]
            logs.append(make_log(current, service, level))

        current += timedelta(seconds=random.randint(2, 10))

    return logs


def main():
    all_logs = []

    # Generate each scenario 2 days apart so they spread across the last 7 days
    print("Generating Scenario 1: Normal Operation...")
    all_logs += scenario_normal(BASE_TIME)

    print("Generating Scenario 2: Deployment Failure...")
    all_logs += scenario_deployment_failure(BASE_TIME + timedelta(days=2))

    print("Generating Scenario 3: Database Timeout...")
    all_logs += scenario_db_timeout(BASE_TIME + timedelta(days=4))

    print("Generating Scenario 4: Cascading Failure...")
    all_logs += scenario_cascading_failure(BASE_TIME + timedelta(days=6))

    # Sort by timestamp
    all_logs.sort(key=lambda x: x["@timestamp"])

    # Write as NDJSON (one JSON per line - Elasticsearch bulk format friendly)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for log in all_logs:
            f.write(json.dumps(log) + "\n")

    print(f"\nDone! Generated {len(all_logs)} log entries -> {OUTPUT_FILE}")
    print(f"  Scenario 1 (Normal):     {BASE_TIME.strftime('%H:%M')} - {(BASE_TIME + timedelta(hours=1)).strftime('%H:%M')}")
    print(f"  Scenario 2 (Deploy):     {(BASE_TIME + timedelta(hours=2)).strftime('%H:%M')} - {(BASE_TIME + timedelta(hours=3)).strftime('%H:%M')}")
    print(f"  Scenario 3 (DB Timeout): {(BASE_TIME + timedelta(hours=4)).strftime('%H:%M')} - {(BASE_TIME + timedelta(hours=5)).strftime('%H:%M')}")
    print(f"  Scenario 4 (Cascade):    {(BASE_TIME + timedelta(hours=6)).strftime('%H:%M')} - {(BASE_TIME + timedelta(hours=7)).strftime('%H:%M')}")


if __name__ == "__main__":
    main()
