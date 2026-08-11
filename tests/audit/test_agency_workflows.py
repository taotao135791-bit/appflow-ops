"""Agency (乙方) workflow contracts: question discipline, rapid response,
client isolation docs, and funnel routing."""

from __future__ import annotations


def _read(repo_root, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def test_question_discipline_policy_is_shipped_and_wired(repo_root):
    policy = _read(
        repo_root, "skills/appflow/references/client-questions-policy.md"
    )
    for phrase in [
        "Must Ask",
        "Do Not Ask",
        "KPI and acceptance definition",
        "Permission boundary",
        "Urgency and deadline",
        "Other vendors",
    ]:
        assert phrase in policy, phrase

    router = _read(repo_root, "skills/appflow/SKILL.md")
    assert "references/client-questions-policy.md" in router
    assert "该问的问，不该问的不问" in policy


def test_rapid_response_keeps_safety_caps_and_dual_output(repo_root):
    rapid = _read(repo_root, "skills/ads-ops/references/rapid-response.md")
    for phrase in [
        "rollback value",
        "EMERGENCY_INTERVENTION",
        "OPERATIONAL_CORRECTION",
        "urgent: true",
        "Client-facing explanation",
        "Internal action ticket",
        "Speed never waives safety caps",
        "Exceed numeric policy single-change caps",
    ]:
        assert phrase in rapid, phrase

    ops_skill = _read(repo_root, "skills/ads-ops/SKILL.md")
    assert "references/rapid-response.md" in ops_skill
    router = _read(repo_root, "skills/appflow/SKILL.md")
    assert "references/rapid-response.md" in router
    assert "Urgent client demands never waive numeric safety caps" in router


def test_router_enforces_client_isolation_and_funnel_routing(repo_root):
    router = _read(repo_root, "skills/appflow/SKILL.md")
    assert "## Client & Account Isolation" in router
    assert "workspaces/<client>/<project>" in router
    assert "reports/client/" in router
    assert "references/funnel-dashboard.md" in router

    funnel_doc = _read(
        repo_root, "skills/ads-google-app/references/funnel-dashboard.md"
    )
    assert "funnel-dashboard" in funnel_doc
    assert "internal diagnosis" in funnel_doc


def test_removed_platform_skills_are_gone(repo_root):
    for removed in [
        "ads-amazon",
        "ads-linkedin",
        "ads-microsoft",
        "ads-landing",
        "ads-dna",
        "ads-photoshoot",
    ]:
        assert not (repo_root / "skills" / removed).exists(), removed

    router = _read(repo_root, "skills/appflow/SKILL.md")
    for removed in ["ads-amazon", "ads-linkedin", "ads-microsoft", "ads-landing"]:
        assert f"`{removed}`" not in router
