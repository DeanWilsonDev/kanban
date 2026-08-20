#!/usr/bin/env python3
"""
kanban.py -- a tiered Epic/Feature/Story/Task backlog, queried through this script
instead of read as prose.

Layout (relative to a repo's docs/kanban/):

    docs/kanban/_index.csv                              children: epic
    docs/kanban/<epic>/epic.json
    docs/kanban/<epic>/_index.csv                        children: feature | task
    docs/kanban/<epic>/<feature>/feature.json
    docs/kanban/<epic>/<feature>/_index.csv              children: story | task
    docs/kanban/<epic>/<feature>/<story>/story.json
    docs/kanban/<epic>/<feature>/<story>/_index.csv      children: task only
    docs/kanban/<epic>/<feature>/<story>/<task>.json      leaf -- plain file, no directory

Every _index.csv has the same columns: id,kind,name,status,priority,file,created,updated
  - status:   todo | in-progress | complete
  - priority: 1-5, lower = more important (1=critical/must, 2=high/should, 3=medium/normal
              -- the default, 4=low/nice-to-have, 5=trivial/someday). Each node's priority is
              independent -- never inherited or computed from its parent.

Every item's own file is a self-contained JSON record (id, path, kind, name, status, priority,
parent, created, updated, body) so a downstream tool can ingest one file -- or a concatenation of
all of them -- without cross-referencing the CSVs. The CSV stays the fast index scripts use for
listing/sorting/filtering without opening every file; `status`/`priority` mutations write both
the CSV row and the JSON record's mirrored fields in the same call, so they can't drift as long as
everything goes through this script (see `lint`, which also checks the two agree).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import html as html_lib
import json
import re
import sys
from pathlib import Path

FIELDS = ["id", "kind", "name", "status", "priority", "file", "created", "updated"]
ITEM_FIELDS = ["id", "path", "kind", "name", "status", "priority", "parent", "created", "updated", "body"]
VALID_STATUS = ("todo", "in-progress", "complete")
VALID_PRIORITY = range(1, 6)
CONTAINER_KINDS = ("epic", "feature", "story")
DOC_NAME = {"epic": "epic.json", "feature": "feature.json", "story": "story.json"}
# What kind of child is allowed directly under a node of a given kind ("root" = docs/kanban/ itself)
CHILD_KINDS = {
    "root": {"epic"},
    "epic": {"feature", "task"},
    "feature": {"story", "task"},
    "story": {"task"},
}
STATUS_MARK = {"todo": "☐", "in-progress": "▶", "complete": "✓"}


class KanbanError(RuntimeError):
    pass


# --------------------------------------------------------------------------- helpers

def today() -> str:
    return datetime.date.today().isoformat()


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        raise KanbanError(f"name {name!r} has no usable characters for a slug")
    return s


def unique_slug(existing_ids: set[str], base: str) -> str:
    if base not in existing_ids:
        return base
    n = 2
    while f"{base}-{n}" in existing_ids:
        n += 1
    return f"{base}-{n}"


def find_root(start: Path, override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    cur = Path(start).resolve()
    for p in [cur, *cur.parents]:
        candidate = p / "docs" / "kanban"
        if candidate.is_dir():
            return candidate
    for p in [cur, *cur.parents]:
        if (p / ".git").exists():
            return p / "docs" / "kanban"
    return cur / "docs" / "kanban"


def ensure_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "_index.csv"
    if not csv_path.exists():
        write_rows(csv_path, [])


def dir_kind(path: Path) -> str:
    for kind, doc_name in DOC_NAME.items():
        if (path / doc_name).exists():
            return kind
    return "root"


# --------------------------------------------------------------------------- CSV I/O

def read_rows(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(csv_path: Path, rows: list[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})


def append_row(csv_path: Path, row: dict) -> None:
    rows = read_rows(csv_path)
    rows.append(row)
    write_rows(csv_path, rows)


def update_row(csv_path: Path, row_id: str, **updates) -> bool:
    rows = read_rows(csv_path)
    found = False
    for row in rows:
        if row["id"] == row_id:
            row.update(updates)
            found = True
            break
    if found:
        write_rows(csv_path, rows)
    return found


# --------------------------------------------------------------------------- item JSON I/O

def read_item(doc_path: Path) -> dict:
    with doc_path.open(encoding="utf-8") as f:
        return json.load(f)


def write_item(doc_path: Path, record: dict) -> None:
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: record.get(k, "" if k != "priority" else 3) for k in ITEM_FIELDS}
    doc_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_item(doc_path: Path, **updates) -> None:
    record = read_item(doc_path)
    record.update(updates)
    write_item(doc_path, record)


# --------------------------------------------------------------------------- locating a node by path

def locate(root: Path, rel_path: str):
    """Resolve a '/'-joined relative path to (kind, doc_path, parent_dir, node_id)."""
    parts = [p for p in rel_path.strip("/").split("/") if p]
    if not parts:
        raise KanbanError("empty path")
    parent_dir = root.joinpath(*parts[:-1]) if len(parts) > 1 else root
    node_id = parts[-1]
    dir_candidate = root.joinpath(*parts)
    if dir_candidate.is_dir():
        kind = dir_kind(dir_candidate)
        if kind == "root":
            raise KanbanError(f"{rel_path!r} is a directory but has no epic.json/feature.json/story.json")
        return kind, dir_candidate / DOC_NAME[kind], parent_dir, node_id
    task_candidate = root.joinpath(*parts[:-1], node_id + ".json")
    if task_candidate.exists():
        return "task", task_candidate, parent_dir, node_id
    raise KanbanError(f"no such kanban item: {rel_path!r}")


def node_dir_for_row(node_dir: Path, row: dict) -> Path:
    """Given a container dir and one of its child rows, return that child's own directory
    (only meaningful when the row's kind is a container kind)."""
    return node_dir / row["id"]


# --------------------------------------------------------------------------- recursive walk

def walk(root: Path, node_dir: Path, start_path: str = "", depth: int = 0):
    """Yield (path_str, row_dict, depth) for every descendant of node_dir, recursively."""
    csv_path = node_dir / "_index.csv"
    for row in read_rows(csv_path):
        path_str = f"{start_path}/{row['id']}" if start_path else row["id"]
        yield path_str, row, depth
        if row["kind"] in CONTAINER_KINDS:
            yield from walk(root, node_dir_for_row(node_dir, row), path_str, depth + 1)


def resolve_container_dir(root: Path, path: str | None) -> tuple[Path, str]:
    """Resolve an optional path to (dir, path_str) for a container node ('' for root)."""
    if not path:
        return root, ""
    kind, doc_path, _parent_dir, _node_id = locate(root, path)
    if kind == "task":
        raise KanbanError(f"{path!r} is a task -- tasks have no children")
    return doc_path.parent, path.strip("/")


# --------------------------------------------------------------------------- validation

def validate_priority(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise KanbanError(f"priority must be an integer 1-5, got {value!r}")
    if n not in VALID_PRIORITY:
        raise KanbanError(f"priority must be 1-5, got {n}")
    return n


def validate_status(value: str) -> str:
    if value not in VALID_STATUS:
        raise KanbanError(f"status must be one of {VALID_STATUS}, got {value!r}")
    return value


# --------------------------------------------------------------------------- commands

def cmd_init(root: Path, args):
    ensure_root(root)
    print(f"initialized {root}/_index.csv")


def cmd_new(root: Path, args):
    ensure_root(root)
    kind = args.kind
    name = args.name
    priority = validate_priority(args.priority)
    status = validate_status(getattr(args, "status", "todo"))
    parent_path = "" if kind == "epic" else args.parent.strip("/")

    if kind == "epic":
        parent_kind, parent_dir = "root", root
    else:
        parent_kind, doc_path, _pd, _nid = locate(root, args.parent)
        if parent_kind == "task":
            raise KanbanError(f"{args.parent!r} is a task -- cannot add a child to it")
        parent_dir = doc_path.parent

    if kind not in CHILD_KINDS[parent_kind]:
        raise KanbanError(f"a {parent_kind} cannot have a {kind} child (allowed: {sorted(CHILD_KINDS[parent_kind])})")

    parent_csv = parent_dir / "_index.csv"
    existing_ids = {r["id"] for r in read_rows(parent_csv)}
    slug = unique_slug(existing_ids, slugify(name))
    node_path = f"{parent_path}/{slug}" if parent_path else slug
    d = today()
    record = {
        "id": slug, "path": node_path, "kind": kind, "name": name, "status": status,
        "priority": priority, "parent": parent_path or None, "created": d, "updated": d, "body": "",
    }

    if kind in CONTAINER_KINDS:
        node_dir = parent_dir / slug
        node_dir.mkdir(parents=True)
        doc_name = DOC_NAME[kind]
        write_item(node_dir / doc_name, record)
        write_rows(node_dir / "_index.csv", [])
        file_rel = f"{slug}/{doc_name}"
    else:
        write_item(parent_dir / f"{slug}.json", record)
        file_rel = f"{slug}.json"

    append_row(parent_csv, {
        "id": slug, "kind": kind, "name": name, "status": status,
        "priority": priority, "file": file_rel, "created": d, "updated": d,
    })
    print(f"created {kind} {node_path}")


def cmd_body(root: Path, args):
    _kind, doc_path, parent_dir, node_id = locate(root, args.path)
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    d = today()
    update_item(doc_path, body=text.rstrip(), updated=d)
    update_row(parent_dir / "_index.csv", node_id, updated=d)
    print(f"{args.path}: body updated ({len(text)} chars)")


def cmd_status(root: Path, args):
    value = validate_status(args.value)
    _kind, doc_path, parent_dir, node_id = locate(root, args.path)
    d = today()
    ok = update_row(parent_dir / "_index.csv", node_id, status=value, updated=d)
    if not ok:
        raise KanbanError(f"could not find row for {args.path!r} in {parent_dir / '_index.csv'}")
    update_item(doc_path, status=value, updated=d)
    print(f"{args.path}: status -> {value}")


def cmd_priority(root: Path, args):
    value = validate_priority(args.value)
    _kind, doc_path, parent_dir, node_id = locate(root, args.path)
    d = today()
    ok = update_row(parent_dir / "_index.csv", node_id, priority=value, updated=d)
    if not ok:
        raise KanbanError(f"could not find row for {args.path!r} in {parent_dir / '_index.csv'}")
    update_item(doc_path, priority=value, updated=d)
    print(f"{args.path}: priority -> {value}")


def _print_table(rows, path_prefix=""):
    if not rows:
        print("(none)")
        return
    widths = {"priority": 3, "status": 11, "kind": 7, "id": 4, "name": 4}
    for r in rows:
        widths["priority"] = max(widths["priority"], len(str(r.get("priority", ""))))
        widths["status"] = max(widths["status"], len(str(r.get("status", ""))))
        widths["kind"] = max(widths["kind"], len(str(r.get("kind", ""))))
        widths["id"] = max(widths["id"], len(str(r.get("id", ""))))
        widths["name"] = max(widths["name"], len(str(r.get("name", ""))))
    header = f"{'P':<{widths['priority']}}  {'STATUS':<{widths['status']}}  {'KIND':<{widths['kind']}}  {'ID':<{widths['id']}}  NAME"
    print(header)
    for r in rows:
        print(f"{r.get('priority',''):<{widths['priority']}}  {r.get('status',''):<{widths['status']}}  "
              f"{r.get('kind',''):<{widths['kind']}}  {r.get('id',''):<{widths['id']}}  {r.get('name','')}")


def cmd_list(root: Path, args):
    node_dir, _path_str = resolve_container_dir(root, args.path)
    rows = read_rows(node_dir / "_index.csv")
    if args.status:
        rows = [r for r in rows if r["status"] == args.status]
    key = args.sort
    if key == "priority":
        rows.sort(key=lambda r: (int(r["priority"]), r["created"]))
    else:
        rows.sort(key=lambda r: r[key])
    _print_table(rows)


def cmd_next(root: Path, args):
    node_dir, path_str = resolve_container_dir(root, args.under)
    candidates = []
    for p, row, _depth in walk(root, node_dir, path_str):
        if row["status"] != "todo":
            continue
        if args.kind and args.kind != "all" and row["kind"] != args.kind:
            continue
        candidates.append((p, row))
    candidates.sort(key=lambda pr: (int(pr[1]["priority"]), pr[1]["created"]))
    candidates = candidates[: args.top]
    if not candidates:
        print("(nothing todo)")
        return
    for p, row in candidates:
        print(f"{row['priority']}  {row['kind']:<7}  {p}  -- {row['name']}")


def cmd_in_progress(root: Path, args):
    node_dir, path_str = resolve_container_dir(root, args.under)
    results = [(p, row) for p, row, _d in walk(root, node_dir, path_str) if row["status"] == "in-progress"]
    results.sort(key=lambda pr: (int(pr[1]["priority"]), pr[1]["created"]))
    if not results:
        print("(nothing in progress)")
        return
    for p, row in results:
        print(f"{row['priority']}  {row['kind']:<7}  {p}  -- {row['name']}")


def cmd_tree(root: Path, args):
    node_dir, path_str = resolve_container_dir(root, args.path)
    label = args.path or "(root)"
    print(label)
    for p, row, depth in walk(root, node_dir, path_str):
        indent = "  " * (depth + 1)
        mark = STATUS_MARK.get(row["status"], "?")
        print(f"{indent}{mark} [{row['priority']}] {row['id']} -- {row['name']}")


def cmd_show(root: Path, args):
    kind, doc_path, parent_dir, node_id = locate(root, args.path)
    record = read_item(doc_path)
    print(f"[{kind}] {record['path']}  status={record['status']}  priority={record['priority']}  "
          f"created={record['created']}  updated={record['updated']}  parent={record['parent'] or '(none)'}")
    print("-" * 60)
    print(f"# {record['name']}")
    if record["body"]:
        print()
        print(record["body"].rstrip())
    if kind in CONTAINER_KINDS:
        child_rows = read_rows(doc_path.parent / "_index.csv")
        if child_rows:
            print("-" * 60)
            print("children:")
            child_rows.sort(key=lambda r: (int(r["priority"]), r["created"]))
            _print_table(child_rows)


def build_tree(node_dir: Path) -> list[dict]:
    """Return the full nested record list for node_dir's direct children, recursively --
    each dict is that item's own JSON record (id/kind/name/status/priority/... /body) plus a
    'children' list of the same shape. Sorted the same way `next`/`list` sort (priority, then
    creation date)."""
    rows = read_rows(node_dir / "_index.csv")
    rows.sort(key=lambda r: (int(r["priority"]), r["created"]))
    result = []
    for row in rows:
        record = dict(read_item(node_dir / row["file"]))
        record["children"] = build_tree(node_dir / row["id"]) if row["kind"] in CONTAINER_KINDS else []
        result.append(record)
    return result


def _flatten_tasks(node: dict):
    for c in node.get("children", []):
        if c["kind"] == "task":
            yield c
        yield from _flatten_tasks(c)


def _render_body_html(text: str) -> str:
    if not text:
        return ""
    blocks = []
    for para in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in para.split("\n")]
        bullet_lines = [l for l in lines if l.strip()]
        if bullet_lines and all(re.match(r"^\s*[-*]\s+", l) for l in bullet_lines):
            items = [re.sub(r"^\s*[-*]\s+", "", l) for l in bullet_lines]
            blocks.append("<ul>" + "".join(f"<li>{_inline_md(html_lib.escape(i))}</li>" for i in items) + "</ul>")
        else:
            joined = " ".join(l.strip() for l in lines if l.strip())
            blocks.append(f"<p>{_inline_md(html_lib.escape(joined))}</p>")
    return "\n".join(blocks)


def _inline_md(escaped_text: str) -> str:
    escaped_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped_text)
    escaped_text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", escaped_text)
    return escaped_text


