#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_PATH="${TARGET_PATH:-$ROOT_DIR}"
GROUP_TITLE="${GROUP_TITLE:-smoke-headless}"
GROUP_TOPIC="${GROUP_TOPIC:-headless cli smoke}"
ACTOR_ID="${ACTOR_ID:-smoke-actor}"
ACTOR_TITLE="${ACTOR_TITLE:-Smoke Actor}"
ACTOR_COMMAND="${ACTOR_COMMAND:-python3 -c 'import time; print(\"smoke actor online\", flush=True); time.sleep(30)'}"
SEND_TEXT="${SEND_TEXT:-headless smoke message}"
POLL_RETRIES="${POLL_RETRIES:-10}"
POLL_INTERVAL="${POLL_INTERVAL:-1}"
KEEP_HOME="${KEEP_HOME:-0}"

AUTO_HOME=0
if [[ -n "${CCCC_HOME:-}" ]]; then
  SMOKE_HOME="$CCCC_HOME"
else
  SMOKE_HOME="$(mktemp -d "${TMPDIR:-/tmp}/cccc-smoke.XXXXXX")"
  AUTO_HOME=1
fi
export CCCC_HOME="$SMOKE_HOME"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

GROUP_ID=""

# Smoke contract:
# cccc daemon start
# cccc group create
# cccc attach
# cccc actor add
# cccc group start
# cccc send
# cccc actor list
# cccc inbox
# cccc tail

note() {
  printf '\n[%s] %s\n' "smoke" "$*"
}

fail() {
  printf '\n[smoke] FAIL: %s\n' "$*" >&2
  exit 1
}

cccc() {
  local bin=""
  bin="$(type -P cccc || true)"
  if [[ -n "$bin" ]]; then
    "$bin" "$@"
    return
  fi
  python3 -m cccc.cli.main "$@"
}

run_json() {
  local out
  if ! out="$("$@" 2>&1)"; then
    printf '%s\n' "$out" >&2
    return 1
  fi
  printf '%s' "$out"
}

json_assert_ok() {
  python3 - "$1" <<'PY'
import json
import sys

obj = json.loads(sys.argv[1])
if not isinstance(obj, dict) or obj.get("ok") is not True:
    raise SystemExit(1)
PY
}

json_get() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

obj = json.loads(sys.argv[1])
path = [segment for segment in sys.argv[2].split(".") if segment]
for segment in path:
    if isinstance(obj, dict):
        obj = obj.get(segment)
    elif isinstance(obj, list) and segment.isdigit():
        idx = int(segment)
        obj = obj[idx] if 0 <= idx < len(obj) else None
    else:
        obj = None
        break
if obj is None:
    raise SystemExit(1)
if isinstance(obj, (dict, list)):
    print(json.dumps(obj, ensure_ascii=False))
else:
    print(obj)
PY
}

json_assert_actor_present() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

obj = json.loads(sys.argv[1])
actor_id = sys.argv[2]
actors = (((obj.get("result") or {}).get("actors")) if isinstance(obj, dict) else None) or []
for item in actors:
    if isinstance(item, dict) and str(item.get("id") or "").strip() == actor_id:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

json_assert_inbox_contains_text() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

obj = json.loads(sys.argv[1])
target = sys.argv[2]
messages = (((obj.get("result") or {}).get("messages")) if isinstance(obj, dict) else None) or []
for item in messages:
    if not isinstance(item, dict):
        continue
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    text = str(data.get("text") or "")
    if text == target:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

