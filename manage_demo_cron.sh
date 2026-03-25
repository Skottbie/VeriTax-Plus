#!/usr/bin/env bash
# manage_demo_cron.sh — schedule/clear one-shot Demo cron ticks for VeriTax

set -euo pipefail

for BIN_DIR in "${HOME}/.local/share/pnpm" "${HOME}/.npm-global/bin" "${HOME}/.local/bin"; do
    if [ -d "${BIN_DIR}" ]; then
        case ":${PATH}:" in
            *":${BIN_DIR}:"*) : ;;
            *) PATH="${PATH}:${BIN_DIR}" ;;
        esac
    fi
done
export PATH

OPENCLAW_BIN="${OPENCLAW_BIN:-}"
if [ -z "${OPENCLAW_BIN}" ]; then
    if command -v openclaw >/dev/null 2>&1; then
        OPENCLAW_BIN="$(command -v openclaw)"
    elif [ -x "${HOME}/.local/share/pnpm/openclaw" ]; then
        OPENCLAW_BIN="${HOME}/.local/share/pnpm/openclaw"
    else
        echo "❌ openclaw binary not found" >&2
        exit 1
    fi
fi

STATE_DIR="${TMPDIR:-/tmp}/veritax-demo"
SCAN_JOB_ID_FILE="${STATE_DIR}/demo_scan_job_id"
MONITOR_JOB_ID_FILE="${STATE_DIR}/demo_monitor_job_id"
ARCHIVE_JOB_ID_FILE="${STATE_DIR}/demo_archive_job_id"
AGENT_STATE_FILE="${STATE_DIR}/agent_state.json"
DEFAULT_DELAY="20s"
DELIVERY_CHANNEL="${VERITAX_DEMO_CHANNEL:-telegram}"
DELIVERY_DEST="${VERITAX_DEMO_TO:-}"
SCAN_JOB_NAME="veritax-demo-daily-scan"
MONITOR_JOB_NAME="veritax-demo-monitor"
ARCHIVE_JOB_NAME="veritax-demo-archive"

mkdir -p "${STATE_DIR}"

remove_job_file() {
    local job_file="$1"
    if [ ! -f "${job_file}" ]; then
        return 0
    fi
    local job_id
    job_id="$(cat "${job_file}")"
    if [ -n "${job_id}" ]; then
        "${OPENCLAW_BIN}" cron rm "${job_id}" >/dev/null 2>&1 || true
    fi
    rm -f "${job_file}"
}

extract_job_id() {
    python3 -c 'import json,sys
data=json.load(sys.stdin)
job_id=(data.get("id") or data.get("jobId") or (data.get("job") or {}).get("id") or "")
if not job_id:
    raise SystemExit("missing job id in openclaw cron add output")
print(job_id)'
}

load_route_to() {
    if [ -n "${DELIVERY_DEST}" ]; then
        printf '%s' "${DELIVERY_DEST}"
        return 0
    fi
    if [ ! -f "${AGENT_STATE_FILE}" ]; then
        return 0
    fi
    python3 -c 'import json,sys
from pathlib import Path
path=Path(sys.argv[1])
data=json.loads(path.read_text(encoding="utf-8"))
print(data.get("route_to") or "")' "${AGENT_STATE_FILE}"
}

require_route_to() {
    local route_to="$1"
    if [ -n "${route_to}" ]; then
        return 0
    fi
    echo "❌ missing Telegram delivery target: pass --to <chatId> when starting demo scheduling" >&2
    exit 1
}

