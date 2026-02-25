"""
LogSage - Multi-Agent Orchestrator
====================================
Orchestrates 3 specialized agents in a 4-phase pipeline:
  1. Investigator  → detects anomalies and collects raw data
  2. Analyst       → correlates events and generates root cause hypothesis
  3. Validator     → validates the hypothesis and assigns confidence score
  4. Escalation    → if Verdict is CONFIRMED/PARTIALLY CONFIRMED and
                     confidence >= 70, writes to logsage-actions and
                     sends a Slack Block Kit notification

Final incident report is saved to Elasticsearch (logsage-incidents index).

Usage:
  py scripts/orchestrate.py
  py scripts/orchestrate.py --prompt "Investigate auth-service in the last 2 hours"
"""

import json
import os
import re
import sys
import uuid
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# --- Load .env ---
def load_env(path=".env"):
    if not os.path.exists(path):
        print(f"ERROR: {path} not found.")
        sys.exit(1)
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

load_env()

# Fix Windows terminal Unicode
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- Config ---
ES_URL      = os.environ.get("ELASTICSEARCH_URL", "").rstrip("/")
KIBANA_URL  = os.environ.get("KIBANA_URL", "").rstrip("/")
API_KEY     = os.environ.get("ELASTICSEARCH_API_KEY", "")

AGENT_INVESTIGATOR  = "logsage"
AGENT_ANALYST       = "logsage_analyst"
AGENT_VALIDATOR     = "logsage_validator"
INCIDENTS_INDEX     = "logsage-incidents"
ACTIONS_INDEX       = "logsage-actions"
CASE_MIN_CONFIDENCE = 70  # auto-escalate when confidence >= this

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # Discord or Slack webhook

DEFAULT_PROMPT = (
    "Investigate the system logs. "
    "Check for anomalies, errors, and performance degradation across all services "
    "in the last 7 days. Identify any incidents that require attention."
)


# --- HTTP helpers ---
def kibana_request(method, path, body=None):
    """Make a request to Kibana API."""
    url = f"{KIBANA_URL}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"ApiKey {API_KEY}",
        "Content-Type": "application/json",
        "kbn-xsrf": "true",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return {"error": error_body, "status": e.code}, e.code


def es_request(method, path, body=None, silent_codes=()):
    """Make a request to Elasticsearch API."""
    url = f"{ES_URL}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"ApiKey {API_KEY}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code not in silent_codes:
            error_body = e.read().decode("utf-8")
            print(f"  ES HTTP {e.code}: {error_body[:200]}")
        return None


# --- Agent call ---
def call_agent(agent_id, message, retries=5):
    """
    Call an Agent Builder agent via A2A endpoint using JSON-RPC 2.0 format.
    Retries on 502/503 errors with exponential backoff.
    """
    print(f"  Calling agent '{agent_id}'...")

    last_error = None
    backoff = [0, 15, 30, 60, 60]  # seconds to wait before each attempt
    for attempt in range(1, retries + 1):
        if attempt > 1:
            wait = backoff[min(attempt - 1, len(backoff) - 1)]
            print(f"  Retry {attempt}/{retries} (waiting {wait}s)...")
            time.sleep(wait)

        task_id = str(uuid.uuid4())
        body = {
            "jsonrpc": "2.0",
            "id": task_id,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": task_id,
                    "role": "user",
                    "parts": [
                        {"kind": "text", "text": message}
                    ]
                }
            }
        }

        result, status = kibana_request(
            "POST",
            f"/api/agent_builder/a2a/{agent_id}",
            body
        )

        if status in (502, 503):
            last_error = f"HTTP {status}"
            continue

        if status != 200:
            print(f"  ERROR: Agent '{agent_id}' call failed (status {status})")
            print(f"  Response: {json.dumps(result)[:300]}")
            return None

        if "error" in result:
            print(f"  JSON-RPC error: {result['error']}")
            return None

        # Extract response text
        # Response: {"result": {"kind": "message", "parts": [{"kind": "text", "text": "..."}]}}
        try:
            rpc_result = result.get("result", {})
            parts = rpc_result.get("parts", [])
            if parts:
                texts = [p.get("text", "") for p in parts if p.get("kind") == "text" or p.get("type") == "text"]
                if texts:
                    return "\n".join(texts)
            artifacts = rpc_result.get("artifacts", [])
            if artifacts:
                artifact_parts = artifacts[0].get("parts", [])
                if artifact_parts:
                    return artifact_parts[0].get("text", json.dumps(rpc_result))
            return json.dumps(rpc_result)
        except Exception:
            return json.dumps(result)

    print(f"  ERROR: Agent '{agent_id}' failed after {retries} retries. Last error: {last_error}")
    return None


