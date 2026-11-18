"""Server-side capability boundaries for platform-specific workflows."""

PLATFORM_CAPABILITIES: dict[str, frozenset[str]] = {
    "boss": frozenset({"collect", "score", "greet", "deliver", "monitor"}),
    # New platforms start read-only. Delivery and monitoring stay locked until
    # an authorized real-account acceptance test has verified the live DOM and
    # the maintainer explicitly enables those capabilities in a later change.
    # 智联的 deliver 已在 2026-11-18 用真实账号验证过一次（立即投递 → 平台发送简历与预置招呼语）。
    "zhilian": frozenset({"collect", "score", "greet", "deliver"}),
    "51job": frozenset({"collect", "score", "greet"}),
    "liepin": frozenset({"collect", "score", "greet"}),
}


def platform_supports(platform: str, capability: str) -> bool:
    return capability in PLATFORM_CAPABILITIES.get(str(platform), frozenset())
