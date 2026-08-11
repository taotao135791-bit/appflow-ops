#!/usr/bin/env bash
set -euo pipefail

# AppFlow Ops Installer
# Wraps everything in main() to prevent partial execution on network failure.
#
# Default target is a local, host-agnostic install under ~/.appflow/skills.
# Cross-host targets are EXPERIMENTAL — they install the same skill artifacts
# under each host's expected directory, but the host's own runtime conventions
# may differ. Pin path overrides via --skill-dir / --agent-dir if the
# auto-detected paths are wrong for your install.
#
# Usage:
#   bash install.sh                              # default: --target=local
#   bash install.sh --target=local
#   bash install.sh --target=codex
#   bash install.sh --target=cursor
#   bash install.sh --target=windsurf
#   bash install.sh --target=gemini
#   bash install.sh --target=goose
#   bash install.sh --skill-dir=/custom/path     # override the target's default path
#   bash install.sh --ref=v3.0.0                 # install an exact release tag
#
# All target keys are validated against a strict whitelist (no shell injection
# possible via --target=...). Custom --skill-dir paths are validated against
# `;&|$()<>`, backslashes, leading dashes, `..` path segments, and UNC-style
# paths. Directory names that merely contain two dots are allowed.

# APPFLOW_OPS_REPO_URL is intentionally undocumented end-user plumbing used by
# packaging smoke tests and downstream mirrors. Normal installs keep using the
# canonical repository.
REPO_URL="${APPFLOW_OPS_REPO_URL:-https://github.com/taotao135791-bit/appflow-ops.git}"

# ─────────────────────────────────────────────────────────────────────────────
# Target whitelist + path mapping
# ─────────────────────────────────────────────────────────────────────────────
#
# Keep this table the SINGLE source of truth. When a new host CLI is added,
# update only this case statement plus the help text.
#
# local    — host-agnostic install (agents live in <skill-base>/appflow/agents)
# codex    — OpenAI Codex CLI
# cursor   — Cursor IDE (EXPERIMENTAL, extension model differs)
# windsurf — Windsurf IDE (EXPERIMENTAL)
# gemini   — Gemini CLI (EXPERIMENTAL)
# goose    — Goose CLI (EXPERIMENTAL)

resolve_target_paths() {
    local target="$1"
    case "$target" in
        local)
            SKILL_BASE="${APPFLOW_HOME:-${HOME}/.appflow}/skills"
            AGENT_DIR=""
            ALLOW_PIP=1
            HOST_LABEL="Local (~/.appflow)"
            ;;
        codex)
            SKILL_BASE="${HOME}/.codex/skills"
            AGENT_DIR="${HOME}/.codex/agents"
            ALLOW_PIP=1
            HOST_LABEL="OpenAI Codex CLI"
            ;;
        cursor)
            SKILL_BASE="${HOME}/.cursor/extensions/appflow-ops/skills"
            AGENT_DIR="${HOME}/.cursor/extensions/appflow-ops/agents"
            ALLOW_PIP=0
            HOST_LABEL="Cursor IDE"
            ;;
        windsurf)
            SKILL_BASE="${HOME}/.windsurf/skills"
            AGENT_DIR="${HOME}/.windsurf/agents"
            ALLOW_PIP=0
            HOST_LABEL="Windsurf IDE"
            ;;
        gemini)
            SKILL_BASE="${HOME}/.gemini/extensions/appflow-ops/skills"
            AGENT_DIR="${HOME}/.gemini/extensions/appflow-ops/agents"
            ALLOW_PIP=0
            HOST_LABEL="Gemini CLI"
            ;;
        goose)
            SKILL_BASE="${HOME}/.config/goose/skills"
            AGENT_DIR="${HOME}/.config/goose/agents"
            ALLOW_PIP=0
            HOST_LABEL="Goose CLI"
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

