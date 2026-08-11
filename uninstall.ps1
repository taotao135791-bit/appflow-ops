#Requires -Version 5.1
<#
.SYNOPSIS
    AppFlow Ops Uninstaller for Windows (multi-host).
.DESCRIPTION
    Removes every ads-* sub-skill directory plus the router from the
    chosen host's install root. For the local target the bundled agents live
    inside <skill-base>\appflow\agents and are removed together with the
    router; for hosts with a separate agents directory the bundled
    agents are removed from there. Uses glob discovery so new sub-skills
    don't require uninstaller updates.
.PARAMETER Target
    Which host CLI to uninstall from. Default: local.
#>

param(
    [ValidateSet('local','codex','cursor','windsurf','gemini','goose')]
    [string]$Target = 'local'
)

$ErrorActionPreference = "Stop"

function Resolve-TargetPaths {
    param([string]$T)
    switch ($T) {
        'local' {
            $AppFlowHome = if ($env:APPFLOW_HOME) { $env:APPFLOW_HOME } else { Join-Path $HOME ".appflow" }
            return @{ SkillBase = Join-Path $AppFlowHome "skills";                                        AgentDir = '' }
        }
        'codex'    { return @{ SkillBase = Join-Path $env:USERPROFILE ".codex\skills";                              AgentDir = Join-Path $env:USERPROFILE ".codex\agents" } }
        'cursor'   { return @{ SkillBase = Join-Path $env:USERPROFILE ".cursor\extensions\appflow-ops\skills";     AgentDir = Join-Path $env:USERPROFILE ".cursor\extensions\appflow-ops\agents" } }
        'windsurf' { return @{ SkillBase = Join-Path $env:USERPROFILE ".windsurf\skills";                           AgentDir = Join-Path $env:USERPROFILE ".windsurf\agents" } }
        'gemini'   { return @{ SkillBase = Join-Path $env:USERPROFILE ".gemini\extensions\appflow-ops\skills";     AgentDir = Join-Path $env:USERPROFILE ".gemini\extensions\appflow-ops\agents" } }
        'goose'    { return @{ SkillBase = Join-Path $env:USERPROFILE ".config\goose\skills";                       AgentDir = Join-Path $env:USERPROFILE ".config\goose\agents" } }
        default    { throw "Unknown target: $T" }
    }
}

function Main {
    $paths = Resolve-TargetPaths -T $Target
    $SkillBase = $paths.SkillBase
    $AgentDir = $paths.AgentDir

    if ($AgentDir) {
        Write-Host "Uninstalling AppFlow Ops from $SkillBase and $AgentDir..."
    } else {
        Write-Host "Uninstalling AppFlow Ops from $SkillBase..."
    }

    # Remove router (for the local target this also removes the bundled
    # agents under <skill-base>\appflow\agents)
    $MainSkill = Join-Path $SkillBase "appflow"
    if (Test-Path $MainSkill) {
        Remove-Item -Path $MainSkill -Recurse -Force
    }

    # Remove all ads-* sub-skills via glob
    if (Test-Path $SkillBase) {
        Get-ChildItem -Path $SkillBase -Directory -Filter "ads-*" -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item -Path $_.FullName -Recurse -Force
        }
    }

    # Remove bundled audit + creative agents from hosts that have a separate
    # agents directory. Skipped for the local target — there the persona
    # briefs live inside <skill-base>\appflow\agents and are already removed
    # above.
    # NOTE: Keep this list in sync with the contents of `agents/` in the repo.
    # install.ps1 uses `Copy-Item agents\*.md` so any new agent file added
    # there must also be appended below.
    if ($AgentDir) {
        $Agents = @(
            "audit-budget", "audit-compliance", "audit-creative",
            "audit-google", "audit-meta", "audit-tracking",
            "copy-writer", "creative-strategist", "format-adapter", "visual-designer"
        )
        foreach ($agent in $Agents) {
            $AgentPath = Join-Path $AgentDir "$agent.md"
            if (Test-Path $AgentPath) {
                Remove-Item -Path $AgentPath -Force
            }
        }
    }

    Write-Host "[OK] AppFlow Ops uninstalled." -ForegroundColor Green
}

Main
