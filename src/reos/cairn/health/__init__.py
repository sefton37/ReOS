"""CAIRN Health Pulse — Dialectical health monitoring.

Three axes of health:
1. Context Health — Data freshness, act vitality, pattern currency
2. Calibration Health — Signal quality, preference alignment, correction intake
3. System Health — Software currency, data integrity, security posture

Master dialectic: "The system genuinely needs you AND must never coerce you."
"""

from reos.cairn.health.anti_nag import AntiNagProtocol
from reos.cairn.health.runner import HealthCheckResult, HealthCheckRunner, HealthStatus, Severity

__all__ = [
    "AntiNagProtocol",
    "HealthCheckResult",
    "HealthCheckRunner",
    "HealthStatus",
    "Severity",
]
