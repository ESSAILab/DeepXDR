from datetime import datetime

import pytest

from ai_agent.defense.defense_manager import DefenseManager
from ai_agent.shared.models.ttp import AttackerFingerprint, ShortTTP


def make_short_ttp(**overrides):
    data = {
        "id": "short-1",
        "created_at": datetime(2026, 1, 1, 0, 0, 0),
        "end_at": datetime(2026, 1, 1, 0, 1, 0),
        "ttps": [],
        "confidence": 0.95,
        "summary": "suspicious requests from attacker",
        "event_count": 1,
        "source_events": ["event-1"],
        "attacker_fingerprint": None,
        "attacker_ip": None,
    }
    data.update(overrides)
    return ShortTTP(**data)


@pytest.mark.asyncio
async def test_short_ttp_blocks_attacker_ip_when_fingerprint_is_missing():
    manager = DefenseManager()
    blocked = []

    async def check_mcp_health():
        return True

    async def block_ip(ip, port, duration, reason):
        blocked.append((ip, port, duration, reason))
        return {"status": "success"}

    manager.check_mcp_health = check_mcp_health
    manager._block_ip_async = block_ip
    manager._increase_monitoring_async = lambda *args: {"status": "success"}

    result = await manager.process_short_ttp(
        make_short_ttp(attacker_ip="198.51.100.44", attacker_fingerprint=None)
    )

    assert result["status"] == "success"
    assert blocked == [
        (
            "198.51.100.44",
            manager.app_port,
            manager.defense_duration,
            "短期TTP置信度0.95: suspicious requests from attacker",
        )
    ]


@pytest.mark.asyncio
async def test_short_ttp_uses_fingerprint_for_monitoring_without_losing_attacker_ip_block():
    manager = DefenseManager()
    blocked = []
    monitored = []

    async def check_mcp_health():
        return True

    async def block_ip(ip, port, duration, reason):
        blocked.append(ip)
        return {"status": "success"}

    async def increase_monitoring(target, frequency, duration):
        monitored.append((target, frequency, duration))
        return {"status": "success"}

    manager.check_mcp_health = check_mcp_health
    manager._block_ip_async = block_ip
    manager._increase_monitoring_async = increase_monitoring
    fingerprint = AttackerFingerprint(
        primary_ip="203.0.113.9",
        ip_list=["203.0.113.9", "203.0.113.10"],
        user_agents=[],
        patterns=[],
        first_seen=datetime(2026, 1, 1, 0, 0, 0),
        last_seen=datetime(2026, 1, 1, 0, 1, 0),
    )

    result = await manager.process_short_ttp(
        make_short_ttp(attacker_ip="198.51.100.44", attacker_fingerprint=fingerprint)
    )

    assert result["status"] == "success"
    assert blocked == ["198.51.100.44"]
    assert monitored == [
        ("203.0.113.9", "high", manager.defense_duration),
        ("203.0.113.10", "high", manager.defense_duration),
    ]
