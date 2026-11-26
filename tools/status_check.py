#!/usr/bin/env python3
"""Uptime + CI monitor for the portfolio (runs in GitHub Actions, free).

- Pings every live demo (3 tries) and reads the latest default-branch run of
  every workflow in every public repo.
- Writes status.json (read by the site: /status page, hero summary and the
  maintenance flag on project cards).
- Opens one GitHub issue per red component (label "status-alert"), and closes
  it with a comment when the component is green again.

Never prints tokens. Never changes, archives or deletes repos.
Usage: status_check.py <previous status.json or ''> <output status.json>
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "status_targets.json").read_text(encoding="utf-8"))
OWNER = CFG["owner"]
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ALERT_REPO = os.environ.get("ALERT_REPO", f"{OWNER}/lucian-ceusan-site")
LABEL = "status-alert"
BAD = {"failure", "timed_out", "startup_failure"}
UA = "lucian-ceusan-status-monitor"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def gh(method: str, path: str, body: dict | None = None):
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", UA)
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def ping(url: str) -> tuple[bool, int, int]:
    code, ms = 0, 0
    for attempt in range(3):
        t = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read(2048)
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception:
            code = 0
        ms = int((time.monotonic() - t) * 1000)
        if 200 <= code < 400:
            return True, code, ms
        time.sleep(5 * (attempt + 1))
    return False, code, ms


def repo_ci(repo: dict) -> dict:
    name, branch = repo["name"], repo.get("default_branch") or "main"
    try:
        runs = gh("GET", f"/repos/{OWNER}/{name}/actions/runs?branch={branch}&per_page=40&exclude_pull_requests=true")
    except Exception as e:
        return {"repo": name, "state": "unknown", "workflows": [], "note": type(e).__name__}
    latest: dict[int, dict] = {}
    for r in runs.get("workflow_runs", []):
        if r.get("status") != "completed" or r.get("conclusion") in ("cancelled", "skipped"):
            continue
        # GitHub's own dependency-graph jobs are noise here; keep CodeQL
        if r.get("event") == "dynamic" and not str(r.get("name", "")).startswith("CodeQL"):
            continue
        latest.setdefault(r["workflow_id"], r)
    wfs = [{"name": r["name"], "conclusion": r["conclusion"], "url": r["html_url"], "at": r.get("updated_at")}
           for r in latest.values()]
    if not wfs:
        state = "none"
    else:
        state = "fail" if any(w["conclusion"] in BAD for w in wfs) else "ok"
    return {"repo": name, "url": f"https://github.com/{OWNER}/{name}", "state": state, "workflows": wfs}


def alert(key: str, title: str, red: bool, detail: str, issues: dict) -> None:
    if not TOKEN or os.environ.get("DRY_RUN"):
        return
    existing = issues.get(key)
    try:
        if red and not existing:
            gh("POST", f"/repos/{ALERT_REPO}/issues", {
                "title": title, "labels": [LABEL],
                "body": f"{detail}\n\nThe site shows this item as **under maintenance** until it is green again. "
                        f"This issue closes itself on recovery.\n\n<!-- status-key:{key} -->"})
        elif not red and existing:
            gh("POST", f"/repos/{ALERT_REPO}/issues/{existing}/comments", {"body": f"Recovered at {now()}. Closing."})
            gh("PATCH", f"/repos/{ALERT_REPO}/issues/{existing}", {"state": "closed"})
    except Exception as e:  # alerting must never break the monitor
        print(f"alert {key}: {type(e).__name__}")


def main() -> int:
    prev_path, out_path = sys.argv[1], sys.argv[2]
    prev = {}
    if prev_path and Path(prev_path).is_file():
        try:
            prev = json.loads(Path(prev_path).read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    prev_since = {("d", d["id"]): (d["state"], d.get("since")) for d in prev.get("demos", [])}
    prev_since.update({("c", c["repo"]): (c["state"], c.get("since")) for c in prev.get("ci", [])})
    ts = now()

    def since(key, state):
        old = prev_since.get(key)
        return old[1] if old and old[0] == state and old[1] else ts

    demos = []
    for d in CFG["demos"]:
        up, code, ms = ping(d["url"])
        st = "up" if up else "down"
        demos.append({**d, "state": st, "code": code, "ms": ms, "since": since(("d", d["id"]), st)})

    ci = []
    try:
        repos = gh("GET", f"/users/{OWNER}/repos?type=owner&per_page=100")
    except Exception as e:
        print(f"repo list failed: {type(e).__name__}")
        repos = []
    for r in sorted(repos, key=lambda r: r["name"].lower()):
        if r.get("private") or r.get("archived") or r.get("fork") or r["name"] in CFG.get("skip_repos", []):
            continue
        c = repo_ci(r)
        c["since"] = since(("c", c["repo"]), c["state"])
        ci.append(c)

    # open alert issues, keyed by the hidden marker in the body
    issues = {}
    if TOKEN:
        try:
            for i in gh("GET", f"/repos/{ALERT_REPO}/issues?state=open&labels={LABEL}&per_page=100"):
                body = i.get("body") or ""
                if "<!-- status-key:" in body:
                    issues[body.split("<!-- status-key:")[1].split(" -->")[0]] = i["number"]
        except Exception as e:
            print(f"issue list failed: {type(e).__name__}")
    for d in demos:
        alert(f"demo:{d['id']}", f"🔴 Down: {d['name']}", d["state"] == "down",
              f"{d['url']} did not answer OK after 3 tries (last HTTP {d['code'] or 'no response'}) at {ts}.", issues)
    for c in ci:
        failed = ", ".join(w["name"] for w in c["workflows"] if w["conclusion"] in BAD)
        alert(f"ci:{c['repo']}", f"🔴 CI failing: {c['repo']}", c["state"] == "fail",
              f"Latest default-branch run failed in {c['url']}: {failed}.", issues)

    red = sum(d["state"] == "down" for d in demos) + sum(c["state"] == "fail" for c in ci)
    out = {"updated": ts, "overall": "ok" if red == 0 else "degraded", "red": red,
           "demos": demos, "ci": ci}
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(demos)} demos, {len(ci)} repos, red={red}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
