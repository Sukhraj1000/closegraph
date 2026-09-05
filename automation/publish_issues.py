"""Explicit, resumable catalogue publisher. Never called by autonomous workers."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO = "Sukhraj1000/closegraph"
ROOT = Path(__file__).resolve().parents[1]


def gh(*args, payload=None) -> Any:
    command = ["gh", *args]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                            text=True, capture_output=True, timeout=90, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def load_catalog(path):
    catalog = json.loads(path.read_text())
    if catalog.get("repo") != REPO:
        raise ValueError("Unexpected catalogue repository")
    entries = catalog["issues"]
    by_key = {i["key"]: i for i in entries}
    if len(by_key) != len(entries):
        raise ValueError("Duplicate catalogue key")
    tasks = [t for i in entries for t in i["spec_tasks"]]
    source = (ROOT / "openspec/changes/verify-corrected-reporting-pack/tasks.md").read_text()
    expected = re.findall(r"^- \[ \] (\d+\.\d+) ", source, re.M)
    if sorted(tasks) != sorted(expected) or len(set(tasks)) != len(tasks):
        raise ValueError("Original OpenSpec tasks are not mapped exactly once")
    for item in entries:
        for dependency in item["depends_on"]:
            if dependency not in by_key:
                raise ValueError(f"Missing dependency {dependency}")
    # A topological ordering lets child descriptions contain final dependency URLs immediately.
    ordered, pending = [], list(entries)
    while pending:
        done = {i["key"] for i in ordered}
        ready = [i for i in pending if set(i["depends_on"]).issubset(done)
                 and (not i.get("epic") or i["epic"] in done)]
        if not ready:
            raise ValueError("Cyclic or parent dependency in catalogue")
        for item in ready:
            pending.remove(item)
            ordered.append(item)
    return catalog, ordered


def render(item, index, children=None):
    marker = f"<!-- closegraph:catalog={item['key']} -->"
    sections = [marker, item["body"].strip()]
    if item.get("epic"):
        sections += [f"## Parent epic\n{index[item['epic']]['url']}"]
    deps = item["depends_on"]
    sections += ["## Execution dependencies\n" + ("\n".join(
        f"- {key}: {index[key]['url']}" for key in deps) if deps else
        "No other issue must finish first. Respect the shared contracts and scope described above.")]
    if children is not None:
        sections += ["## Child issues\n" + "\n".join(
            f"- [ ] {entry['url']}" for entry in children)]
    sections += ["## Operating boundary\nAutomation is paused. This issue is not permission to start a worker, change scope, bypass review, upload private data or enable external services. The user owns final integration/QA. Adding an issue is not implementation evidence."]
    return "\n\n".join(sections) + "\n"


def save_index(path, index, *, complete=False, native=False):
    payload = {"schema_version": 1, "repo": REPO, "complete": complete,
               "native_subissues_verified": native,
               "issues": list(index.values())}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def verify_issue(item, observed, body, wanted_labels, *, verify_body=True):
    """Resume must not certify a matching marker with changed acceptance."""
    if observed['title'] != item['title'] or f"<!-- closegraph:catalog={item['key']} -->" not in observed['body']:
        raise RuntimeError(f"Issue {item['key']} read-back mismatch")
    if (verify_body and observed['body'] != body) or {x['name'] for x in observed['labels']} != set(wanted_labels):
        raise RuntimeError(f"Issue {item['key']} content/label read-back mismatch")


def publish(catalog_path, output):
    catalog, ordered = load_catalog(catalog_path)
    metadata = gh("api", f"repos/{REPO}")
    if not metadata["private"] or not metadata["permissions"].get("admin"):
        raise RuntimeError("Requires the approved private repository with admin access")
    remote = gh("issue", "list", "--repo", REPO, "--state", "all", "--limit", "1000",
                "--json", "number,title,body,url,id")
    existing = {}
    for issue in remote:
        match = re.search(r"<!-- closegraph:catalog=([\w.]+) -->", issue["body"] or "")
        if match:
            if match[1] in existing:
                raise RuntimeError(f"Duplicate published marker {match[1]}")
            existing[match[1]] = issue
    if set(existing) - {i["key"] for i in ordered}:
        raise RuntimeError("Remote contains catalogue keys absent from local source")
    labels = sorted({label for i in ordered for label in i["labels"]} | {"loop:backlog", "loop:ready", "loop:hold"})
    current_labels = {i["name"] for i in gh("label", "list", "--repo", REPO, "--limit", "500", "--json", "name")}
    for label in labels:
        if label not in current_labels:
            gh("api", f"repos/{REPO}/labels", "--method", "POST",
               payload={"name": label, "color": "5319e7" if label == "epic" else "1d76db",
                        "description": "CloseGraph scoped engineering catalogue"})
    index = {}
    for item in ordered:
        body = render(item, index)
        wanted_labels = sorted((set(item["labels"]) | {"loop:backlog"}) - {"loop:ready"})
        prior = existing.get(item["key"])
        if prior:
            number = prior["number"]
            actual = gh("api", f"repos/{REPO}/issues/{number}")
            # Do not erase human/worker progress during retries.
            if actual["state"] != "open" or "loop:ready" in {x["name"] for x in actual["labels"]}:
                raise RuntimeError(f"Issue {number} has active progress; refusing overwrite")
            if actual["title"] != item["title"]:
                raise RuntimeError(f"Issue {number} title changed; manual reconciliation required")
            if item['kind'] == 'epic':
                prior_children = [existing[x['key']] for x in ordered
                                  if x.get('epic') == item['key'] and x['key'] in existing]
                expected_prior = render(item, index, prior_children)
                if actual['body'] not in (body, expected_prior):
                    raise RuntimeError(f"Epic {number} body changed; refusing overwrite")
        else:
            actual = gh("api", f"repos/{REPO}/issues", "--method", "POST",
                        payload={"title": item["title"], "body": body, "labels": wanted_labels,
                                 "assignees": []})
            number = actual["number"]
        record = {"key": item["key"], "number": number, "url": actual["html_url"],
                  "id": actual["id"], "node_id": actual["node_id"], "kind": item["kind"],
                  "epic": item.get("epic"), "spec_tasks": item["spec_tasks"]}
        index[item["key"]] = record
        save_index(output, index)
        verified = gh("api", f"repos/{REPO}/issues/{number}")
        verify_issue(item, verified, body, wanted_labels,
                     verify_body=not prior or item['kind'] != 'epic')
        print(f"Verified {item['key']} {record['url']}", flush=True)
    native = True
    for epic in [i for i in ordered if i["kind"] == "epic"]:
        children = [i for i in index.values() if i.get("epic") == epic["key"]]
        number = index[epic["key"]]["number"]
        body = render(epic, index, children)
        gh("api", f"repos/{REPO}/issues/{number}", "--method", "PATCH", payload={"body": body})
        if gh("api", f"repos/{REPO}/issues/{number}")["body"] != body:
            raise RuntimeError("Epic body read-back mismatch")
        existing_children = gh("api", f"repos/{REPO}/issues/{number}/sub_issues?per_page=100")
        current = {i["id"] for i in existing_children}
        for child in children:
            if child["id"] not in current:
                gh("api", f"repos/{REPO}/issues/{number}/sub_issues", "--method", "POST",
                   payload={"sub_issue_id": child["id"]})
        verified_children = gh("api", f"repos/{REPO}/issues/{number}/sub_issues?per_page=100")
        if {i["id"] for i in verified_children} != {i["id"] for i in children}:
            raise RuntimeError("Native sub-issue read-back mismatch")
        print(f"Verified hierarchy {epic['key']}: {len(children)} children", flush=True)
    readback = gh("issue", "list", "--repo", REPO, "--state", "all", "--limit", "1000", "--json", "number,title,body,state,url,labels")
    markers = [re.search(r"<!-- closegraph:catalog=([\w.]+) -->", i["body"] or "") for i in readback]
    keys = [m[1] for m in markers if m]
    if sorted(keys) != sorted(index):
        raise RuntimeError("Published catalogue count/key mismatch")
    by_number = {x['number']: x for x in readback}
    for item in ordered:
        children = [x for x in index.values() if x.get('epic') == item['key']] if item['kind'] == 'epic' else None
        verify_issue(item, by_number[index[item['key']]['number']], render(item, index, children),
                     sorted((set(item['labels']) | {'loop:backlog'}) - {'loop:ready'}))
    save_index(output, index, complete=True, native=native)
    print(json.dumps({"verified_issues": len(index), "epics": sum(i["kind"] == "epic" for i in index.values()),
                      "product_tasks": sum(bool(i["spec_tasks"]) for i in index.values()), "native_subissues_verified": native}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Explicitly publish approved catalogue to private GitHub repository")
    parser.add_argument("--catalog", type=Path, default=ROOT / "docs/engineering/issue-catalog.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/engineering/github-issues.json")
    args = parser.parse_args()
    catalog, ordered = load_catalog(args.catalog)
    if not args.apply:
        print(json.dumps({"repo": REPO, "issues": len(ordered), "epics": sum(i["kind"] == "epic" for i in ordered),
                          "product_tasks": sum(bool(i["spec_tasks"]) for i in ordered), "applied": False}))
    else:
        publish(args.catalog, args.output)


if __name__ == "__main__":
    main()
