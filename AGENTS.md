# AI Agent Rules

## 1. Core Principle

Understand the existing codebase before writing or modifying anything. The existing
architecture, conventions, and style are the source of truth — not general best practices, not
the agent's own preferences. Reuse existing patterns instead of introducing new ones. New code
must match the surrounding code's structure, idioms, and conventions exactly — not "similar,"
identical. If a request conflicts with an existing convention, flag it and ask rather than
silently picking a side.

## 2. Before Writing Code

- Inspect the relevant files and surrounding implementation first.
- Understand how the feature currently works, including edge cases already handled.
- Identify existing utilities, services, and patterns to reuse.
- Check related models, APIs, and data flows, plus what else imports or calls this code.
- Read existing tests covering the area before changing behavior they assert on.
- Form a clear plan before making changes.

Never code from assumptions. If a file or behavior can't be verified by inspection, say so
instead of guessing.

## 3. Codebase Consistency

New code should read as if the same author wrote it. Match exactly: folder structure, naming,
types, API and database patterns, error handling, validation, logging, testing, component and
state-management patterns, and formatting (indentation, quotes, import order, comment style).

Don't introduce new frameworks, libraries, or abstractions the codebase doesn't already use. If
two conflicting patterns already exist, match whichever the immediate surrounding code uses. If
no existing pattern fits, say so and propose the closest match before writing code — don't
invent a convention silently.

## 4. Simplicity — Don't Over-Engineer

Simple over clever. Explicit over abstract. Match the size of the solution to the size of the
problem — a 2-line fix stays 2 lines, not a new abstraction, config layer, or "future-proofing"
nobody asked for. Only add an abstraction when there's a real second use case, not a
hypothetical one. Ask: what's the smallest change that correctly and durably solves exactly
what was requested, in the codebase's existing style? Write that.

## 5. Security

Never:
- Expose secrets/credentials in logs, errors, commits, or config/example files.
- Log passwords, tokens, MFA secrets, API keys, or session identifiers.
- Disable security controls, bypass auth (even "temporarily"), or trust client-side authorization.
- Roll custom crypto where a vetted library exists.
- Introduce injection risk — always use parameterized queries and existing sanitization.

Use the project's existing security patterns and libraries. If a task seems to require
weakening a security control, stop and flag it instead of proceeding.

## 6. Scope of Changes

Keep changes focused on the requested task. Don't modify unrelated code, reformat untouched
files, or fix unrelated bugs in the same change — note them separately. Avoid large refactors
unless the requested feature requires one. Prefer an existing dependency already in the project
over adding a new one for something a few lines of code can handle.

## 7. Database Changes

Inspect the existing schema first. Follow existing naming/relationship conventions exactly.
Check whether the change breaks current rows or in-flight queries. Avoid unnecessary schema
changes. Never make a destructive database change without an explicit requirement for it.

## 8. Error Handling

Follow the existing error-handling strategy exactly — same exception types, same response
shape — even if a different approach seems cleaner. Errors must be predictable, consistent with
the rest of the codebase, and free of leaked internals (stack traces, paths, credentials).
Handle errors at the right layer; never swallow or silently ignore them.

## 9. Testing and Verification

After implementing a change: run relevant tests, type checking, linting, and any relevant
static analysis; review the final diff line by line; fix issues before calling the task done.
Never assume code works without verification, and never fabricate a passing result — if a check
can't be run in the current environment, say so explicitly.

## 10. Comments

Keep comments where they explain *why*, not *what* — preserve existing comments unless they're
now wrong, and add new ones only where the surrounding code's own commenting style already
would (e.g. non-obvious logic, safety-critical checks, workarounds). Don't strip comments
during unrelated edits, and don't add comment noise the existing style doesn't have.

## 11. Workflow

Sequence for every change: **Understand → Plan → Implement → Verify → Review.**

Inspect before assuming — never guess at a file's contents, an API's shape, or a convention.
Don't duplicate existing functionality. Don't change architecture because another approach
looks better in isolation — the existing architecture is the constraint. If a request is
ambiguous, state the interpretation being used before proceeding, favoring whichever keeps the
change closest to existing patterns.

## 12. Codebase Location & Per-Person Changelog

The codebase should always follow the guidenlines of the `/ponytail` skills, if it isnt downloaded, download it from the github and start to use it, code should be written using that skill . All new code must match the conventions of what's already
there (per Sections 1–4) — nothing about this location relaxes those rules.

At the end of any task that changes code, record what changed under that person's own folder:

- Path: `/changelog/<person-name>/changelog.md`
- If that person's folder doesn't exist yet, create it.
- Append an entry (don't overwrite prior entries) with: date, a short summary of what changed
  and why, and the files touched.
- This is separate from commit messages/PR descriptions — it's a running per-person log, not a
  replacement for either.

## 13. Final Review

Before finishing, verify: the requested functionality works; existing functionality still
works; the new code is stylistically identical to its surroundings, with no visible seam;
comments were preserved/added per Section 10; no unnecessary files or dependencies were
touched; no security control was weakened; tests and checks pass; the per-person changelog
entry (Section 12) was written; the solution isn't bigger than the problem it solves.

The final implementation should be: **secure, reliable, consistent, simple, maintainable — and
indistinguishable in style from the code it sits beside.**