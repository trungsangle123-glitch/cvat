"""Add the Facial Landmark-50 skeleton labels to a CVAT task or project.

Dry run by default - prints what would change and exits. Pass --apply to send
the PATCH. Only missing labels / sublabels are sent, and CVAT treats a PATCH
label list as an upsert, so existing labels, attributes and annotations are
left untouched.

Usage (token auth, recommended):

    set CVAT_TOKEN=xxxxxxxx
    python tools/setup_task.py --task-id 42
    python tools/setup_task.py --task-id 42 --apply

A token is created in CVAT: profile menu -> "Access tokens" -> Create.

Standard library only; no pip install needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from labels_spec import build_labels  # noqa: E402

DEFAULT_URL = "https://cvat.edufun.ai"
POINT_ID_RE = re.compile(r"(\d+)(?!.*\d)")


class CvatError(RuntimeError):
    pass


class Cvat:
    def __init__(self, url: str, token: str, insecure: bool = False):
        self.url = url.rstrip("/")
        self.token = token
        self.context = ssl._create_unverified_context() if insecure else None

    def request(self, path: str, method: str = "GET", payload: dict | None = None):
        url = f"{self.url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Token {self.token}")

        try:
            with urllib.request.urlopen(req, timeout=60, context=self.context) as res:
                body = res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise CvatError(f"{method} {path} -> HTTP {exc.code}: {detail[:800]}") from None
        except urllib.error.URLError as exc:
            raise CvatError(f"{method} {url} failed: {exc.reason}") from None

        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise CvatError(f"{method} {path} returned non-JSON: {body[:300]}") from None

    def get(self, path: str):
        return self.request(path)

    def patch(self, path: str, payload: dict):
        return self.request(path, method="PATCH", payload=payload)


def point_id(name: str) -> int | None:
    match = POINT_ID_RE.search(str(name or ""))
    return int(match.group(1)) if match else None


def resolve_target(api: Cvat, args) -> tuple[str, int, str]:
    """Return (resource, id, note) - labels are owned by the project when set."""
    if args.project_id:
        return "projects", args.project_id, ""

    task_id = args.task_id
    if args.job_id:
        job = api.get(f"/api/jobs/{args.job_id}")
        task_id = job["task_id"]
        note = f"job {args.job_id} belongs to task {task_id}"
    else:
        note = ""

    task = api.get(f"/api/tasks/{task_id}")
    project_id = task.get("project_id")
    if project_id:
        return (
            "projects",
            project_id,
            f"task {task_id} is inside project {project_id}; labels live on the project",
        )
    return "tasks", task_id, note


def fetch_labels(api: Cvat, resource: str, target_id: int) -> list[dict]:
    query = urllib.parse.urlencode({f"{resource[:-1]}_id": target_id, "page_size": 1000})
    data = api.get(f"/api/labels?{query}")
    return data if isinstance(data, list) else data.get("results", [])


def build_plan(existing: list[dict], desired: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """Return (payload_labels, notes, problems)."""
    by_name = {label["name"]: label for label in existing}
    payload: list[dict] = []
    notes: list[str] = []
    problems: list[str] = []

    for want in desired:
        current = by_name.get(want["name"])
        if current is None:
            payload.append(want)
            notes.append(f"create skeleton {want['name']} ({len(want['sublabels'])} points)")
            continue

        if str(current.get("type")) != "skeleton":
            problems.append(
                f"label {want['name']!r} already exists with type {current.get('type')!r}; "
                "rename it in the CVAT UI first - this script never changes existing labels"
            )
            continue

        have = {point_id(sub.get("name")) for sub in current.get("sublabels") or []}
        missing = [sub for sub in want["sublabels"] if point_id(sub["name"]) not in have]
        if not missing:
            notes.append(f"ok {want['name']} ({len(have)} points)")
            continue

        payload.append(
            {
                "id": current["id"],
                "name": current["name"],
                "type": "skeleton",
                "sublabels": missing,
            }
        )
        notes.append(
            f"add {len(missing)} point(s) to {want['name']}: "
            + ", ".join(sub["name"] for sub in missing)
        )

    return payload, notes, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Add Face Landmark-50 skeleton labels to a CVAT task/project (dry run by default)."
    )
    parser.add_argument("--url", default=os.environ.get("CVAT_URL", DEFAULT_URL))
    parser.add_argument(
        "--token",
        default=os.environ.get("CVAT_TOKEN", ""),
        help="CVAT access token (or set CVAT_TOKEN)",
    )
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--apply", action="store_true", help="actually PATCH CVAT")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification")
    parser.add_argument(
        "--emit",
        type=Path,
        help="also write labels_raw.json to this path (e.g. ../face50-extension/labels_raw.json)",
    )
    args = parser.parse_args(argv)

    if sum(bool(x) for x in (args.task_id, args.job_id, args.project_id)) != 1:
        parser.error("pass exactly one of --task-id / --job-id / --project-id")
    if not args.token:
        parser.error("a CVAT access token is required (--token or CVAT_TOKEN)")

    if args.emit:
        args.emit.parent.mkdir(parents=True, exist_ok=True)
        args.emit.write_text(
            json.dumps(build_labels(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.emit}")

    api = Cvat(args.url, args.token, insecure=args.insecure)
    resource, target_id, note = resolve_target(api, args)
    if note:
        print(f"* {note}")
    print(f"* target: {resource}/{target_id} on {api.url}")

    existing = fetch_labels(api, resource, target_id)
    payload, notes, problems = build_plan(existing, build_labels())

    for line in notes:
        print(f"  - {line}")
    for line in problems:
        print(f"  ! {line}")

    if problems:
        print("\nNothing was sent: resolve the conflicts above first.")
        return 2

    if not payload:
        print("\nAll Face-50 labels are already present. Nothing to do.")
        return 0

    if not args.apply:
        print(f"\nDry run: {len(payload)} label(s) would be PATCHed. Re-run with --apply to write.")
        return 0

    result = api.patch(f"/api/{resource}/{target_id}", {"labels": payload})
    total = len(result.get("labels", [])) if isinstance(result, dict) else "?"
    print(f"\nPATCH ok - {len(payload)} label(s) sent, task/project now reports {total} labels.")
    print("Reload the CVAT annotation page so the extension picks up the new labels.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CvatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