def _render_node_html(node: dict, open_by_default: bool) -> str:
    status = node.get("status", "todo")
    priority = node.get("priority", 3)
    kind = node.get("kind", "task")
    name_esc = html_lib.escape(node.get("name", ""))
    body_html = _render_body_html(node.get("body", ""))
    children = node.get("children", [])
    search_blob = html_lib.escape((node.get("name", "") + " " + node.get("body", "")).lower())

    child_count_badge = ""
    if children:
        tasks = list(_flatten_tasks(node))
        if tasks:
            done = sum(1 for t in tasks if t["status"] == "complete")
            child_count_badge = f'<span class="counts">{done}/{len(tasks)}</span>'

    body_block = f'<div class="body">{body_html}</div>' if body_html else ""
    children_html = "".join(_render_node_html(c, False) for c in children)
    open_attr = " open" if open_by_default else ""

    return (
        f'<details class="node kind-{kind} status-{status}" data-search="{search_blob}"{open_attr}>'
        f'<summary><span class="prio p{priority}">P{priority}</span>'
        f'<span class="kindtag">{kind}</span>'
        f'<span class="dot"></span>'
        f'<span class="name">{name_esc}</span>'
        f"{child_count_badge}</summary>"
        f"{body_block}"
        f'<div class="children">{children_html}</div>'
        f"</details>"
    )