# --- Parse verdict and confidence score from validation text ---
def parse_validation(text):
    verdict = "UNKNOWN"
    confidence = None

    # Match: Verdict: CONFIRMED / PARTIALLY CONFIRMED / UNCONFIRMED
    m = re.search(r"Verdict[:\*\s]+\**\s*(CONFIRMED|PARTIALLY CONFIRMED|UNCONFIRMED)\**", text, re.IGNORECASE)
    if m:
        verdict = m.group(1).upper()

    # Match: Confidence Score: 75/100 or Confidence Score: 75
    m = re.search(r"Confidence Score[:\*\s]+\**\s*(\d+)\s*(?:/\s*100)?\**", text, re.IGNORECASE)
    if m:
        confidence = int(m.group(1))

    return verdict, confidence


# --- Save incident to Elasticsearch ---
def save_incident(incident_data):
    """Index the incident report into logsage-incidents."""
    result = es_request("POST", f"{INCIDENTS_INDEX}/_doc", incident_data)
    if result and result.get("result") in ("created", "updated"):
        return result.get("_id", "unknown")
    return None


def send_webhook(incident_id, verdict, confidence_score, investigation, analysis, recommendation):
    """
    Send a rich escalation notification to Discord or Slack webhook.
    Includes root cause, affected services, and recommendation so on-call
    engineers can act without opening the dashboard.
    No-op if WEBHOOK_URL is not set.
    """
    if not WEBHOOK_URL:
        return

    severity  = "CRITICAL" if confidence_score >= 85 else "HIGH"
    color     = 0xFF0000   if confidence_score >= 85 else 0xFF8C00

    # Extract root cause (first sentence / line of analysis)
    root_cause = ""
    for line in analysis.splitlines():
        line = line.strip().lstrip("#* ")
        if len(line) > 30:
            root_cause = line[:200]
            break
    if not root_cause:
        root_cause = analysis[:200]

    # Extract affected services summary from investigation (lines with error counts)
    affected = []
    for line in investigation.splitlines():
        if any(svc in line for svc in ["auth-service", "payment-service", "api-gateway",
                                        "user-service", "notification-service"]):
            clean = line.strip().lstrip("| *#-").strip()
            if clean and len(clean) > 10:
                affected.append(clean[:80])
        if len(affected) >= 4:
            break
    affected_text = "\n".join(f"• {a}" for a in affected) if affected else "_See dashboard for details_"

    dashboard_url = f"{KIBANA_URL}/app/dashboards#/view/logsage-dashboard-001"

    if "discord.com" in WEBHOOK_URL:
        payload = {
            "embeds": [{
                "title": f"\U0001f6a8 LogSage Alert — {incident_id}",
                "color": color,
                "fields": [
                    {"name": "Verdict",           "value": verdict,                   "inline": True},
                    {"name": "Confidence",         "value": f"{confidence_score}/100", "inline": True},
                    {"name": "Severity",           "value": severity,                  "inline": True},
                    {"name": "\U0001f4cd Root Cause",        "value": root_cause[:300],          "inline": False},
                    {"name": "\u26a0\ufe0f Affected Services", "value": affected_text[:400],   "inline": False},
                    {"name": "\U0001f4a1 Recommendation",  "value": recommendation[:300],      "inline": False},
                    {"name": "\U0001f4ca Dashboard",        "value": dashboard_url,             "inline": False},
                ],
                "footer": {"text": "LogSage Multi-Agent Orchestrator"},
            }]
        }
    else:
        # Slack Block Kit — colored attachment + rich blocks
        color = "#E01E5A" if confidence_score >= 85 else "#E8A020"  # red / orange (hex for Slack)
        ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        payload = {
            "text": f"[{severity}] LogSage Alert — {incident_id} | {verdict} ({confidence_score}/100)",
            "attachments": [
                {
                    "color": color,
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": f"\U0001f6a8 [{severity}] Incident Detected \u2014 {incident_id}"
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Verdict*\n`{verdict}`"},
                                {"type": "mrkdwn", "text": f"*Confidence*\n`{confidence_score}/100`"},
                                {"type": "mrkdwn", "text": f"*Severity*\n`{severity}`"},
                                {"type": "mrkdwn", "text": f"*Detected At*\n`{ts_str}`"},
                            ]
                        },
                        {"type": "divider"},
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f":mag: *Root Cause*\n{root_cause}"}
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f":warning: *Affected Services*\n{affected_text}"}
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f":bulb: *Recommendation*\n{recommendation[:400]}"}
                        },
                        {"type": "divider"},
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":bar_chart: *<{dashboard_url}|View LogSage Dashboard \u2192>*"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": (
                                        f"*LogSage Multi-Agent Orchestrator* "
                                        f"\u00b7 {incident_id} "
                                        f"\u00b7 {ts_str}"
                                    )
                                }
                            ]
                        },
                    ]
                }
            ]
        }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL, data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print(f"  Webhook notification sent.")
    except Exception as e:
        print(f"  WARNING: Webhook failed: {e}")