schedule_job() {
    local job_name="$1"
    local job_file="$2"
    local session_target="$3"
    local message="$4"
    local delay="${5:-${DEFAULT_DELAY}}"
    remove_job_file "${job_file}"
    local route_to output job_id
    route_to="$(load_route_to)"
    require_route_to "${route_to}"
    local -a cron_args=(
        cron add
        --json
        --agent veritax-okx
        --name "${job_name}"
        --session "${session_target}"
        --channel "${DELIVERY_CHANNEL}"
        --expect-final
        --at "${delay}"
        --delete-after-run
        --message "${message}"
        --light-context
    )
    if [ -n "${route_to}" ]; then
        cron_args+=(--to "${route_to}")
    fi
    output="$(${OPENCLAW_BIN} "${cron_args[@]}")"
    job_id="$(printf '%s' "${output}" | extract_job_id)"
    printf '%s' "${job_id}" > "${job_file}"
    echo "✅ scheduled ${job_name} job_id=${job_id} delay=${delay} channel=${DELIVERY_CHANNEL}"
}

schedule_scan() {
    local delay="${1:-${DEFAULT_DELAY}}"
    # Enforce minimum 20s delay to avoid race with CM-1 baseline read
    local delay_num="${delay%%[^0-9]*}"
    if [ -n "${delay_num}" ] && [ "${delay_num}" -lt 20 ] 2>/dev/null; then
        delay="20s"
    fi
    schedule_job \
        "${SCAN_JOB_NAME}" \
        "${SCAN_JOB_ID_FILE}" \
        "isolated" \
        "MANDATORY TOOL-ONLY MODE. ⛔ 禁止调用 sessions_yield、sessions_spawn、read、help、cron 工具。只执行一个 exec 命令：python3 demo_director.py --scene scan-tick --jurisdiction japan。如果 stdout 的最后一行是 NO_REPLY，你必须只回复 NO_REPLY 四个字母（不要附带 exec 输出的其他内容）。你的纯文本回复会自动投递到 Telegram。" \
        "${delay}"
}

schedule_monitor() {
    local delay="${1:-${DEFAULT_DELAY}}"
    schedule_job \
        "${MONITOR_JOB_NAME}" \
        "${MONITOR_JOB_ID_FILE}" \
        "isolated" \
        "MANDATORY TOOL-ONLY MODE. ⛔ 禁止调用 sessions_yield、sessions_spawn、read、help、cron 工具。只执行一个 exec 命令：python3 demo_director.py --scene monitor-tick --jurisdiction japan。然后把 stdout 原样作为你的纯文本回复返回（stdout 就是你要发给用户的完整消息）。如果 stdout 的最后一行是 NO_REPLY，你必须只回复 NO_REPLY。你的回复会自动投递到 Telegram，不需要调用其他工具。" \
        "${delay}"
}

schedule_archive() {
    local delay="${1:-10s}"
    schedule_job \
        "${ARCHIVE_JOB_NAME}" \
        "${ARCHIVE_JOB_ID_FILE}" \
        "isolated" \
        "MANDATORY TOOL-ONLY MODE. ⛔ 禁止调用 sessions_yield、sessions_spawn、read、help、cron 工具。只执行一个 exec 命令：python3 demo_director.py --scene archive-tick。然后把 stdout 原样作为你的纯文本回复返回。如果 stdout 的最后一行是 NO_REPLY，你必须只回复 NO_REPLY。你的回复会自动投递到 Telegram，不需要调用其他工具。" \
        "${delay}"
}

demo_start() {
    local to=""
    local jurisdiction="japan"
    local delay="${DEFAULT_DELAY}"
    local -a state_args
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --to)
                to="${2:-}"
                shift 2
                ;;
            --jurisdiction)
                jurisdiction="${2:-japan}"
                shift 2
                ;;
            --delay)
                delay="${2:-${DEFAULT_DELAY}}"
                shift 2
                ;;
            *)
                echo "❌ unknown argument: $1" >&2
                usage
                exit 1
                ;;
        esac
    done
    remove_job_file "${SCAN_JOB_ID_FILE}"
    remove_job_file "${MONITOR_JOB_ID_FILE}"
    remove_job_file "${ARCHIVE_JOB_ID_FILE}"
    if [ -z "${to}" ] && [ -z "${DELIVERY_DEST}" ]; then
        echo "❌ demo-start requires --to <telegram_chat_id>" >&2
        usage
        exit 1
    fi
    state_args=(python3 demo_director.py --scene state-start --jurisdiction "${jurisdiction}")
    if [ -n "${to}" ]; then
        state_args+=(--to "${to}")
    fi
    "${state_args[@]}" >/dev/null
    # Reset tax_dataset.json to clean baseline (prevents stale data from prior runs)
    python3 demo_director.py --scene scan0 >/dev/null
    DELIVERY_DEST="${to:-${DELIVERY_DEST}}"
    schedule_scan "${delay}"
}

