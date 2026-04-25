# Data Persistence Guidelines

> How data is stored and queried in this project.

---

## Overview

This project uses **no ORM or external database**. All persistence is file-based: JSON files, JSONL append-only logs, and YAML plan files. The `CCCC_HOME` directory (resolved in `src/cccc/paths.py`) is the storage root.

---

## Persistence Patterns

### 1. Append-only JSONL Ledger

The primary event store is an append-only JSONL ledger (`src/cccc/kernel/ledger.py`). Every domain event is serialized as one JSON line.

```python
# Writing events (src/cccc/kernel/ledger.py)
append_event(ledger_path, *, kind="...", group_id="...")

# Reading events
read_last_lines(path, n=100)
follow(path, *, sleep_seconds=0.2)   # tail-follow, yields JSONL lines
```

- Never modify existing lines — append only
- Compaction and snapshotting via `kernel/ledger_retention.py`
- Cursor-based reading for consumers (`kernel/inbox.py`)

### 2. JSON Entity Files

Groups, actors, and settings are stored as individual JSON files managed by kernel modules:

```python
# src/cccc/kernel/group.py
create_group(reg, *, title, topic="")   # writes JSON file, returns Group
load_group(group_id)                     # reads JSON file
update_group(reg, group, *, patch={})    # read-modify-write

# src/cccc/kernel/actors.py
add_actor(group, *, actor_id, title="", ...)
list_actors(group)
```

### 3. YAML/JSON Plan Files (Ralph)

Ralph plan files use YAML or JSON and are parsed via `src/cccc/ralph/plan_io.py`:

```python
data = _parse_raw_data(path)       # auto-detects YAML vs JSON by extension
plan = Plan.model_validate(data)   # validated through Pydantic v2
```

---

## Data Modeling

All structured data uses **Pydantic v2 BaseModel** (`pydantic>=2.0,<3.0`).

### Contracts (wire format)

Located in `src/cccc/contracts/v1/`. Use `ConfigDict(extra="forbid")` to reject unknown fields:

```python
# src/cccc/contracts/v1/event.py
class GroupCreateData(BaseModel):
    title: str
    topic: str = ""
    model_config = ConfigDict(extra="forbid")
```

### Domain models

Located alongside their domain module (e.g., `src/cccc/ralph/models.py`):

```python
class Plan(BaseModel):
    ...
class ValidationReport(BaseModel):
    ...
class ValidationIssue(BaseModel):
    ...
```

---

## File Locking

When concurrent access is possible, use advisory file locks via `src/cccc/util/file_lock.py`:

```python
from cccc.util.file_lock import acquire_lockfile, release_lockfile, LockUnavailableError

lock = acquire_lockfile(path, blocking=True)  # blocks until available
try:
    # ... do work ...
finally:
    release_lockfile(lock)
```

---

## Forbidden Patterns

| Pattern | Why |
|---------|-----|
| SQLite or any external database | Architecture is file-based; no DB driver in dependencies |
| Direct `open()` for entity CRUD | Use kernel module functions which handle path resolution and locking |
| Mutating existing JSONL ledger lines | Ledger is append-only by design |
| `json.dump` without `ensure_ascii=False` | Project uses UTF-8 throughout |
| `pydantic<2.0` patterns (`class Config:`) | Project uses Pydantic v2 `ConfigDict` |
