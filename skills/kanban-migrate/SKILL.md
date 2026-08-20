---
name: kanban-migrate
description: One-off migration of an existing running backlog doc (e.g. docs/next_steps.md, plus any docs/archive/*_resolved.md companion) into this repo's docs/kanban/ tiered tree. Use when asked to convert, migrate, or move a next_steps.md-style doc onto the kanban system.
---

# Migrating a next_steps.md-style doc into docs/kanban/

This is judgment work, not a mechanical dump — read the whole source doc first, the same way
`next-steps-assess`/`audit-docs` would, before creating anything.

## 1. Read the whole live doc (and skim the archive)

Read the doc's current "Open items" (or equivalent) section in full. For the archive companion,
you don't need to read it line-by-line if it's large — you already have enough context on what
each already-condensed "Open items" entry says was archived (section pointers like "§7d/7e"); the
goal is a short summary + pointer, not a transcription.

## 2. Map structure, don't invent it

- Each top-level "Open items" bullet is usually **Epic-sized**. Give it a real Epic.
- If the doc's own prose already has a natural phase/sub-effort breakdown (the source docs this
  was designed against often do — "Phase 1", "Phase 2a/2b", etc.), map those onto **Features**,
  and a further breakdown onto **Stories** — but only where the prose already earns it. Don't
  invent a Story tier for a flat, single-thread piece of work; attach its Tasks straight to the
  Feature (or Epic) instead.
- Every "genuinely still open" item the doc calls out becomes its own **Task**, `status=todo` (or
  `in-progress` if the doc frames it as actively being worked when the migration happens).
  Preserve the *exact* blocking reason and any concrete next-step text in the Task's own `body` —
  this is the one thing that must not get lost in the move.
- Priority: use the doc's own framing as a signal (something called out as blocking/critical →
  `1`-`2`; a documented, deliberate scope cut with no urgency → `3`-`4`; a "someday, not asked
  for" aside → `5`). Don't default everything to `3` just to move fast — the whole point of this
  system is that priority actually means something when you run `next`.

## 3. Resolved/"Done" history — condense, don't transcribe

For content the source doc already marks resolved/done/superseded: **do not create one Task per
historical paragraph.** Create one `complete` stub entry per already-finished phase or milestone
(matching whatever granularity the live doc itself already condensed things to), with a short
body: what shipped, the load-bearing facts worth keeping (a benchmark number, the commit that
landed it, a root cause worth remembering if the same bug shape recurs), and a plain-text pointer
back at the archive file's own section for the full narrative. This mirrors the "condense, don't
duplicate" bar the `audit-docs` skill already holds itself to — a `complete` item nobody will ever
need to read in full is not worth spending effort transcribing in full.

## 4. Build it

Use `kanban.py new epic|feature|story|task` (see the `kanban` skill) for every node — don't
hand-write CSV rows or JSON files directly, so the schema stays correct by construction. `new`
creates the record with an empty `body`; follow it with `kanban.py body <path> --file <tmpfile>`
(or piped via stdin) to set the real write-up once you've drafted it.

## 5. Verify

- `kanban.py lint` — must be clean.
- `kanban.py tree` and `kanban.py next --top 5` — read the output and sanity-check it against
  what a human would actually expect to see next; if something's obviously missing or
  misprioritized, fix it now rather than after the fact.

## 6. Leave the source doc alone

Don't delete or rewrite the original `next_steps.md`/archive — leave them in place as frozen
historical record (the same treatment already given to older legacy docs in most of these repos).
Add one short, dated line at the top of the live doc noting it's superseded by `docs/kanban/`.
