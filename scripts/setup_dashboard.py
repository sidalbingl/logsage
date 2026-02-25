"""
LogSage - Kibana Dashboard Setup Script
========================================
Creates Data Views, Lens Visualizations, and a Dashboard in Kibana.
Compatible with Kibana Serverless (uses lens type, DELETE+POST overwrite).

Usage:
  py scripts/setup_dashboard.py
"""

import json
import os
import sys
import urllib.request
import urllib.error

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

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KIBANA_URL = os.environ.get("KIBANA_URL", "").rstrip("/")
API_KEY    = os.environ.get("ELASTICSEARCH_API_KEY", "")


# --- HTTP helper ---
def kibana(method, path, body=None):
    url = f"{KIBANA_URL}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"ApiKey {API_KEY}",
        "Content-Type": "application/json",
        "kbn-xsrf": "true",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return {"error": error_body}, e.code


# --- Bulk import saved objects via import API ---
def import_objects(objects):
    """POST /api/saved_objects/_import  — the ONLY working endpoint in Serverless."""
    ndjson_bytes = ("\n".join(json.dumps(o) for o in objects) + "\n").encode("utf-8")

    boundary = "logsageboundary42"
    part = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="logsage.ndjson"\r\n'
        f"Content-Type: application/ndjson\r\n"
        f"\r\n"
    ).encode("utf-8")
    body = part + ndjson_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    url = f"{KIBANA_URL}/api/saved_objects/_import?overwrite=true"
    headers = {
        "Authorization": f"ApiKey {API_KEY}",
        "kbn-xsrf": "true",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8")}, e.code


# --- 1. Create Data Views ---
def create_data_views():
    print("\n[1/3] Creating Data Views...")
    views = [
        {"name": "LogSage Logs",      "title": "logsage-logs",      "timeField": "@timestamp"},
        {"name": "LogSage Incidents", "title": "logsage-incidents", "timeField": "@timestamp"},
        {"name": "LogSage Actions",   "title": "logsage-actions",   "timeField": "@timestamp"},
    ]
    ids = {}
    for v in views:
        body = {"data_view": {"title": v["title"], "timeFieldName": v["timeField"], "name": v["name"]}}
        result, status = kibana("POST", "/api/data_views/data_view", body)
        if status in (200, 201):
            dv_id = result.get("data_view", {}).get("id", "")
            ids[v["title"]] = dv_id
            print(f"  [OK] '{v['name']}' -> {dv_id}")
        else:
            all_views, _ = kibana("GET", "/api/data_views")
            for dv in all_views.get("data_view", []):
                if dv.get("title") == v["title"]:
                    ids[v["title"]] = dv.get("id", "")
                    print(f"  [--] '{v['name']}' already exists -> {ids[v['title']]}")
                    break
    return ids


# --- Lens state builders ---

def _base_layer(col_order, columns):
    """Build a formBased Lens layer."""
    return {
        "columnOrder": col_order,
        "columns": columns,
        "incompleteColumns": {},
        "sampling": 1,
    }


def lens_xy(title, chart_type, x_field, y_op, dv_id, kuery="", y_field=None, color=None):
    """XY chart (bar / line)."""
    x_is_date = x_field == "@timestamp"
    x_col = {
        "dataType": "date" if x_is_date else "string",
        "isBucketed": True,
        "label": x_field,
        "operationType": "date_histogram" if x_is_date else "terms",
        "params": (
            {"interval": "auto", "includeEmptyRows": True}
            if x_is_date else
            {"orderBy": {"columnId": "col_y", "type": "column"},
             "orderDirection": "desc", "size": 10}
        ),
        "scale": "interval" if x_is_date else "ordinal",
        "sourceField": x_field,
    }
    op = "average" if y_op == "avg" else y_op
    y_col = {
        "dataType": "number",
        "isBucketed": False,
        "label": "Count" if y_op == "count" else f"Avg {y_field}",
        "operationType": op,
        "scale": "ratio",
        "sourceField": "___records___" if y_op == "count" else y_field,
    }
    if op == "average":
        y_col["params"] = {}
    if kuery and y_op == "count":
        y_col["filter"] = {"query": kuery, "language": "kuery"}

    y_cfg = [{"forAccessor": "col_y"}]
    if color:
        y_cfg[0]["color"] = color

    state = {
        "datasourceStates": {
            "formBased": {
                "layers": {
                    "layer1": _base_layer(["col_x", "col_y"], {"col_x": x_col, "col_y": y_col})
                }
            },
            "textBased": {"layers": {}},
        },
        "adHocDataViews": {},
        "internalReferences": [],
        "visualization": {
            "axisTitlesVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
            "fittingFunction": "None",
            "gridlinesVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
            "layers": [{
                "accessors": ["col_y"],
                "layerId": "layer1",
                "layerType": "data",
                "seriesType": chart_type,
                "xAccessor": "col_x",
                "yConfig": y_cfg,
            }],
            "legend": {"isVisible": True, "position": "right"},
            "preferredSeriesType": chart_type,
            "tickLabelsVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
            "valueLabels": "hide",
        },
        "query": {"language": "kuery", "query": ""},
        "filters": [],
    }
    return {
        "attributes": {"title": title, "visualizationType": "lnsXY", "state": state, "description": ""},
        "references": [{"id": dv_id, "name": "indexpattern-datasource-layer-layer1", "type": "index-pattern"}],
    }


def lens_pie(title, group_field, dv_id):
    """Donut / pie chart."""
    group_col = {
        "dataType": "string",
        "isBucketed": True,
        "label": group_field,
        "operationType": "terms",
        "params": {"orderBy": {"columnId": "col_count", "type": "column"}, "orderDirection": "desc", "size": 5},
        "scale": "ordinal",
        "sourceField": group_field,
    }
    count_col = {
        "dataType": "number",
        "isBucketed": False,
        "label": "Count",
        "operationType": "count",
        "scale": "ratio",
        "sourceField": "___records___",
    }
    state = {
        "datasourceStates": {
            "formBased": {
                "layers": {
                    "layer1": _base_layer(["col_group", "col_count"], {"col_group": group_col, "col_count": count_col})
                }
            },
            "textBased": {"layers": {}},
        },
        "adHocDataViews": {},
        "internalReferences": [],
        "visualization": {
            "layers": [{
                "layerId": "layer1",
                "layerType": "data",
                "metrics": ["col_count"],
                "primaryGroups": ["col_group"],
                "shape": "donut",
                "numberDisplay": "percent",
                "categoryDisplay": "default",
                "legendDisplay": "default",
            }],
            "shape": "donut",
        },
        "query": {"language": "kuery", "query": ""},
        "filters": [],
    }
    return {
        "attributes": {"title": title, "visualizationType": "lnsPie", "state": state, "description": ""},
        "references": [{"id": dv_id, "name": "indexpattern-datasource-layer-layer1", "type": "index-pattern"}],
    }


def lens_metric(title, label, dv_id, kuery=""):
    """Single metric (big number)."""
    count_col = {
        "dataType": "number",
        "isBucketed": False,
        "label": label,
        "operationType": "count",
        "scale": "ratio",
        "sourceField": "___records___",
    }
    if kuery:
        count_col["filter"] = {"query": kuery, "language": "kuery"}

    state = {
        "datasourceStates": {
            "formBased": {
                "layers": {
                    "layer1": _base_layer(["col_count"], {"col_count": count_col})
                }
            },
            "textBased": {"layers": {}},
        },
        "adHocDataViews": {},
        "internalReferences": [],
        "visualization": {
            "layerId": "layer1",
            "layerType": "data",
            "metricAccessor": "col_count",
        },
        "query": {"language": "kuery", "query": ""},
        "filters": [],
    }
    return {
        "attributes": {"title": title, "visualizationType": "lnsMetric", "state": state, "description": ""},
        "references": [{"id": dv_id, "name": "indexpattern-datasource-layer-layer1", "type": "index-pattern"}],
    }


def lens_datatable(title, dv_id):
    """Datatable showing recent incidents with verdict and confidence."""
    state = {
        "datasourceStates": {
            "formBased": {
                "layers": {
                    "layer1": {
                        "columnOrder": ["col_id", "col_verdict", "col_score", "col_status"],
                        "columns": {
                            "col_id": {
                                "dataType": "string",
                                "isBucketed": True,
                                "label": "Incident ID",
                                "operationType": "terms",
                                "params": {"orderBy": {"type": "alphabetical"}, "orderDirection": "desc", "size": 10},
                                "scale": "ordinal",
                                "sourceField": "incident_id",
                            },
                            "col_verdict": {
                                "dataType": "string",
                                "isBucketed": False,
                                "label": "Verdict",
                                "operationType": "last_value",
                                "params": {"sortField": "@timestamp", "showArrayValues": False},
                                "scale": "ordinal",
                                "sourceField": "verdict",
                            },
                            "col_score": {
                                "dataType": "number",
                                "isBucketed": False,
                                "label": "Confidence %",
                                "operationType": "max",
                                "params": {},
                                "scale": "ratio",
                                "sourceField": "confidence_score",
                            },
                            "col_status": {
                                "dataType": "string",
                                "isBucketed": False,
                                "label": "Report Status",
                                "operationType": "last_value",
                                "params": {"sortField": "@timestamp", "showArrayValues": False},
                                "scale": "ordinal",
                                "sourceField": "status",
                            },
                        },
                        "incompleteColumns": {},
                    }
                }
            },
            "textBased": {"layers": {}},
        },
        "adHocDataViews": {},
        "internalReferences": [],
        "visualization": {
            "layerId": "layer1",
            "layerType": "data",
            "columns": [
                {"columnId": "col_id", "isTransposed": False},
                {"columnId": "col_verdict", "isTransposed": False},
                {"columnId": "col_score", "isTransposed": False},
                {"columnId": "col_status", "isTransposed": False},
            ],
        },
        "query": {"language": "kuery", "query": ""},
        "filters": [],
    }
    return {
        "attributes": {"title": title, "visualizationType": "lnsDatatable", "state": state, "description": ""},
        "references": [{"id": dv_id, "name": "indexpattern-datasource-layer-layer1", "type": "index-pattern"}],
    }


def lens_actions_datatable(title, dv_id):
    """Datatable showing recent automated escalation actions."""
    state = {
        "datasourceStates": {
            "formBased": {
                "layers": {
                    "layer1": {
                        "columnOrder": ["col_time", "col_incident", "col_verdict", "col_score", "col_severity"],
                        "columns": {
                            "col_time": {
                                "dataType": "date",
                                "isBucketed": True,
                                "label": "Time",
                                "operationType": "date_histogram",
                                "params": {"interval": "auto", "includeEmptyRows": False},
                                "scale": "interval",
                                "sourceField": "@timestamp",
                            },
                            "col_incident": {
                                "dataType": "string",
                                "isBucketed": False,
                                "label": "Incident ID",
                                "operationType": "last_value",
                                "params": {"sortField": "@timestamp", "showArrayValues": False},
                                "scale": "ordinal",
                                "sourceField": "incident_id",
                            },
                            "col_verdict": {
                                "dataType": "string",
                                "isBucketed": False,
                                "label": "Verdict",
                                "operationType": "last_value",
                                "params": {"sortField": "@timestamp", "showArrayValues": False},
                                "scale": "ordinal",
                                "sourceField": "verdict",
                            },
                            "col_score": {
                                "dataType": "number",
                                "isBucketed": False,
                                "label": "Confidence %",
                                "operationType": "max",
                                "params": {},
                                "scale": "ratio",
                                "sourceField": "confidence_score",
                            },
                            "col_severity": {
                                "dataType": "string",
                                "isBucketed": False,
                                "label": "Severity",
                                "operationType": "last_value",
                                "params": {"sortField": "@timestamp", "showArrayValues": False},
                                "scale": "ordinal",
                                "sourceField": "severity",
                            },
                        },
                        "incompleteColumns": {},
                    }
                }
            },
            "textBased": {"layers": {}},
        },
        "adHocDataViews": {},
        "internalReferences": [],
        "visualization": {
            "layerId": "layer1",
            "layerType": "data",
            "columns": [
                {"columnId": "col_time",     "isTransposed": False},
                {"columnId": "col_incident", "isTransposed": False},
                {"columnId": "col_verdict",  "isTransposed": False},
                {"columnId": "col_score",    "isTransposed": False},
                {"columnId": "col_severity", "isTransposed": False},
            ],
        },
        "query": {"language": "kuery", "query": ""},
        "filters": [],
    }
    return {
        "attributes": {"title": title, "visualizationType": "lnsDatatable", "state": state, "description": ""},
        "references": [{"id": dv_id, "name": "indexpattern-datasource-layer-layer1", "type": "index-pattern"}],
    }


# --- 2+3. Build all objects and import in one shot ---
def create_dashboard_objects(logs_id, incidents_id, actions_id):
    print("\n[2/3] Building visualizations + dashboard...")

    viz_specs = [
        ("logsage-viz-001", lens_xy(
            "Error Spike Timeline", "bar_stacked",
            "@timestamp", "count", logs_id,
            kuery='level: "ERROR"', color="#e74c3c",
        )),
        ("logsage-viz-002", lens_xy(
            "Errors by Service", "bar",
            "service", "count", logs_id,
            kuery='level: "ERROR"', color="#e67e22",
        )),
        ("logsage-viz-003", lens_xy(
            "Average Latency (ms) Over Time", "line",
            "@timestamp", "avg", logs_id,
            y_field="latency_ms", color="#3498db",
        )),
        ("logsage-viz-004", lens_pie("Log Level Distribution", "level", logs_id)),
        ("logsage-viz-005", lens_datatable("Recent Incidents", incidents_id)),
        ("logsage-viz-006", lens_actions_datatable("Actions Taken", actions_id)),
    ]

    # Build import objects list (visualizations)
    objects = []
    viz_ids = []
    for viz_id, body in viz_specs:
        obj = {"id": viz_id, "type": "lens", "typeMigrationVersion": "9.0.0"}
        obj.update(body)
        objects.append(obj)
        viz_ids.append(viz_id)
        print(f"  - {body['attributes']['title']}")

    # Build dashboard object
    grid = [
        {"x": 0,  "y": 0,  "w": 48, "h": 15},
        {"x": 0,  "y": 15, "w": 24, "h": 15},
        {"x": 24, "y": 15, "w": 24, "h": 15},
        {"x": 0,  "y": 30, "w": 24, "h": 15},
        {"x": 24, "y": 30, "w": 24, "h": 15},
        {"x": 0,  "y": 45, "w": 48, "h": 15},
    ]
    panels = []
    dash_refs = []
    for i, (viz_id, g) in enumerate(zip(viz_ids, grid)):
        ref_name = f"panel_{i}"
        panels.append({
            "panelIndex": str(i + 1),
            "gridData": {**g, "i": str(i + 1)},
            "type": "lens",
            "panelRefName": ref_name,
            "embeddableConfig": {},
        })
        dash_refs.append({"name": ref_name, "type": "lens", "id": viz_id})

    objects.append({
        "id": "logsage-dashboard-001",
        "type": "dashboard",
        "typeMigrationVersion": "9.0.0",
        "attributes": {
            "title": "LogSage Incident Dashboard",
            "description": "Real-time log anomaly detection and incident tracking powered by LogSage.",
            "panelsJSON": json.dumps(panels),
            "optionsJSON": json.dumps({"useMargins": True, "syncColors": False, "hidePanelTitles": False}),
            "timeRestore": False,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps({"query": {"language": "kuery", "query": ""}, "filter": []})
            },
        },
        "references": dash_refs,
    })
    print("  - LogSage Incident Dashboard")

    # Save NDJSON to disk (always, useful for manual import)
    ndjson_path = "logsage-dashboard.ndjson"
    ndjson_content = "\n".join(json.dumps(o) for o in objects) + "\n"
    with open(ndjson_path, "w", encoding="utf-8") as f:
        f.write(ndjson_content)
    print(f"  NDJSON saved -> {ndjson_path}")

    print("\n[3/3] Importing via Saved Objects API...")
    result, status = import_objects(objects)

    if status == 200 and result.get("success"):
        count = result.get("successCount", 0)
        print(f"  [OK] {count} objects imported successfully.")
        return True
    else:
        errors = result.get("errors", [])
        if errors:
            for e in errors[:3]:
                print(f"  [ERR] {e.get('type')} '{e.get('id')}': {e.get('error', {}).get('message', '')}")
        else:
            raw_err = result.get("error", "")[:200]
            print(f"  [WARN] API import failed (HTTP {status}): {raw_err}")
        print()
        print("  *** MANUAL IMPORT INSTRUCTIONS ***")
        print(f"  1. Open: {os.environ.get('KIBANA_URL','<KIBANA_URL>')}/app/management/kibana/objects")
        print(f"  2. Click 'Import' button (top right)")
        print(f"  3. Select file: {os.path.abspath(ndjson_path)}")
        print(f"  4. Enable 'Overwrite existing objects'")
        print(f"  5. Click 'Import'")
        print()
        return False


# --- Main ---
def main():
    if not KIBANA_URL:
        print("ERROR: KIBANA_URL not set in .env")
        sys.exit(1)

    print("=" * 60)
    print("LogSage - Dashboard Setup")
    print("=" * 60)

    ids = create_data_views()
    logs_id      = ids.get("logsage-logs",      "logsage-logs")
    incidents_id = ids.get("logsage-incidents",  "logsage-incidents")
    actions_id   = ids.get("logsage-actions",    "logsage-actions")

    success = create_dashboard_objects(logs_id, incidents_id, actions_id)

    print("\n" + "=" * 60)
    if success:
        print("Setup complete!")
        print(f"\n  Dashboard URL:")
        print(f"  {KIBANA_URL}/app/dashboards#/view/logsage-dashboard-001")
        print("\n  Or: Analytics > Dashboards > 'LogSage Incident Dashboard'")
    else:
        print("Setup finished with errors. Check output above.")
    print("=" * 60)


if __name__ == "__main__":
    main()