# Reject anything that could be path-injection, flag-confusion, or
# directory-traversal. Called before --skill-dir / --agent-dir values are
# used in `mkdir`, `cp`, or `rm`.
validate_install_path() {
    local path="$1"
    # Reject empty
    [ -z "$path" ] && return 1
    # Reject leading dash (flag confusion: `--skill-dir=-rf`)
    case "$path" in -*) return 1 ;; esac
    # Reject shell metacharacters
    case "$path" in *[\;\&\|\$\(\)\<\>\`\\]*) return 1 ;; esac
    # Reject parent-traversal path segments
    case "$path" in ..|../*|*/..|*/../*) return 1 ;; esac
    # Reject UNC-style paths (Windows-ish input slipping through bash)
    case "$path" in //*|\\\\*) return 1 ;; esac
    return 0
}

# Release pins deliberately accept only final semantic-version tags. Branches,
# prereleases, option-like values, and arbitrary Git ref syntax are rejected.
validate_repo_ref() {
    local ref="$1"
    [[ "${ref}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

print_help() {
    cat <<EOF
AppFlow Ops Installer

Usage:
  bash install.sh [--target=<host>] [--skill-dir=<path>] [--agent-dir=<path>] [--ref=vX.Y.Z]

Targets (default: local):
  local      Host-agnostic install under ~/.appflow/skills (default)
  codex      OpenAI Codex CLI
  cursor     Cursor IDE (experimental)
  windsurf   Windsurf IDE (experimental)
  gemini     Gemini CLI (experimental)
  goose      Goose CLI (experimental)

Overrides:
  --skill-dir=<path>   Override the target's default skill install root
  --agent-dir=<path>   Override the target's default agent install root
  --ref=vX.Y.Z         Install one exact final release tag

For the local target, Python report/screenshot dependencies are installed into
a local skill venv at <skill-dir>/appflow/.venv. The installer never modifies
system Python packages.

Examples:
  curl -fsSL https://raw.githubusercontent.com/taotao135791-bit/appflow-ops/main/install.sh | bash
  bash install.sh
  bash install.sh --ref=v3.0.0
  bash install.sh --target=local --skill-dir="\$HOME/custom/skills"

EOF
}

main() {
    # Defaults
    local TARGET="local"
    local SKILL_DIR_OVERRIDE=""
    local AGENT_DIR_OVERRIDE=""
    local REPO_REF=""
    local REF_WAS_SET=0

    # Parse args
    while [ $# -gt 0 ]; do
        case "$1" in
            --target=*)
                TARGET="${1#*=}"
                ;;
            --target)
                shift
                [ $# -eq 0 ] && { echo "✗ --target requires a value" >&2; exit 1; }
                TARGET="$1"
                ;;
            --skill-dir=*)
                SKILL_DIR_OVERRIDE="${1#*=}"
                ;;
            --skill-dir)
                shift
                [ $# -eq 0 ] && { echo "✗ --skill-dir requires a value" >&2; exit 1; }
                SKILL_DIR_OVERRIDE="$1"
                ;;
            --agent-dir=*)
                AGENT_DIR_OVERRIDE="${1#*=}"
                ;;
            --agent-dir)
                shift
                [ $# -eq 0 ] && { echo "✗ --agent-dir requires a value" >&2; exit 1; }
                AGENT_DIR_OVERRIDE="$1"
                ;;
            --ref=*)
                REPO_REF="${1#*=}"
                REF_WAS_SET=1
                ;;
            --ref)
                shift
                [ $# -eq 0 ] && { echo "✗ --ref requires a value" >&2; exit 1; }
                REPO_REF="$1"
                REF_WAS_SET=1
                ;;
            --help|-h)
                print_help
                exit 0
                ;;
            *)
                echo "✗ Unknown argument: $1" >&2
                echo "  Run: bash install.sh --help" >&2
                exit 1
                ;;
        esac
        shift
    done

    if [ "${REF_WAS_SET}" -eq 1 ] && ! validate_repo_ref "${REPO_REF}"; then
        echo "✗ Invalid --ref: expected an exact tag such as v3.0.0" >&2
        exit 1
    fi

    # Resolve target paths (rejects unknown targets via whitelist)
    if ! resolve_target_paths "$TARGET"; then
        echo "✗ Unknown target: $TARGET" >&2
        echo "  Valid targets: local, codex, cursor, windsurf, gemini, goose" >&2
        echo "  Run: bash install.sh --help" >&2
        exit 1
    fi

    # Apply path overrides (with strict validation)
    if [ -n "$SKILL_DIR_OVERRIDE" ]; then
        validate_install_path "$SKILL_DIR_OVERRIDE" || {
            echo "✗ Invalid --skill-dir: contains forbidden characters or traversal" >&2
            exit 1
        }
        SKILL_BASE="$SKILL_DIR_OVERRIDE"
    fi
    if [ -n "$AGENT_DIR_OVERRIDE" ]; then
        validate_install_path "$AGENT_DIR_OVERRIDE" || {
            echo "✗ Invalid --agent-dir: contains forbidden characters or traversal" >&2
            exit 1
        }
        AGENT_DIR="$AGENT_DIR_OVERRIDE"
    fi

    local SKILL_DIR="${SKILL_BASE}/appflow"

    echo "════════════════════════════════════════"
    echo "║   AppFlow Ops - Installer            ║"
    echo "║   Target: ${HOST_LABEL}"
    echo "════════════════════════════════════════"
    echo ""

    # Check prerequisites
    command -v git >/dev/null 2>&1 || { echo "✗ Git is required but not installed."; exit 1; }
    echo "✓ Git detected"

    # Create directories. The local target has no separate agents directory
    # (AGENT_DIR is empty) — its persona briefs live inside the main skill.
    mkdir -p "${SKILL_DIR}/references"
    if [ -n "${AGENT_DIR}" ]; then
        mkdir -p "${AGENT_DIR}"
    fi

    # Clone or update
    TEMP_DIR=$(mktemp -d)
    trap 'rm -rf "${TEMP_DIR}"' EXIT

    local SOURCE_DIR="${TEMP_DIR}/appflow-ops"
    if [ "${REF_WAS_SET}" -eq 1 ]; then
        echo "↓ Downloading AppFlow Ops ${REPO_REF} from ${REPO_URL}..."
        mkdir -p "${SOURCE_DIR}"
        git -C "${SOURCE_DIR}" init --quiet
        if ! git -C "${SOURCE_DIR}" fetch --depth 1 --no-tags -- \
            "${REPO_URL}" "refs/tags/${REPO_REF}:refs/tags/${REPO_REF}"; then
            echo "✗ Ref ${REPO_REF} does not resolve to a release tag" >&2
            exit 1
        fi
        if ! git -C "${SOURCE_DIR}" show-ref --verify --quiet \
            "refs/tags/${REPO_REF}"; then
            echo "✗ Ref ${REPO_REF} does not resolve to a release tag" >&2
            exit 1
        fi
        if ! git -C "${SOURCE_DIR}" checkout --quiet --detach \
            "refs/tags/${REPO_REF}^{commit}"; then
            echo "✗ Ref ${REPO_REF} does not resolve to a commit tag" >&2
            exit 1
        fi
        local HEAD_COMMIT TAG_COMMIT
        HEAD_COMMIT=$(git -C "${SOURCE_DIR}" rev-parse --verify 'HEAD^{commit}')
        TAG_COMMIT=$(git -C "${SOURCE_DIR}" rev-parse --verify \
            "refs/tags/${REPO_REF}^{commit}")
        if [ "${HEAD_COMMIT}" != "${TAG_COMMIT}" ]; then
            echo "✗ Checked-out commit does not match tag ${REPO_REF}" >&2
            exit 1
        fi
    else
        echo "↓ Downloading AppFlow Ops from ${REPO_URL}..."
        if ! git clone --depth 1 -- "${REPO_URL}" "${SOURCE_DIR}"; then
            echo "✗ Failed to clone AppFlow Ops from ${REPO_URL}" >&2
            echo "  Check that the repository exists and that you have access." >&2
            exit 1
        fi
    fi

    # Copy main skill + references from the plugin-compatible skill tree.
    echo "→ Installing skill files..."
    cp "${TEMP_DIR}/appflow-ops/skills/appflow/SKILL.md" "${SKILL_DIR}/SKILL.md"
    cp "${TEMP_DIR}/appflow-ops/skills/appflow/references/"*.md "${SKILL_DIR}/references/"
    cp "${TEMP_DIR}/appflow-ops/VERSION" "${SKILL_DIR}/VERSION"
    # Scoped privacy exceptions ship with the bundle so an installed
    # preflight (--full) can audit history against the same allowlist.
    if [ -f "${TEMP_DIR}/appflow-ops/privacy-allowlist.json" ]; then
        cp "${TEMP_DIR}/appflow-ops/privacy-allowlist.json" "${SKILL_DIR}/privacy-allowlist.json"
    fi

    # Copy sub-skills
    echo "→ Installing sub-skills..."
    for skill_dir in "${TEMP_DIR}/appflow-ops/skills"/*/; do
        skill_name=$(basename "${skill_dir}")
        if [ "${skill_name}" = "appflow" ]; then
            continue
        fi
        target="${SKILL_BASE}/${skill_name}"
        mkdir -p "${target}"
        cp "${skill_dir}SKILL.md" "${target}/SKILL.md"

        # Copy supported assets/templates if they exist. Keep this extension
        # allowlist narrow: skills may contain local working files that should
        # not become part of an installation. UAC ledgers and schemas require
        # YAML/JSON in addition to the historical Markdown templates.
        if [ -d "${skill_dir}assets" ]; then
            mkdir -p "${target}/assets"
            for asset in "${skill_dir}assets/"*; do
                [ -f "${asset}" ] || continue
                case "${asset}" in
                    *.md|*.yaml|*.yml|*.json)
                        cp "${asset}" "${target}/assets/"
                        ;;
                esac
            done
        fi

        # Copy Markdown references recursively while preserving their relative
        # layout. `find -type f` deliberately excludes symlinks and the narrow
        # extension allowlist prevents private working files from leaking into
        # an installation.
        if [ -d "${skill_dir}references" ]; then
            while IFS= read -r -d '' reference; do
                relative_reference="${reference#"${skill_dir}references/"}"
                reference_target="${target}/references/${relative_reference}"
                mkdir -p "$(dirname "${reference_target}")"
                cp "${reference}" "${reference_target}"
            done < <(find "${skill_dir}references" -type f -name '*.md' -print0)
        fi
    done

    # Copy agents. Hosts with a separate agents directory (codex etc.) receive
    # the persona briefs there; for the local target they are installed into
    # the main skill at <skill-base>/appflow/agents instead. The source glob
    # is tested first so a missing source tree only warns, while a real copy
    # failure (permissions, full disk, ...) aborts loudly under `set -e`.
    echo "→ Installing subagents..."
    local AGENTS_TARGET
    if [ -n "${AGENT_DIR}" ]; then
        AGENTS_TARGET="${AGENT_DIR}"
    else
        AGENTS_TARGET="${SKILL_DIR}/agents"
        mkdir -p "${AGENTS_TARGET}"
    fi
    shopt -s nullglob
    local agent_briefs=("${TEMP_DIR}/appflow-ops/agents/"*.md)
    shopt -u nullglob
    if [ "${#agent_briefs[@]}" -gt 0 ]; then
        cp "${agent_briefs[@]}" "${AGENTS_TARGET}/"
    else
        echo "  ⚠ No agent briefs found under ${TEMP_DIR}/appflow-ops/agents — skipping." >&2
    fi

    # Copy scripts (optional Python tools)
    SCRIPTS_DIR="${SKILL_DIR}/scripts"
    if [ -d "${TEMP_DIR}/appflow-ops/scripts" ]; then
        echo "→ Installing Python scripts..."
        mkdir -p "${SCRIPTS_DIR}"
        cp "${TEMP_DIR}/appflow-ops/scripts/"*.py "${SCRIPTS_DIR}/"
        if [ -d "${TEMP_DIR}/appflow-ops/scripts/appflow_ops" ]; then
            cp -R "${TEMP_DIR}/appflow-ops/scripts/appflow_ops" "${SCRIPTS_DIR}/"
        fi
        cp "${TEMP_DIR}/appflow-ops/requirements.txt" "${SKILL_DIR}/requirements.txt"
    fi

    # Copy synthetic eval fixtures (privacy-safe, no production data).
    if [ -d "${TEMP_DIR}/appflow-ops/evals" ]; then
        echo "→ Installing eval fixtures..."
        mkdir -p "${SKILL_DIR}/evals"
        cp "${TEMP_DIR}/appflow-ops/evals/"*.json "${SKILL_DIR}/evals/"
    fi

    # Install Python dependencies only for hosts that explicitly support
    # Python execution. Use a local venv; never mutate system Python packages.
    echo ""
    if [ "${ALLOW_PIP}" = "1" ]; then
        echo "→ Installing Python dependencies into local skill venv..."
        if command -v python3 >/dev/null 2>&1; then
            VENV_DIR="${SKILL_DIR}/.venv"
            if python3 -m venv "${VENV_DIR}" 2>/dev/null; then
                "${VENV_DIR}/bin/python" -m pip install -q --upgrade pip 2>/dev/null || true
                if "${VENV_DIR}/bin/python" -m pip install -q -r "${SKILL_DIR}/requirements.txt" 2>/dev/null; then
                    echo "  ✓ Python dependencies installed in ${VENV_DIR}"
                    echo "  Use: ${VENV_DIR}/bin/python ${SKILL_DIR}/scripts/<script>.py"
                else
                    echo "  ⚠ venv pip install failed. Run manually:" >&2
                    echo "    ${VENV_DIR}/bin/python -m pip install -r ${SKILL_DIR}/requirements.txt" >&2
                fi
            else
                echo "  ⚠ python3 -m venv failed. Install deps manually in your preferred environment:" >&2
                echo "    python3 -m pip install -r ${SKILL_DIR}/requirements.txt" >&2
            fi
        else
            echo "  ⚠ python3 not found. Install deps manually in your preferred environment:"
            echo "    python3 -m pip install -r ${SKILL_DIR}/requirements.txt"
        fi
    else
        echo "ℹ Skipping Python dependencies — ${HOST_LABEL} host runtime may not execute Python skills directly."
        echo "  If you need PDF reports / funnel dashboards / screenshots, install manually:"
        echo "    pip3 install -r ${SKILL_DIR}/requirements.txt"
    fi

    echo ""
    echo "ℹ Image generation uses scripts/generate_image.py with ADS_IMAGE_PROVIDER."
    echo "  Set GOOGLE_API_KEY, OPENAI_API_KEY, STABILITY_API_KEY, or REPLICATE_API_TOKEN as needed."

    # Derive the bundle counts from what was actually installed, so the
    # banner cannot drift away from the real payload as skills come and go.
    local SUB_SKILL_COUNT AGENT_COUNT REFERENCE_COUNT TEMPLATE_COUNT
    SUB_SKILL_COUNT=$(find "${SKILL_BASE}" -mindepth 1 -maxdepth 1 -type d -name 'ads-*' | wc -l | tr -d '[:space:]')
    AGENT_COUNT=$(find "${AGENTS_TARGET}" -mindepth 1 -maxdepth 1 -type f -name '*.md' | wc -l | tr -d '[:space:]')
    REFERENCE_COUNT=$(find "${SKILL_DIR}/references" -type f -name '*.md' | wc -l | tr -d '[:space:]')
    TEMPLATE_COUNT=$(find "${SKILL_BASE}" -type f -path '*/assets/*.md' | wc -l | tr -d '[:space:]')

    echo ""
    echo "✓ AppFlow Ops installed successfully for ${HOST_LABEL}!"
    echo ""
    echo "  Installed to:"
    echo "    Skills: ${SKILL_BASE}"
    if [ -n "${AGENT_DIR}" ]; then
        echo "    Agents: ${AGENT_DIR}"
    else
        echo "    Agents: ${AGENTS_TARGET} (persona briefs)"
    fi
    echo ""
    echo "  Bundled:"
    echo "    • 1 main skill (appflow router)"
    echo "    • ${SUB_SKILL_COUNT} sub-skills (platform + functional + creative + agency ops)"
    echo "    • ${AGENT_COUNT} agents (audit + creative personas)"
    echo "    • ${REFERENCE_COUNT} reference files (main skill)"
    echo "    • ${TEMPLATE_COUNT} templates (sub-skill Markdown assets)"
    echo ""
    echo "Usage:"
    echo "  1. Start your AI coding assistant"
    echo "  2. Ask naturally, e.g.:"
    echo "       只读审查这个广告账户，先看 KPI、预算消耗、转化目标和今天要处理的事项。"
    echo "       或使用 /skill:appflow，或路由 shorthand: /appflow audit, /appflow uac, /appflow google"
    echo ""
    echo "To uninstall: bash uninstall.sh --target=${TARGET}"
}

main "$@"
