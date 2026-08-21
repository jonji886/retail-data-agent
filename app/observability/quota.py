"""公网 Demo 的轻量配额控制。"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple


def _int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class QuotaConfig:
    enabled: bool = True
    session_limit: int = 10
    ip_daily_limit: int = 20
    global_daily_limit: int = 40

    @classmethod
    def from_env(cls) -> "QuotaConfig":
        return cls(
            enabled=os.getenv("DEMO_RATE_LIMIT_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
            session_limit=_int("DEMO_SESSION_LIMIT", 10),
            ip_daily_limit=_int("DEMO_IP_DAILY_LIMIT", 20),
            global_daily_limit=_int("DEMO_GLOBAL_DAILY_LIMIT", 40),
        )


class DemoQuota:
    """按进程内 session/IP/UTC 日全局计数，重启后自然清零。"""

    def __init__(self, config: Optional[QuotaConfig] = None) -> None:
        self.config = config or QuotaConfig.from_env()
        self._lock = threading.Lock()
        self._sessions: Dict[Tuple[str, str], int] = {}
        self._ips: Dict[Tuple[str, str], int] = {}
        self._global: Dict[str, int] = {}

    @staticmethod
    def _day() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def allow(self, session_id: str, ip: str = "", bypass: bool = False) -> Tuple[bool, str]:
        if bypass or not self.config.enabled:
            return True, "disabled_or_bypassed"
        day = self._day()
        session_key = (day, session_id or "anonymous")
        ip_key = (day, ip) if ip else None
        with self._lock:
            if self._sessions.get(session_key, 0) >= self.config.session_limit:
                return False, "session_limit"
            if ip_key and self._ips.get(ip_key, 0) >= self.config.ip_daily_limit:
                return False, "ip_daily_limit"
            if self._global.get(day, 0) >= self.config.global_daily_limit:
                return False, "global_daily_limit"
            self._sessions[session_key] = self._sessions.get(session_key, 0) + 1
            if ip_key:
                self._ips[ip_key] = self._ips.get(ip_key, 0) + 1
            self._global[day] = self._global.get(day, 0) + 1
            return True, "allowed"