resume_after_confirmation() {
    local delay="${1:-${DEFAULT_DELAY}}"
    python3 demo_director.py --scene state-monitoring --jurisdiction japan >/dev/null
    schedule_scan "${delay}"
}

clear_all() {
    remove_job_file "${SCAN_JOB_ID_FILE}"
    remove_job_file "${MONITOR_JOB_ID_FILE}"
    remove_job_file "${ARCHIVE_JOB_ID_FILE}"
}

show_status() {
    for item in \
        "demo_scan_job_id:${SCAN_JOB_ID_FILE}" \
        "demo_monitor_job_id:${MONITOR_JOB_ID_FILE}" \
        "demo_archive_job_id:${ARCHIVE_JOB_ID_FILE}"; do
        local name="${item%%:*}"
        local file="${item#*:}"
        if [ -f "${file}" ]; then
            echo "${name}=$(cat "${file}")"
        else
            echo "${name}=(none)"
        fi
    done
}

usage() {
    cat <<'EOF'
Usage:
    bash manage_demo_cron.sh demo-start --to <chatId> [--jurisdiction japan] [--delay 20s]
    bash manage_demo_cron.sh schedule-scan [--delay 20s]
    bash manage_demo_cron.sh schedule-monitor [--delay 10s]
    bash manage_demo_cron.sh schedule-archive [--delay 10s]
    bash manage_demo_cron.sh resume [--delay 20s]
  bash manage_demo_cron.sh clear
  bash manage_demo_cron.sh status
EOF
}

COMMAND="${1:-}"
case "${COMMAND}" in
    demo-start)
        shift || true
        demo_start "$@"
        ;;
    schedule-scan)
        shift || true
        DELAY="${DEFAULT_DELAY}"
        while [ "$#" -gt 0 ]; do
            case "$1" in
                --delay)
                    DELAY="${2:-}"
                    shift 2
                    ;;
                *)
                    echo "❌ unknown argument: $1" >&2
                    usage
                    exit 1
                    ;;
            esac
        done
        schedule_scan "${DELAY}"
        ;;
    schedule-monitor)
        shift || true
        DELAY="10s"
        while [ "$#" -gt 0 ]; do
            case "$1" in
                --delay)
                    DELAY="${2:-}"
                    shift 2
                    ;;
                *)
                    echo "❌ unknown argument: $1" >&2
                    usage
                    exit 1
                    ;;
            esac
        done
        schedule_monitor "${DELAY}"
        ;;
    schedule-archive)
        shift || true
        DELAY="10s"
        while [ "$#" -gt 0 ]; do
            case "$1" in
                --delay)
                    DELAY="${2:-}"
                    shift 2
                    ;;
                *)
                    echo "❌ unknown argument: $1" >&2
                    usage
                    exit 1
                    ;;
            esac
        done
        schedule_archive "${DELAY}"
        ;;
    resume)
        shift || true
        DELAY="${DEFAULT_DELAY}"
        while [ "$#" -gt 0 ]; do
            case "$1" in
                --delay)
                    DELAY="${2:-}"
                    shift 2
                    ;;
                *)
                    echo "❌ unknown argument: $1" >&2
                    usage
                    exit 1
                    ;;
            esac
        done
        resume_after_confirmation "${DELAY}"
        ;;
    clear)
        clear_all
        echo "✅ cleared demo tick schedule"
        ;;
    status)
        show_status
        ;;
    *)
        usage
        exit 1
        ;;
esac