_REPORT_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0; background: #f1f5f9; color: #0f172a;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
header {
  position: sticky; top: 0; z-index: 10; background: #0f172a; color: #f8fafc;
  padding: 12px 16px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
header h1 { font-size: 16px; margin: 0; font-weight: 600; }
header .meta { color: #94a3b8; font-size: 12px; }
header input[type=search] {
  padding: 6px 10px; border-radius: 6px; border: 1px solid #334155; background: #1e293b;
  color: #f8fafc; font-size: 13px; min-width: 220px;
}
header label { font-size: 13px; display: flex; align-items: center; gap: 6px; cursor: pointer; }
.board { display: flex; gap: 14px; overflow-x: auto; padding: 16px; align-items: flex-start; }
.lane {
  flex: 0 0 auto; width: 340px; background: #ffffff; border-radius: 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,.06); padding: 10px;
}
.lane > .node { border: none; }
.lane > .node > summary { font-size: 15px; font-weight: 600; }
summary {
  cursor: pointer; list-style: none; display: flex; align-items: center; gap: 6px;
  padding: 6px 6px; border-radius: 6px; user-select: none;
}
summary::-webkit-details-marker { display: none; }
summary:hover { background: #f1f5f9; }
.node { border-left: 2px solid transparent; }
.node.status-todo > summary { border-left: 3px solid #94a3b8; }
.node.status-in-progress > summary { border-left: 3px solid #f59e0b; background: #fffbeb; }
.node.status-complete > summary { border-left: 3px solid #16a34a; }
.node.status-complete { opacity: .65; }
.dot { display: none; }
.kindtag {
  font-size: 10px; text-transform: uppercase; letter-spacing: .03em; color: #64748b;
  background: #f1f5f9; padding: 1px 6px; border-radius: 999px;
}
.name { flex: 1; }
.counts { font-size: 11px; color: #64748b; }
.prio {
  font-size: 10px; font-weight: 700; color: #fff; border-radius: 999px; padding: 1px 6px;
  min-width: 20px; text-align: center;
}
.p1 { background: #dc2626; } .p2 { background: #f59e0b; } .p3 { background: #64748b; }
.p4 { background: #94a3b8; } .p5 { background: #cbd5e1; color: #334155; }
.body { margin: 4px 0 6px 26px; color: #334155; font-size: 13px; }
.body p { margin: 0 0 8px; }
.body ul { margin: 0 0 8px 18px; padding: 0; }
.body code {
  background: #f1f5f9; padding: 1px 4px; border-radius: 4px; font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.children { margin-left: 16px; padding-left: 10px; border-left: 1px dashed #e2e8f0; }
body.hide-complete .node.status-complete { display: none; }
.node.search-hide { display: none; }
@media (prefers-color-scheme: dark) {
  body { background: #0b1120; color: #e2e8f0; }
  .lane { background: #111827; box-shadow: none; border: 1px solid #1f2937; }
  summary:hover { background: #1f2937; }
  .kindtag { background: #1f2937; color: #94a3b8; }
  .body { color: #cbd5e1; }
  .body code { background: #1f2937; }
  .children { border-left-color: #1f2937; }
  .node.status-in-progress > summary { background: #1c1608; }
}
"""

_REPORT_JS = """
const hideBox = document.getElementById('hide-complete');
hideBox.addEventListener('change', () => {
  document.body.classList.toggle('hide-complete', hideBox.checked);
});
document.body.classList.toggle('hide-complete', hideBox.checked);

const search = document.getElementById('search');
search.addEventListener('input', () => {
  const q = search.value.trim().toLowerCase();
  const nodes = document.querySelectorAll('.node');
  if (!q) {
    nodes.forEach(n => n.classList.remove('search-hide'));
    return;
  }
  nodes.forEach(n => {
    const hit = (n.dataset.search || '').includes(q);
    n.classList.toggle('search-hide', !hit);
    if (hit) {
      let p = n.parentElement;
      while (p) {
        if (p.tagName === 'DETAILS') { p.open = true; p.classList.remove('search-hide'); }
        p = p.parentElement;
      }
      if (n.querySelectorAll) n.querySelectorAll('details').forEach(d => d.open = true);
    }
  });
});
"""


def cmd_report(root: Path, args):
    node_dir, path_str = resolve_container_dir(root, args.path)
    epics = build_tree(node_dir)

    lanes_html = []
    for epic in epics:
        tasks = list(_flatten_tasks(epic))
        done = sum(1 for t in tasks if t["status"] == "complete")
        stat = f'<div class="meta">{done}/{len(tasks)} tasks complete</div>' if tasks else ""
        lanes_html.append(f'<div class="lane">{_render_node_html(epic, True)}{stat}</div>')

    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    scope = path_str or "(whole tree)"
    # Guard against a body ever containing a literal "</script" sequence and breaking out of the
    # embedded JSON <script> block.
    data_json = json.dumps(epics).replace("</", "<\\/")
    html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Kanban report</title>
<style>{_REPORT_CSS}</style>
</head>
<body>
<header>
  <h1>Kanban report</h1>
  <span class="meta">scope: {html_lib.escape(scope)} &middot; generated {generated}</span>
  <input type="search" id="search" placeholder="filter by name/body text...">
  <label><input type="checkbox" id="hide-complete" checked> hide complete</label>
</header>
<div class="board">
{"".join(lanes_html)}
</div>
<script id="kanban-data" type="application/json">{data_json}</script>
<script>{_REPORT_JS}</script>
</body>
</html>
"""
    out_path = Path(args.out) if args.out else Path.cwd() / "kanban-report.html"
    out_path.write_text(html_doc, encoding="utf-8")
    print(f"wrote {out_path}")


def cmd_lint(root: Path, args):
    node_dir, path_str = resolve_container_dir(root, args.path)
    problems: list[str] = []

    def check_dir(dir_path: Path, dir_path_str: str, parent_kind: str):
        csv_path = dir_path / "_index.csv"
        rows = read_rows(csv_path)
        seen_ids: set[str] = set()
        for row in rows:
            loc = f"{dir_path_str or '(root)'}::{row.get('id','?')}"
            if row["id"] in seen_ids:
                problems.append(f"{loc}: duplicate id in {csv_path}")
            seen_ids.add(row["id"])
            if row["kind"] not in CHILD_KINDS.get(parent_kind, set()):
                problems.append(f"{loc}: kind {row['kind']!r} not valid under a {parent_kind}")
            if row["status"] not in VALID_STATUS:
                problems.append(f"{loc}: invalid status {row['status']!r}")
            try:
                validate_priority(row["priority"])
            except KanbanError as e:
                problems.append(f"{loc}: {e}")
            child_path = dir_path / row["file"]
            if not child_path.exists():
                problems.append(f"{loc}: file {row['file']!r} does not exist")
            else:
                try:
                    item = read_item(child_path)
                except (ValueError, OSError) as e:
                    problems.append(f"{loc}: {row['file']!r} is not valid JSON: {e}")
                else:
                    missing = [k for k in ITEM_FIELDS if k not in item]
                    if missing:
                        problems.append(f"{loc}: {row['file']!r} missing field(s) {missing}")
                    if item.get("status") != row["status"] or str(item.get("priority")) != str(row["priority"]):
                        problems.append(
                            f"{loc}: CSV/JSON drift -- CSV has status={row['status']!r} "
                            f"priority={row['priority']!r}, JSON has status={item.get('status')!r} "
                            f"priority={item.get('priority')!r}"
                        )
            child_path_str = f"{dir_path_str}/{row['id']}" if dir_path_str else row["id"]
            if row["kind"] in CONTAINER_KINDS:
                child_dir = dir_path / row["id"]
                if not (child_dir / DOC_NAME[row["kind"]]).exists():
                    problems.append(f"{loc}: missing {DOC_NAME[row['kind']]} in {child_dir}")
                check_dir(child_dir, child_path_str, row["kind"])

        referenced_top = {row["file"].split("/")[0] for row in rows}
        known = {"_index.csv"} | set(DOC_NAME.values())
        if csv_path.exists():
            for entry in dir_path.iterdir():
                if entry.name in known or entry.name in referenced_top:
                    continue
                problems.append(f"{dir_path_str or '(root)'}: orphan file/dir not referenced by _index.csv: {entry.name}")

    start_kind = "root" if not path_str else dir_kind(node_dir)
    check_dir(node_dir, path_str, start_kind)

    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        print(f"\n{len(problems)} problem(s) found")
        sys.exit(1)
    print("lint clean")


# --------------------------------------------------------------------------- CLI wiring

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kanban.py")
    p.add_argument("--root", default=None, help="override the docs/kanban directory (default: auto-discovered)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create docs/kanban/_index.csv if it doesn't exist yet")

    new_p = sub.add_parser("new", help="create a new epic/feature/story/task")
    new_sub = new_p.add_subparsers(dest="kind", required=True)

    epic_p = new_sub.add_parser("epic")
    epic_p.add_argument("name")
    epic_p.add_argument("--priority", type=int, default=3)
    epic_p.add_argument("--status", default="todo")

    for kind in ("feature", "story"):
        kp = new_sub.add_parser(kind)
        kp.add_argument("parent")
        kp.add_argument("name")
        kp.add_argument("--priority", type=int, default=3)
        kp.add_argument("--status", default="todo")

    task_p = new_sub.add_parser("task")
    task_p.add_argument("parent")
    task_p.add_argument("name")
    task_p.add_argument("--priority", type=int, default=3)
    task_p.add_argument("--status", default="todo")

    status_p = sub.add_parser("status", help="set a node's status")
    status_p.add_argument("path")
    status_p.add_argument("value", choices=VALID_STATUS)

    priority_p = sub.add_parser("priority", help="set a node's priority (1-5)")
    priority_p.add_argument("path")
    priority_p.add_argument("value", type=int)

    body_p = sub.add_parser("body", help="replace a node's body text (from --file, else stdin)")
    body_p.add_argument("path")
    body_p.add_argument("--file", default=None, help="read the new body from this file instead of stdin")

    list_p = sub.add_parser("list", help="list a node's direct children")
    list_p.add_argument("path", nargs="?", default=None)
    list_p.add_argument("--status", default=None, choices=VALID_STATUS)
    list_p.add_argument("--sort", default="priority", choices=["priority", "name", "updated", "created"])

    next_p = sub.add_parser("next", help="what to pick up next, recursively, sorted by priority")
    next_p.add_argument("--under", default=None)
    next_p.add_argument("--top", type=int, default=10)
    next_p.add_argument("--kind", default="task", help="'task' (default), 'all', or a specific kind")

    inprog_p = sub.add_parser("in-progress", help="everything currently in progress, any tier")
    inprog_p.add_argument("--under", default=None)

    tree_p = sub.add_parser("tree", help="pretty-print a subtree")
    tree_p.add_argument("path", nargs="?", default=None)

    show_p = sub.add_parser("show", help="print one node's doc plus its children's status")
    show_p.add_argument("path")

    lint_p = sub.add_parser("lint", help="sanity-check the tree")
    lint_p.add_argument("path", nargs="?", default=None)

    report_p = sub.add_parser("report", help="generate a throwaway, self-contained static HTML report")
    report_p.add_argument("path", nargs="?", default=None, help="scope to a subtree (default: whole tree)")
    report_p.add_argument("--out", default=None, help="output file (default: ./kanban-report.html)")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    root = find_root(Path.cwd(), args.root)

    dispatch = {
        "init": cmd_init,
        "new": cmd_new,
        "status": cmd_status,
        "priority": cmd_priority,
        "body": cmd_body,
        "list": cmd_list,
        "next": cmd_next,
        "in-progress": cmd_in_progress,
        "tree": cmd_tree,
        "show": cmd_show,
        "lint": cmd_lint,
        "report": cmd_report,
    }
    try:
        dispatch[args.command](root, args)
    except KanbanError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
