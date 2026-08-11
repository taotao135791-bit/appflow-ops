#!/usr/bin/env bash
set -euo pipefail

# AppFlow Ops Uninstaller (multi-host)
#
# Usage:
#   bash uninstall.sh                  # default: --target=local
#   bash uninstall.sh --target=local
#
# Removes every directory under <SKILL_BASE>/ads-* plus the router at
# <SKILL_BASE>/appflow. For the local target the bundled agents live inside
# <SKILL_BASE>/appflow/agents and are removed together with the router; for
# hosts with a separate agents directory the bundled audit + creative agents
# are removed from <AGENT_DIR>.
# Uses glob discovery so new sub-skills don't require uninstaller updates.

resolve_target_paths() {
    local target="$1"
    case "$target" in
        local)    SKILL_BASE="${APPFLOW_HOME:-${HOME}/.appflow}/skills";                 AGENT_DIR="" ;;
        codex)    SKILL_BASE="${HOME}/.codex/skills";                                    AGENT_DIR="${HOME}/.codex/agents" ;;
        cursor)   SKILL_BASE="${HOME}/.cursor/extensions/appflow-ops/skills";            AGENT_DIR="${HOME}/.cursor/extensions/appflow-ops/agents" ;;
        windsurf) SKILL_BASE="${HOME}/.windsurf/skills";                                 AGENT_DIR="${HOME}/.windsurf/agents" ;;
        gemini)   SKILL_BASE="${HOME}/.gemini/extensions/appflow-ops/skills";            AGENT_DIR="${HOME}/.gemini/extensions/appflow-ops/agents" ;;
        goose)    SKILL_BASE="${HOME}/.config/goose/skills";                             AGENT_DIR="${HOME}/.config/goose/agents" ;;
        *)        return 1 ;;
    esac
    return 0
}

main() {
    local TARGET="local"

    while [ $# -gt 0 ]; do
        case "$1" in
            --target=*) TARGET="${1#*=}" ;;
            --target)   shift; [ $# -eq 0 ] && { echo "✗ --target requires a value" >&2; exit 1; }; TARGET="$1" ;;
            --help|-h)
                echo "Usage: bash uninstall.sh [--target=<local|codex|cursor|windsurf|gemini|goose>]"
                exit 0
                ;;
            *) echo "✗ Unknown argument: $1" >&2; exit 1 ;;
        esac
        shift
    done

    if ! resolve_target_paths "$TARGET"; then
        echo "✗ Unknown target: $TARGET" >&2
        echo "  Valid targets: local, codex, cursor, windsurf, gemini, goose" >&2
        exit 1
    fi

    if [ -n "${AGENT_DIR}" ]; then
        echo "→ Uninstalling AppFlow Ops from ${SKILL_BASE} and ${AGENT_DIR}..."
    else
        echo "→ Uninstalling AppFlow Ops from ${SKILL_BASE}..."
    fi

    # Remove router (with references + scripts; for the local target this
    # also removes the bundled agents under <SKILL_BASE>/appflow/agents)
    rm -rf "${SKILL_BASE}/appflow"

    # Remove all ads-* sub-skills via glob (no hardcoded list — new sub-skills
    # don't require an uninstaller update)
    if [ -d "${SKILL_BASE}" ]; then
        for d in "${SKILL_BASE}"/ads-*/; do
            [ -d "$d" ] && rm -rf "$d"
        done
    fi

    # Remove bundled audit + creative agents from hosts that have a separate
    # agents directory. Skipped for the local target — there the persona
    # briefs live inside <SKILL_BASE>/appflow/agents and are already removed
    # above.
    # ⚠ Keep this list in sync with the contents of `agents/` in the repo. The
    # installer uses `cp agents/*.md` so any new agent file added there must
    # also be appended below.
    if [ -n "${AGENT_DIR}" ]; then
        for agent in \
            audit-budget audit-compliance audit-creative audit-google audit-meta audit-tracking \
            copy-writer creative-strategist format-adapter visual-designer; do
            rm -f "${AGENT_DIR}/${agent}.md"
        done
    fi

    echo "✓ AppFlow Ops uninstalled."
}

main "$@"
