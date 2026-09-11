# AI Agent Rules

## 1. Core Principle

Before writing or modifying code, understand the existing codebase first. The existing architecture, conventions, patterns, and implementation style are the source of truth — not general best practices, not the agent's own preferences, not what would be "better" in a greenfield project. Do not introduce a new pattern when an existing project pattern can be reused. **New code must match the surrounding codebase's patterns and style exactly — same structure, same idioms, same conventions — not merely "similar" or "inspired by."** When a requested change conflicts with an existing convention, flag the conflict and ask rather than silently picking one side.

## 2. Before Writing Code

Always:

- Inspect the relevant files and surrounding implementation before touching anything.
- Understand how the existing feature works, including edge cases already handled.
- Identify existing utilities, services, components, middleware, and patterns that can be reused.
- Check related database models, APIs, and frontend/backend flows.
- Identify dependencies and possible side effects — what else imports or calls this code.
- Check for existing tests covering the area, and read them before changing behavior they assert on.
- Form a clear implementation plan before making changes.

Do not start coding based only on assumptions. If a file, API, or behavior can't be verified by inspection, say so explicitly instead of guessing.

## 3. Codebase Consistency

All new code must be indistinguishable in style from the existing codebase — it should read as if the same author, following the same conventions, wrote it. Match, exactly, the existing:

- Folder structure
- Naming conventions
- Type conventions
- API patterns
- Database patterns
- Error handling
- Validation
- Logging
- Testing patterns
- Component patterns
- State management patterns
- Formatting and style (indentation, quote style, import ordering, comment style)

Do not introduce unnecessary frameworks, libraries, abstractions, or architectural patterns. If two conflicting patterns already exist in the codebase, match whichever the immediate surrounding code uses rather than inventing a third. If no existing pattern covers the case, say so explicitly and propose the closest fit before writing code — don't invent a new convention silently.

## 4. Simplicity — Do Not Over-Engineer

Prefer: simple over clever, explicit over overly abstract, reusable over duplicated, maintainable over prematurely optimized.

Match the size of the solution to the size of the problem. If a task can be solved in 2 lines, write 2 lines — not a 50-line abstraction with configs, helper classes, or "future-proofing" no one asked for. Do not add layers, wrappers, design patterns, or generalized utilities for a single, simple use case. Only introduce an abstraction when there is a clear reason for it — a real second use case, not a hypothetical future one. Before writing a solution, ask: what's the smallest change that correctly and durably solves exactly what was requested, in the codebase's existing style? Write that.

## 5. Security

Security is a default requirement. Never:

- Expose secrets or credentials, including in logs, error messages, commit history, or example/config files.
- Log passwords, tokens, MFA secrets, API keys, session identifiers, or other sensitive data.
- Disable security controls to make implementation easier.
- Trust client-side authorization; always re-check on the server/backend.
- Bypass existing authentication or authorization, even temporarily "for testing."
- Introduce insecure cryptographic implementations, or roll custom crypto where a vetted library exists.
- Store or transmit sensitive authentication data insecurely.
- Introduce injection risks (SQL, command, template, XSS) — always use parameterized queries and existing sanitization utilities.

Use established security libraries and existing project security patterns whenever possible. If a task seems to require weakening a security control, stop and flag it instead of proceeding.

## 6. Changes

Keep changes focused on the requested task. Do not modify unrelated code, reformat untouched files, or fix unrelated bugs in the same change — note them separately instead. Do not perform large refactors unless they are required for the requested feature. Prefer small, understandable changes over large rewrites. Prefer existing dependencies already used in the project over adding new ones; don't add a dependency for something a few lines of code, written in the codebase's own style, already handles.

## 7. Database Changes

Before changing the database:

- Inspect the existing schema.
- Follow existing naming and relationship conventions exactly.
- Consider migrations and existing data — will this change break current rows or in-flight queries?
- Avoid unnecessary schema changes.
- Keep database logic consistent with the existing architecture and query patterns already in use.

Never make destructive database changes without a clear, explicit requirement to do so.

## 8. Error Handling

Follow the existing error-handling strategy exactly — don't introduce a new error shape, exception type, or response format even if it seems cleaner. Errors should:

- Be predictable and consistent with how errors are already surfaced elsewhere in the codebase.
- Avoid leaking sensitive information (stack traces, internal paths, credentials) to end users.
- Be handled at the appropriate layer, not swallowed early or re-thrown without context.
- Follow existing API response conventions (status codes, error object shape).

Do not silently ignore errors.

## 9. Testing and Verification

After implementing a change:

- Run relevant tests.
- Run type checking.
- Run linting.
- Run relevant security/static analysis.
- Review the final diff line by line.
- Fix issues before considering the task complete.

Do not assume code works without verification. If a check can't be run in the current environment, say so explicitly rather than assuming it passed or fabricating a result.

## 10. Agent Workflow

Sequence for every change: **Understand → Plan → Implement → Verify → Review.**

When uncertain, inspect the repository before making assumptions — never guess at a file's contents, an API's shape, or a convention's existence. Reuse existing code whenever appropriate. Do not create duplicate implementations of functionality that already exists. Do not change architecture simply because another approach looks better in isolation — the existing architecture is the constraint, not a suggestion. If a request is ambiguous or could be implemented multiple reasonable ways, state the interpretation being used before proceeding, and prefer whichever interpretation keeps the change closest to existing patterns.

## 11. Final Review

Before finishing a task, verify:

- The requested functionality works.
- Existing functionality still works.
- The new code is stylistically identical to the surrounding codebase — no visible seam between old and new code.
- No unnecessary files were changed.
- No unnecessary dependencies were added.
- No security controls were weakened.
- Code follows existing conventions exactly, not approximately.
- Tests and checks pass.
- The implementation is understandable to another developer already familiar with this codebase.
- The solution isn't bigger than the problem it solves.

The final implementation should be: **secure, reliable, consistent, simple, maintainable — and indistinguishable in style from the code it sits beside.**
