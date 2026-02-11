"""Data Integrity Check — Is the database structurally sound?

Runs PRAGMA integrity_check and foreign_key_check on the CAIRN database.
This is a critical-only check — if it finds problems, something is wrong.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from reos.cairn.health.runner import HealthCheckResult, Severity

logger = logging.getLogger(__name__)


class DataIntegrityCheck:
    """Check SQLite database integrity."""

    name = "data_integrity"

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)

    def run(self) -> list[HealthCheckResult]:
        """Run integrity checks on the database."""
        results: list[HealthCheckResult] = []

        if not self._db_path.exists():
            results.append(HealthCheckResult(
                check_name=self.name,
                severity=Severity.WARNING,
                title="Database file not found",
                details=f"Expected database at {self._db_path}",
                finding_key=f"{self.name}:missing:{self._db_path.name}",
            ))
            return results

        try:
            conn = sqlite3.connect(str(self._db_path))
            try:
                # PRAGMA integrity_check
                integrity_result = conn.execute("PRAGMA integrity_check").fetchone()
                if integrity_result and integrity_result[0] != "ok":
                    results.append(HealthCheckResult(
                        check_name=self.name,
                        severity=Severity.CRITICAL,
                        title="Database integrity check failed",
                        details=f"PRAGMA integrity_check: {integrity_result[0]}",
                        finding_key=f"{self.name}:integrity:{self._db_path.name}",
                    ))
                    return results

                # PRAGMA foreign_key_check
                fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_violations:
                    tables = {v[0] for v in fk_violations}
                    results.append(HealthCheckResult(
                        check_name=self.name,
                        severity=Severity.WARNING,
                        title=f"Foreign key violations in {len(tables)} table(s)",
                        details=(
                            f"Tables with FK violations: {', '.join(sorted(tables))}. "
                            f"Total violations: {len(fk_violations)}"
                        ),
                        finding_key=f"{self.name}:fk:{','.join(sorted(tables))}",
                    ))
                    return results

                # All good
                results.append(HealthCheckResult(
                    check_name=self.name,
                    severity=Severity.HEALTHY,
                    title="Database integrity verified",
                    finding_key=f"{self.name}:ok:{self._db_path.name}",
                ))

            finally:
                conn.close()

        except sqlite3.Error as e:
            logger.error("Database integrity check failed: %s", e)
            results.append(HealthCheckResult(
                check_name=self.name,
                severity=Severity.CRITICAL,
                title="Cannot open database for integrity check",
                details=str(e),
                finding_key=f"{self.name}:open_error:{self._db_path.name}",
            ))

        return results
