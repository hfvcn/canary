# Disable CI Build Auto Run

## Goal

Prevent the project's `CI Build` workflow from running automatically on push or pull request events.

## Scope

- Update only the CI build workflow trigger.
- Preserve manual execution through GitHub Actions.
- Do not change docs deployment or release publishing workflows.

## Validation

- Confirm `.github/workflows/ci.yml` no longer contains automatic `push` or `pull_request` triggers.
- Confirm workflow YAML remains parseable.