json_assert_group_running() {
  python3 - "$1" <<'PY'
import json
import sys

obj = json.loads(sys.argv[1])
group = (((obj.get("result") or {}).get("group")) if isinstance(obj, dict) else None) or {}
if bool(group.get("running")):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

cleanup() {
  if [[ -n "$GROUP_ID" ]]; then
    cccc group stop --group "$GROUP_ID" --by user >/dev/null 2>&1 || true
  fi
  cccc daemon stop >/dev/null 2>&1 || true

  if [[ "$AUTO_HOME" == "1" && "$KEEP_HOME" != "1" ]]; then
    rm -rf "$SMOKE_HOME"
  else
    printf '[smoke] retained CCCC_HOME=%s\n' "$SMOKE_HOME"
  fi
}
trap cleanup EXIT

wait_for_group_running() {
  local show_json attempt
  for ((attempt = 1; attempt <= POLL_RETRIES; attempt++)); do
    show_json="$(run_json cccc group show "$GROUP_ID")" || true
    if [[ -n "$show_json" ]] && json_assert_group_running "$show_json"; then
      return 0
    fi
    sleep "$POLL_INTERVAL"
  done
  return 1
}

wait_for_inbox_message() {
  local inbox_json attempt
  for ((attempt = 1; attempt <= POLL_RETRIES; attempt++)); do
    inbox_json="$(run_json cccc inbox --actor-id "$ACTOR_ID" --group "$GROUP_ID" --limit 20)" || true
    if [[ -n "$inbox_json" ]] && json_assert_inbox_contains_text "$inbox_json" "$SEND_TEXT"; then
      printf '%s' "$inbox_json"
      return 0
    fi
    sleep "$POLL_INTERVAL"
  done
  return 1
}

note "starting daemon under CCCC_HOME=$SMOKE_HOME"
cccc daemon start >/dev/null

note "creating group"
group_create_json="$(run_json cccc group create --title "$GROUP_TITLE" --topic "$GROUP_TOPIC")" \
  || fail "group create failed"
json_assert_ok "$group_create_json" || fail "group create returned non-ok"
GROUP_ID="$(json_get "$group_create_json" "result.group_id")" || fail "group create did not return group_id"

note "attaching scope $TARGET_PATH"
attach_json="$(run_json cccc attach "$TARGET_PATH" --group "$GROUP_ID")" || fail "attach failed"
json_assert_ok "$attach_json" || fail "attach returned non-ok"

note "adding actor $ACTOR_ID"
actor_add_json="$(run_json cccc actor add "$ACTOR_ID" --group "$GROUP_ID" --title "$ACTOR_TITLE" --runtime custom --command "$ACTOR_COMMAND" --submit none)" \
  || fail "actor add failed"
json_assert_ok "$actor_add_json" || fail "actor add returned non-ok"

note "starting group"
group_start_json="$(run_json cccc group start --group "$GROUP_ID" --by user)" || fail "group start failed"
json_assert_ok "$group_start_json" || fail "group start returned non-ok"
wait_for_group_running || fail "group did not reach running=true after start"

note "listing actors"
actor_list_json="$(run_json cccc actor list --group "$GROUP_ID")" || fail "actor list failed"
json_assert_ok "$actor_list_json" || fail "actor list returned non-ok"
json_assert_actor_present "$actor_list_json" "$ACTOR_ID" || fail "actor list missing $ACTOR_ID"

note "sending directed message"
send_json="$(run_json cccc send "$SEND_TEXT" --group "$GROUP_ID" --to "$ACTOR_ID" --by user)" || fail "send failed"
json_assert_ok "$send_json" || fail "send returned non-ok"

note "checking inbox delivery"
inbox_json="$(wait_for_inbox_message)" || fail "message did not appear in inbox"
json_assert_ok "$inbox_json" || fail "inbox returned non-ok"

note "checking ledger tail"
tail_output="$(cccc tail --group "$GROUP_ID" -n 20)" || fail "tail failed"
printf '%s\n' "$tail_output" | grep -F "$SEND_TEXT" >/dev/null || fail "tail missing sent message"

note "smoke passed"
printf '[smoke] group_id=%s actor_id=%s\n' "$GROUP_ID" "$ACTOR_ID"
printf '[smoke] OK: headless create/attach/add/start/send/inbox/tail path verified\n'