def create_action_record(incident_id, verdict, confidence_score, validation):
    """
    Write an escalation action record to logsage-actions index.
    Triggered when verdict is CONFIRMED or PARTIALLY CONFIRMED and confidence >= CASE_MIN_CONFIDENCE.
    Returns action_id or None on failure.
    """
    severity = "critical" if confidence_score >= 85 else "high"
    # Extract a short recommendation from validation text (first 300 chars after "Recommendation")
    rec_match = re.search(r"(?:Recommendation|recommend)[:\s]+(.+)", validation, re.IGNORECASE | re.DOTALL)
    recommendation = rec_match.group(1).strip()[:300] if rec_match else "Immediate investigation required."

    action = {
        "@timestamp":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "incident_id":     incident_id,
        "action_type":     "escalate",
        "verdict":         verdict,
        "confidence_score": confidence_score,
        "severity":        severity,
        "recommendation":  recommendation,
        "triggered_by":    "logsage-orchestrator",
        "message":         (
            f"Incident {incident_id} automatically escalated by LogSage. "
            f"Verdict: {verdict} | Confidence: {confidence_score}/100"
        ),
    }

    result = es_request("POST", f"{ACTIONS_INDEX}/_doc", action)
    if result and result.get("result") in ("created", "updated"):
        return result.get("_id", "unknown")
    return None


def ensure_actions_index():
    """Create logsage-actions index if it doesn't exist."""
    mapping = {
        "mappings": {
            "properties": {
                "@timestamp":      {"type": "date"},
                "incident_id":     {"type": "keyword"},
                "action_type":     {"type": "keyword"},
                "verdict":         {"type": "keyword"},
                "confidence_score": {"type": "integer"},
                "severity":        {"type": "keyword"},
                "recommendation":  {"type": "text"},
                "triggered_by":    {"type": "keyword"},
                "message":         {"type": "text"},
            }
        }
    }
    es_request("PUT", ACTIONS_INDEX, mapping, silent_codes=(400,))


def ensure_incidents_index():
    """Create logsage-incidents index if it doesn't exist."""
    mapping = {
        "mappings": {
            "properties": {
                "@timestamp":          {"type": "date"},
                "incident_id":         {"type": "keyword"},
                "status":              {"type": "keyword"},
                "prompt":              {"type": "text"},
                "investigation":       {"type": "text"},
                "analysis":            {"type": "text"},
                "validation":          {"type": "text"},
                "confidence_score":    {"type": "integer"},
                "verdict":             {"type": "keyword"},
                "action_id":           {"type": "keyword"},
            }
        }
    }
    # PUT with ignore_already_exists logic
    result = es_request("PUT", INCIDENTS_INDEX, mapping, silent_codes=(400,))
    if result and result.get("acknowledged"):
        print(f"  Index '{INCIDENTS_INDEX}' created.")


