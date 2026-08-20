---
name: kanban
description: Query and update this repo's tiered Epic/Feature/Story/Task backlog (docs/kanban/) through the kanban.py script instead of reading next_steps.md-style prose. Use whenever you need to find what to work on next, check what's in progress, log newly-discovered work, or update a task's status/priority.
---

# Kanban: a scripted backlog, not a doc to read

This repo tracks its backlog as a tiered tree — **Epic → Feature → User Story → Task** — under
`docs/kanban/`, instead of a running prose doc. Every level's own `_index.csv` is a small,
scriptable index; every item's own `.json` file is a self-contained record (id/kind/name/status/
priority/parent/dates plus a `body` write-up), machine-ingestable on its own — that's also what
lets this tree feed a dashboard or any other downstream tool for free (concatenate every item's
JSON, e.g. with Amanuensis). **The entire point of this system is that you never need to read
more than one item's `.json` file, or one directory's `_index.csv`, to answer a question.** Don't
`grep`/`cat`/`find` across `docs/kanban/` wholesale —
that reintroduces the exact "read thousands of lines to find one fact" problem this system
replaced. Always go through the script below.

Locate it via `$CLAUDE_PLUGIN_ROOT/scripts/kanban.py` (falls back to a repo-local
`.claude/skills/kanban/scripts/kanban.py`-style path if this skill was copied in rather than
installed as a plugin — check what actually exists before assuming).

## When the human wants an overview, not you

If the ask is for the human to review the board themselves (not "what should I work on"), skip
the query loop below and run `... report [--out FILE]` instead — it writes one throwaway,
self-contained HTML file (swim lanes per Epic, click-to-expand down to Tasks, a "hide complete"
toggle, a search box) they can open directly in a browser and read on their own, faster than
relaying the same information as chat text. It's meant to be regenerated and discarded, not
committed. Point them at the file path; don't paste its contents back into the conversation.

## The loop

1. **Check what's already in flight**: `python3 "$CLAUDE_PLUGIN_ROOT/scripts/kanban.py" in-progress`.
   If something's there, that's almost always what to keep working on — an in-progress item at
   any tier (not just a Task) is meaningful.
2. **Otherwise, check what's next**: `... next --top 5` (defaults to Tasks — the actual unit of
   work — sorted by priority, ties broken by creation date). Add `--under <epic-or-feature-path>`
   to scope it to one area, or `--kind all` to see every tier.
3. **Before starting real work on an item**: `... status <path> in-progress`.
4. **Read the item's own context**: `... show <path>` — prints the item's own metadata plus its
   `body` write-up, and (if it's a container) a table of its own children's status. This is the
   one file you actually read.
5. **If you discover new work mid-task** (a follow-up, a bug found along the way, a scope cut):
   log it immediately as a new Task rather than letting it live only in conversation —
   `... new task <parent-path> "<name>" --priority N`. Pick the parent that already exists closest
   to where the work belongs (the current Story/Feature/Epic); don't invent a new Epic for a small
   follow-up.
6. **When done**: fold anything genuinely load-bearing (a root cause, a commit hash, a benchmark
   number, an explicit scope cut) into the item's own `body` — `... body <path>` replaces it
   (reads new text from `--file <path>`, or stdin if omitted; it's a full replace, so include the
   existing body text too if you're appending rather than rewriting) — same "don't lose it" bar a
   good commit message or the old archive followed. Then `... status <path> complete`. You should
   never need to re-read a completed item afterward; that's fine and intended.

## Priority (1-5, independent per node)

Each item's `priority` is set once at creation and lives only on that item — never inherited or
computed from its parent, and never renumbered as siblings come and go (that's the whole point of
a small bounded scale instead of a unique rank/index). Rough meaning:

| Priority | Meaning |
|---|---|
| 1 | Critical / must — the project (or this Epic) isn't done without it |
| 2 | High / should — real, not optional, but not blocking |
| 3 | Medium / normal — the default if you're not sure |
| 4 | Low / nice-to-have |
| 5 | Trivial / someday |

Most items land on 1-3. `next` sorts purely by the *item's own* priority (then creation date) —
it does not weight by the parent Epic's priority. It's expected and fine for a priority-1 Task in
one Epic to surface ahead of a priority-1 Task in a different, "more important" Epic, or vice
versa — priority is set per-item precisely so this doesn't need a composite formula.

## Creating new tiers

- **Epic**: a large, multi-session effort (the old doc's own top-level "Open items" bullets are
  roughly epic-sized). `new epic "<name>" --priority N`.
- **Feature**: a distinct phase or slice of an Epic. `new feature <epic-path> "<name>" --priority N`.
- **User Story**: a further breakdown within a Feature, only when the Feature is big enough to
  need it — small Features can hold `task`s directly instead. `new story <feature-path> "<name>"
  --priority N`.
- **Task**: the actual unit of work — the thing that gets marked `in-progress`/`complete`. Can
  attach directly to an Epic, a Feature, or a Story, whichever is the closest real container.
  `new task <parent-path> "<name>" --priority N`.

Don't force every Epic through all four tiers — a small, self-contained effort can be an Epic with
Tasks straight underneath it.

## Sanity-check after any bulk edit

`... lint [<path>]` — checks every CSV row's file exists, every container has its doc file, ids
are unique per directory, `status`/`priority`/`kind` values are valid, and flags files on disk
that no CSV row references. Run this after migrating content in, or after any manual edit to a
CSV (which should be rare — prefer the script's own mutating commands).
