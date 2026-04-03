# CLI and Operations

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

Run the CLI as `agentflow ...` or `python -m agentflow ...`.

## Templates

List bundled starters:

```bash
agentflow templates
```

Scaffold a starter:

```bash
agentflow init > pipeline.yaml
agentflow init repo-sweep.yaml --template codex-fanout-repo-sweep
agentflow init repo-sweep-batched.yaml --template codex-repo-sweep-batched
agentflow init kimi-smoke.yaml --template local-kimi-smoke
```

The bundled templates are:

- `pipeline`
- `codex-fanout-repo-sweep`
- `codex-repo-sweep-batched`
- `local-kimi-smoke`
- `local-kimi-shell-init-smoke`
- `local-kimi-shell-wrapper-smoke`

## Validate and Inspect

Validate a pipeline:

```bash
agentflow validate examples/pipeline.yaml
```

Inspect the resolved launch plan:

```bash
agentflow inspect examples/pipeline.yaml
agentflow inspect examples/codex-repo-sweep-batched.yaml --output summary
```

## Run

Run a pipeline once:

```bash
agentflow run examples/pipeline.yaml
```

On a terminal, `run` and `inspect` default to a compact summary. When stdout is redirected, they fall back to JSON-oriented output. You can always force a format with `--output`.

## Smoke

Run the bundled local smoke check:

```bash
agentflow smoke
```

Run the same flow through `run`:

```bash
agentflow run examples/local-real-agents-kimi-smoke.yaml --output summary
```

Use the shell-init or shell-wrapper smoke templates when you want the bootstrap wiring spelled out explicitly.
