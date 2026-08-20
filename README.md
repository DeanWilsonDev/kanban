# kanban

A tiered Epic → Feature → User Story → Task backlog, stored as small self-contained JSON records
plus small CSV indexes, queried through a script instead of read as prose.

Built to replace a `docs/next_steps.md`-style running backlog doc: those work fine until they
grow into thousands of lines of narrative, at which point every "what's open" check means
reading a large chunk of the file. This system answers "what's next" and "what's in progress" by
running a script against small CSVs — no file in the tree should ever need to grow past a single
task's own write-up. Storing each item as JSON rather than prose also means the tree is
machine-ingestable for free: concatenate every item's JSON file (e.g. with Amanuensis) into one
array and hand it to a dashboard or any other downstream tool, no markdown parsing required.

## Layout

```
docs/kanban/_index.csv                              # children: epic
docs/kanban/<epic>/epic.json
docs/kanban/<epic>/_index.csv                        # children: feature | task
docs/kanban/<epic>/<feature>/feature.json
docs/kanban/<epic>/<feature>/_index.csv              # children: story | task
docs/kanban/<epic>/<feature>/<story>/story.json
docs/kanban/<epic>/<feature>/<story>/_index.csv      # children: task only
docs/kanban/<epic>/<feature>/<story>/<task>.json      # leaf -- plain file, no directory
```

A directory's own tier is whichever of `epic.json`/`feature.json`/`story.json` it holds — no
separate marker file. An epic or feature may hold `task` rows directly (skipping a tier that
doesn't earn its keep for a small effort).

Every `_index.csv` shares one schema:

```
id,kind,name,status,priority,file,created,updated
```

- `status`: `todo` | `in-progress` | `complete`
- `priority`: `1`-`5`, independent per node (never inherited from its parent) — `1` critical/must,
  `2` high/should, `3` medium/normal (the default), `4` low/nice-to-have, `5` trivial/someday.
  Most items will land on `1`-`3`.
- `file`: path relative to that CSV's own directory

Every item's own `.json` file is a **self-contained record** — it mirrors the same metadata the
CSV row has, plus the write-up itself:

```json
{
  "id": "...", "path": "...", "kind": "task", "name": "...",
  "status": "todo", "priority": 2, "parent": "...",
  "created": "2026-08-20", "updated": "2026-08-20",
  "body": "markdown-formatted prose, one string"
}
```

The CSV stays the fast index scripts use for listing/sorting/filtering without opening every
file. `kanban.py status`/`priority`/`new` write the CSV row and the JSON record's mirrored fields
in the same call, so the two can't drift as long as everything goes through this script — `lint`
also checks the CSV and JSON agree, in case something edited a file directly.

## CLI

```
kanban.py init
kanban.py new epic "<name>" [--priority N]
kanban.py new feature <epic-path> "<name>" [--priority N]
kanban.py new story <feature-path> "<name>" [--priority N]
kanban.py new task <parent-path> "<name>" [--priority N] [--status todo]
kanban.py status <path> <todo|in-progress|complete>
kanban.py priority <path> <1-5>
kanban.py body <path> [--file <path>]              # replaces body; reads stdin if --file omitted
kanban.py list [<path>] [--status X] [--sort priority|name|updated|created]
kanban.py next [--under <path>] [--top N] [--kind task|all|<kind>]
kanban.py in-progress [--under <path>]
kanban.py tree [<path>]
kanban.py show <path>
kanban.py lint [<path>]
kanban.py report [<path>] [--out FILE]              # throwaway static HTML report, default ./kanban-report.html
```

`report` renders every epic as a swim lane in one self-contained HTML file — click into any
feature/story/task to read its body, a "hide complete" toggle is on by default, and a search box
filters by name/body text and auto-expands matches. Open it directly in a browser
(`file://...`), no server needed; regenerate and throw away, it's not meant to be committed.

`--root` overrides the auto-discovered `docs/kanban` directory (found by walking up from `cwd`).

Paths are `/`-joined slugs relative to `docs/kanban/`, e.g.
`nyx-native-application/phase-2-cpp-collapse/2e-nativenoderef-elimination`.

## Install as a plugin

Add to the consuming repo's `.claude/settings.json`:

```json
"enabledPlugins": { "kanban@kanban": true },
"extraKnownMarketplaces": {
  "kanban": { "source": { "source": "directory", "path": "/absolute/path/to/kanban" } }
}
```

See `skills/kanban/SKILL.md` for day-to-day usage and `skills/kanban-migrate/SKILL.md` for
folding an existing `next_steps.md`-style doc into this structure.

## Tests

```
python3 -m unittest tests.test_kanban -v
```