# --- Main orchestration ---
def run(prompt):
    incident_id = f"INC-{uuid.uuid4().hex[:6].upper()}"
    print(f"\n{'='*60}")
    print(f"LogSage Incident Investigation")
    print(f"Incident ID : {incident_id}")
    print(f"Prompt      : {prompt}")
    print(f"{'='*60}\n")

    # --- Phase 1: Investigate ---
    print("[1/4] INVESTIGATOR AGENT — Detecting anomalies...")
    investigator_prompt = (
        f"{prompt}\n\n"
        "Use your tools to detect anomalies and retrieve relevant logs. "
        "Report: affected services, time range, error counts, and key log messages. "
        "Be specific and data-driven."
    )
    investigation = call_agent(AGENT_INVESTIGATOR, investigator_prompt)
    if not investigation:
        print("FAILED: Investigator agent did not respond.")
        sys.exit(1)
    print(f"\n  Investigation complete. ({len(investigation)} chars)\n")

    # --- Phase 2: Analyze ---
    print("[2/4] ANALYST AGENT — Generating root cause hypothesis...")
    # Trim investigation to avoid LLM gateway timeout
    inv_trimmed = investigation[:600] + "..." if len(investigation) > 600 else investigation
    analyst_prompt = (
        "Analyze the root cause based on these investigation findings:\n\n"
        f"{inv_trimmed}\n\n"
        "Use correlate_events and get_service_metrics tools. "
        "Reply with: Root Cause, Evidence (3 bullet points), Failure Sequence."
    )
    analysis = call_agent(AGENT_ANALYST, analyst_prompt)
    if not analysis:
        print("  WARNING: Analyst agent did not respond. Saving partial report.")
        analysis = "[ANALYST UNAVAILABLE — skipped due to agent error]"
    else:
        print(f"\n  Analysis complete. ({len(analysis)} chars)\n")

    # --- Phase 3: Validate ---
    print("[3/4] VALIDATOR AGENT — Validating hypothesis...")
    # Trim to avoid timeout — keep only first 800 chars of each phase
    inv_summary = investigation[:800] + "..." if len(investigation) > 800 else investigation
    ana_summary = analysis[:800] + "..." if len(analysis) > 800 else analysis
    validator_prompt = (
        "Validate the following incident analysis using your tools. Re-query data independently.\n\n"
        f"INVESTIGATION SUMMARY:\n{inv_summary}\n\n"
        f"ANALYSIS SUMMARY:\n{ana_summary}\n\n"
        "Assign: Verdict (CONFIRMED/PARTIALLY CONFIRMED/UNCONFIRMED), "
        "Confidence Score (0-100), and Final Recommendation."
    )
    validation = call_agent(AGENT_VALIDATOR, validator_prompt)
    if not validation:
        print("  WARNING: Validator agent did not respond. Saving partial report.")
        validation = "[VALIDATOR UNAVAILABLE — skipped due to agent error]"
    else:
        print(f"\n  Validation complete. ({len(validation)} chars)\n")

    # Determine report completeness
    analyst_ok  = not analysis.startswith("[ANALYST")
    validator_ok = not validation.startswith("[VALIDATOR")
    if analyst_ok and validator_ok:
        report_status = "complete"
    elif analyst_ok or validator_ok:
        report_status = "partial"
    else:
        report_status = "investigation_only"

    # --- Parse verdict + confidence from validation ---
    verdict, confidence_score = parse_validation(validation)
    print(f"  Verdict: {verdict} | Confidence: {confidence_score}")

    # --- Phase 4: Auto-escalate if confirmed and high confidence ---
    action_id = None
    action_taken = False
    should_escalate = (
        verdict in ("CONFIRMED", "PARTIALLY CONFIRMED")
        and confidence_score is not None
        and confidence_score >= CASE_MIN_CONFIDENCE
    )
    if should_escalate:
        print(f"\n[4/4] ACTION — Escalating incident (verdict={verdict}, confidence={confidence_score})...")
        ensure_actions_index()
        action_id = create_action_record(incident_id, verdict, confidence_score, validation)
        if action_id:
            action_taken = True
            print(f"  Escalation record saved: {ACTIONS_INDEX}/{action_id}")
            # Extract recommendation for webhook
            rec_match = re.search(r"(?:Recommendation|recommend)[:\s]+(.+)", validation, re.IGNORECASE | re.DOTALL)
            recommendation = rec_match.group(1).strip()[:400] if rec_match else "Immediate investigation required."
            send_webhook(incident_id, verdict, confidence_score, investigation, analysis, recommendation)
        else:
            print("  WARNING: Could not save escalation record.")
    else:
        reason = (
            f"verdict={verdict}" if verdict == "UNCONFIRMED"
            else f"confidence={confidence_score} < {CASE_MIN_CONFIDENCE}"
        )
        print(f"\n[4/4] ACTION — Skipped escalation ({reason}).")

    # --- Save to Elasticsearch ---
    print("[+] Saving incident report to Elasticsearch...")
    ensure_incidents_index()

    incident = {
        "@timestamp":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "incident_id":      incident_id,
        "status":           report_status,
        "verdict":          verdict,
        "confidence_score": confidence_score,
        "prompt":           prompt,
        "investigation":    investigation,
        "analysis":         analysis,
        "validation":       validation,
        "action_id":        action_id,
    }
    doc_id = save_incident(incident)

    # --- Final Report ---
    print(f"\n{'='*60}")
    print(f"LOGSAGE INCIDENT REPORT — {incident_id}")
    print(f"{'='*60}")
    print(f"\n[INVESTIGATION]\n{investigation}\n")
    print(f"[ANALYSIS]\n{analysis}\n")
    print(f"[VALIDATION]\n{validation}\n")
    if action_taken:
        print(f"[ACTION] Incident escalated → {ACTIONS_INDEX}/{action_id}")
    else:
        print(f"[ACTION] No escalation (threshold not met).")
    if doc_id:
        print(f"Incident saved to Elasticsearch: {INCIDENTS_INDEX}/{doc_id}")
    else:
        print("WARNING: Could not save incident to Elasticsearch.")
    print(f"Report status: {report_status.upper()}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    # Allow custom prompt via command line
    if len(sys.argv) > 1 and sys.argv[1] == "--prompt":
        user_prompt = " ".join(sys.argv[2:])
    else:
        user_prompt = DEFAULT_PROMPT

    run(user_prompt)
