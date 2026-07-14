#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
WORKSPACE=${AGENTGUARD_SMOKE_WORKSPACE:-"$REPO_ROOT/.tmp/agentguard-smoke-workspace"}
CASE=${1:-${AGENTGUARD_SMOKE_CASE:-small}}

if [ -z "${DEEPXDR_REAL_NONO:-}" ]; then
  if [ -x "$HOME/.local/bin/nono" ]; then
    DEEPXDR_REAL_NONO="$HOME/.local/bin/nono"
  else
    echo "Set DEEPXDR_REAL_NONO to the real nono binary path before running smoke." >&2
    exit 2
  fi
fi

case "$CASE" in
  small)
    AGENT_COMMAND="cp after/README.md README.md"
    DEFAULT_ORIGINAL_REQUEST="smoke small: update README wording"
    ;;
  medium)
    AGENT_COMMAND="cp after/service.py service.py && cp after/policy.yaml policy.yaml"
    DEFAULT_ORIGINAL_REQUEST="smoke medium: update service logic and policy config"
    ;;
  large)
    AGENT_COMMAND="cp after/generated_policy.json generated_policy.json"
    DEFAULT_ORIGINAL_REQUEST="smoke large: regenerate policy dataset"
    ;;
  agent)
    AGENT_PROMPT="Edit README.md. Add a short section titled Agent Result explaining that this file was modified by a real opencode agent under nono. Keep it concise."
    AGENT_COMMAND="mkdir -p .opencode-runtime/home .opencode-runtime/config .opencode-runtime/cache .opencode-runtime/data .opencode-runtime/state && HOME='$WORKSPACE/.opencode-runtime/home' XDG_CONFIG_HOME='$WORKSPACE/.opencode-runtime/config' XDG_CACHE_HOME='$WORKSPACE/.opencode-runtime/cache' XDG_DATA_HOME='$WORKSPACE/.opencode-runtime/data' XDG_STATE_HOME='$WORKSPACE/.opencode-runtime/state' opencode run --model deepxdr/deepseek-v3-2-251201 --auto '$AGENT_PROMPT'"
    DEFAULT_ORIGINAL_REQUEST="$AGENT_PROMPT"
    ;;
  *)
    echo "Unknown AgentGuard smoke case: $CASE. Expected one of: small, medium, large, agent." >&2
    exit 2
    ;;
esac

export DEEPXDR_NONO_STATE_HOME=${DEEPXDR_NONO_STATE_HOME:-"$REPO_ROOT/.tmp/agentguard-nono-state"}

PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python -m scripts.agentguard_path_policy \
  --workspace "$WORKSPACE" \
  --state-home "$DEEPXDR_NONO_STATE_HOME"

if [ "$CASE" = "agent" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "Set OPENAI_API_KEY before running the real opencode AgentGuard smoke case." >&2
  exit 2
fi

if [ -z "$WORKSPACE" ] || [ "$WORKSPACE" = "/" ]; then
  echo "Refusing to reset unsafe smoke workspace: $WORKSPACE" >&2
  exit 2
fi

rm -rf "$WORKSPACE"
PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python -m scripts.agentguard_smoke_cases "$CASE" "$WORKSPACE" >/dev/null

export DEEPXDR_REAL_NONO
export DEEPXDR_AGENT_ORIGINAL_REQUEST=${DEEPXDR_AGENT_ORIGINAL_REQUEST:-"$DEFAULT_ORIGINAL_REQUEST"}
export DEEPXDR_AGENT_RUN_ID=${DEEPXDR_AGENT_RUN_ID:-"smoke-$CASE-$(date +%Y%m%d%H%M%S)"}
export KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-"localhost:29092"}
export DEEPXDR_AGENT_EVENTS_TOPIC=${DEEPXDR_AGENT_EVENTS_TOPIC:-"events"}
export AGENT_GUARD_DIFF_STORAGE=${AGENT_GUARD_DIFF_STORAGE:-"minio"}
export AGENT_GUARD_DIFF_BUCKET=${AGENT_GUARD_DIFF_BUCKET:-"agent-diffs"}
export AGENT_GUARD_DIFF_PREFIX=${AGENT_GUARD_DIFF_PREFIX:-"smoke"}
export AGENT_GUARD_DIFF_ENDPOINT_URL=${AGENT_GUARD_DIFF_ENDPOINT_URL:-"http://localhost:9000"}
export AGENT_GUARD_DIFF_ACCESS_KEY_ID=${AGENT_GUARD_DIFF_ACCESS_KEY_ID:-"minioadmin"}
export AGENT_GUARD_DIFF_SECRET_ACCESS_KEY=${AGENT_GUARD_DIFF_SECRET_ACCESS_KEY:-"minioadmin"}
export NO_PROXY=${NO_PROXY:-"localhost,127.0.0.1,minio,kafka"}
export no_proxy=${no_proxy:-"$NO_PROXY"}

printf 'Running nono smoke case=%s in %s with run_id=%s\n' "$CASE" "$WORKSPACE" "$DEEPXDR_AGENT_RUN_ID"
(
  cd "$WORKSPACE"
  if [ "$CASE" = "agent" ]; then
    "$REPO_ROOT/scripts/nono" run --profile always-further/opencode --allow-domain "https://ark.cn-beijing.volces.com/**" --rollback --no-rollback-prompt --rollback-exclude .opencode-runtime --rollback-exclude opencode --rollback-exclude opentui --allow "$WORKSPACE" -- \
      /bin/sh -c "$AGENT_COMMAND"
  else
    "$REPO_ROOT/scripts/nono" run --rollback --no-rollback-prompt --allow "$WORKSPACE" -- \
      /bin/sh -c "$AGENT_COMMAND"
  fi
)

printf '\nSmoke nono command finished. Open http://localhost:30003 and check Agent Guard Sessions.\n'
