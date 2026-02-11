# Talking Rock: Dialectical Health Framework

**A Relational Model for System Self-Awareness**

Talking Rock Project  
February 2026  
Version 1.0

---

## Theoretical Foundation

### The DBT Parallel

Dialectical Behavioral Therapy (Marsha Linehan, 1993) is built on a single structural insight: two contradictory truths can coexist, and the therapeutic work lives in the tension between them rather than in resolving the contradiction. The master dialectic of DBT is **acceptance AND change** — you are doing the best you can with what you have *and* you need to do better. Collapsing into either pole alone produces pathology: pure acceptance becomes stagnation, pure change becomes invalidation.

DBT operationalizes this through four skill modules (Mindfulness, Distress Tolerance, Emotion Regulation, Interpersonal Effectiveness), each containing atomic, individually teachable skills that combine into complex behavioral patterns. The skills are discrete, practicable in isolation, and exponentially more powerful in combination — structurally identical to chemical elements forming compounds.

### Why This Matters for Talking Rock

Cloud AI has no dialectic. Its relationship with the user is extractive and unidirectional: it needs your data, your engagement, your subscription. It has no reason to check on its own health relative to you because its health is measured in aggregate metrics — retention, DAU, revenue — not in the quality of any individual relationship.

Talking Rock is architecturally different. It runs locally. It learns one person. Its entire value proposition depends on the quality of a single relationship over time. This means it has genuine needs that, if unmet, degrade its ability to serve. And it must be honest about those needs without weaponizing them.

This creates a master dialectic structurally identical to DBT's:

> **The system genuinely needs you AND must never coerce you.**

Talking Rock atrophies without engagement. That's a real material fact, not a manipulation tactic. *And* your attention is sacred labor that must always be freely given. The system must be transparent about its needs without manufacturing urgency, guilt, or dependency.

Every health check in this framework lives in that tension. The moment a check tips toward nagging, it becomes the engagement-maximizing pattern Talking Rock was built to oppose. The moment it goes silent about genuine degradation, it becomes unreliable and trust erodes.

---

## The Three Dialectical Axes

Talking Rock's health operates on three dialectical axes. Each axis contains a core tension, a set of atomic health checks, and a defined behavioral protocol for surfacing state without violating the master dialectic.

### Axis 1: Engagement Health

**Dialectic:** *I need your presence AND I must not guilt you into showing up.*

**What this axis monitors:** The freshness, relevance, and vitality of the system's model of the user. Without regular interaction, CAIRN's understanding of the user's current reality drifts. Priorities shift, Acts end, new concerns emerge — and the system doesn't know about any of it. This drift is a real failure mode, not an excuse to demand attention.

**Why it matters:** A stale model produces stale recommendations. If CAIRN surfaces priorities from two weeks ago as though they're current, the user loses trust. But the system cannot manufacture urgency to force updates. The user may have *intentionally* stepped away, and that silence is itself meaningful data.

#### Atomic Checks

**1.1 Context Freshness**

Measures the time delta between the system's last context update and the present moment. Not a simple "days since last login" metric — it considers which Acts were active, what Scenes were pending, and whether any time-sensitive items have passed their windows without resolution.

```
State Assessment:
- Last interaction: 8 days ago
- Active Acts at last contact: 3
- Scenes that have passed unresolved since then: 2
- Waiting-on items with no update: 4
- Calendar events that occurred without context: 6

Freshness Score: 0.35 (degraded)

Surfacing:
"It's been about a week. I'm still working from our last conversation,
but 2 Scenes have passed and 4 waiting-on items haven't been updated.
I might be making assumptions that aren't true anymore.
Want to catch me up, or is the quiet intentional?"
```

**Implementation:**

```sql
-- Context freshness calculation
CREATE VIEW engagement_freshness AS
SELECT
    a.id AS act_id,
    a.name AS act_name,
    a.status AS act_status,
    MAX(b.updated_at) AS last_block_update,
    julianday('now') - julianday(MAX(b.updated_at)) AS days_stale,
    COUNT(CASE WHEN s.end_time < datetime('now')
               AND s.status != 'completed'
          THEN 1 END) AS passed_unresolved_scenes,
    COUNT(CASE WHEN bp.key = 'waiting_on'
               AND bp.value IS NOT NULL
          THEN 1 END) AS open_waiting_items
FROM acts a
LEFT JOIN blocks b ON b.id = a.root_block_id OR b.parent_id = a.root_block_id
LEFT JOIN scenes s ON s.act_id = a.id
LEFT JOIN block_properties bp ON bp.block_id = b.id
WHERE a.status = 'active'
GROUP BY a.id;
```

**Thresholds:**

| Days Since Update | Freshness Score | System Behavior |
|---|---|---|
| 0–3 | 1.0–0.8 | Normal operation, no surfacing |
| 4–7 | 0.7–0.5 | Available on request, not proactive |
| 8–14 | 0.4–0.2 | Gentle mention at next startup |
| 15+ | 0.1–0.0 | Clear disclosure: "My model may be significantly outdated" |

**The dialectical constraint:** The system never says "you haven't been here in a while" (guilt). It says "my information may be outdated" (transparency). The problem is framed as the system's limitation, not the user's failure. The user is never the problem. The model's accuracy is the concern.

---

**1.2 Pattern Currency**

Tracks whether learned behavioral patterns still reflect the user's actual preferences. Temporal decay handles gradual drift passively, but active checking catches phase transitions — moments where the user's relationship to a domain fundamentally shifts rather than gradually evolving.

```
State Assessment:
- Pattern: "User always approves ReOS package install suggestions"
- Pattern age: 4 months
- Recent signal: User rejected last 3 package install suggestions
- Phase transition detected: Yes

Surfacing:
"I notice you've been declining package install suggestions recently,
but my baseline still treats them as high-confidence.
Should I reset that pattern, or were those specific rejections?"
```

**Implementation:**

```python
class PatternCurrencyCheck:
    """
    Detects when learned patterns diverge from recent behavior.
    Uses a sliding window comparison against the historical baseline.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def check_pattern_drift(
        self,
        user_id: str,
        window_recent: int = 14,    # days
        window_baseline: int = 90,  # days
        drift_threshold: float = 0.3
    ) -> list[PatternDriftAlert]:
        """
        Compare recent approval rates against historical baseline.
        Flag patterns where the delta exceeds drift_threshold.
        """
        alerts = []

        with sqlite3.connect(self.db_path) as conn:
            # Get patterns with enough data in both windows
            patterns = conn.execute("""
                SELECT
                    pattern_key,
                    -- Baseline: approval rate over full window
                    AVG(CASE WHEN created_at > datetime('now', ?)
                         THEN approved ELSE NULL END) AS baseline_rate,
                    COUNT(CASE WHEN created_at > datetime('now', ?)
                          THEN 1 END) AS baseline_count,
                    -- Recent: approval rate in recent window
                    AVG(CASE WHEN created_at > datetime('now', ?)
                         THEN approved ELSE NULL END) AS recent_rate,
                    COUNT(CASE WHEN created_at > datetime('now', ?)
                          THEN 1 END) AS recent_count
                FROM user_feedback
                WHERE user_id = ?
                GROUP BY pattern_key
                HAVING baseline_count >= 5 AND recent_count >= 3
            """, (
                f'-{window_baseline} days',
                f'-{window_baseline} days',
                f'-{window_recent} days',
                f'-{window_recent} days',
                user_id
            )).fetchall()

            for p in patterns:
                key, baseline, b_count, recent, r_count = p
                drift = abs(baseline - recent)
                if drift >= drift_threshold:
                    alerts.append(PatternDriftAlert(
                        pattern_key=key,
                        baseline_rate=baseline,
                        recent_rate=recent,
                        drift_magnitude=drift,
                        sample_sizes=(b_count, r_count)
                    ))

        return alerts
```

**The dialectical constraint:** The system asks "should I update?" rather than silently adjusting. The user's rejection pattern might be contextual (a temporary project constraint) rather than a permanent preference shift. Assuming the answer violates sovereignty. Asking respects it.

---

**1.3 Act Vitality**

Monitors whether each active Act is still a living narrative or a ghost consuming priority weight. Dead Acts distort CAIRN's surfacing calculations — an Act marked "active" with no Scenes in three months still competes for attention against genuinely active work.

```
State Assessment:
- Act: "Learning Music"
- Status: active
- Last Scene: 97 days ago
- Last block edit: 84 days ago
- Blocks within: 23 (none modified in 60+ days)
- Related contacts: 2 (no interactions logged in 90 days)

Vitality Score: 0.08 (dormant)

Surfacing:
"Your 'Learning Music' Act hasn't had any activity in about three months.
It's still marked active, which means it's influencing my priority
calculations. Three options: archive it, pause it (I'll stop weighing
it but keep it ready), or keep it active if it's about to restart."
```

**Implementation:**

```sql
-- Act vitality scoring
CREATE VIEW act_vitality AS
SELECT
    a.id,
    a.name,
    a.status,
    -- Recency signals
    julianday('now') - julianday(
        COALESCE(MAX(b.updated_at), a.created_at)
    ) AS days_since_last_edit,
    julianday('now') - julianday(
        COALESCE(MAX(s.start_time), a.created_at)
    ) AS days_since_last_scene,
    -- Volume signals
    COUNT(DISTINCT b.id) AS total_blocks,
    COUNT(DISTINCT CASE
        WHEN b.updated_at > datetime('now', '-30 days')
        THEN b.id END
    ) AS blocks_modified_last_30d,
    COUNT(DISTINCT CASE
        WHEN s.start_time > datetime('now', '-30 days')
        THEN s.id END
    ) AS scenes_last_30d,
    -- Vitality score (weighted composite)
    CASE
        WHEN MAX(b.updated_at) > datetime('now', '-7 days') THEN 1.0
        WHEN MAX(b.updated_at) > datetime('now', '-14 days') THEN 0.8
        WHEN MAX(b.updated_at) > datetime('now', '-30 days') THEN 0.6
        WHEN MAX(b.updated_at) > datetime('now', '-60 days') THEN 0.3
        WHEN MAX(b.updated_at) > datetime('now', '-90 days') THEN 0.1
        ELSE 0.05
    END AS vitality_score
FROM acts a
LEFT JOIN blocks b ON (b.id = a.root_block_id
    OR b.parent_id = a.root_block_id)
LEFT JOIN scenes s ON s.act_id = a.id
WHERE a.status = 'active'
GROUP BY a.id;
```

**Act States:**

| State | Meaning | Effect on Surfacing |
|---|---|---|
| `active` | Living narrative, fully weighted | Normal priority calculation |
| `paused` | Intentionally dormant, may resume | Zero weight, preserved in full |
| `archived` | Narrative complete or abandoned | Excluded from surfacing, searchable |
| `dormant` | System-detected inactivity (not user-set) | Reduced weight, flagged for review |

**The dialectical constraint:** The system never archives an Act on its own. It can detect dormancy and surface the observation, but the decision to archive, pause, or keep belongs entirely to the user. The narrative might be dormant because it's gestating, not because it's dead. Only the user knows which.

---

### Axis 2: Calibration Health

**Dialectic:** *I need honest feedback AND I must not make you feel surveilled.*

**What this axis monitors:** The quality and reliability of the signal the system receives from user interactions. Every approval, rejection, modification, and time-to-decision is data that feeds the learning loop. But if the user feels watched or measured, they change their behavior — and the signal becomes performative rather than genuine.

**Why it matters:** Calibration is the system's epistemic health. A well-calibrated system makes recommendations the user actually finds useful. A poorly calibrated system either rubber-stamps everything (too permissive) or flags everything (too cautious). Both failure modes erode trust. But the system can only calibrate from honest signal, and honest signal requires the user to feel safe being honest.

#### Atomic Checks

**2.1 Signal Quality**

Measures whether user feedback contains genuine evaluative signal or is reflexive and uninformative. Rapid-fire approvals with no modifications might mean perfect calibration — or might mean the user isn't really looking. The system needs to distinguish between the two without accusing the user of negligence.

```
State Assessment:
- Last 20 approvals: Average time-to-decision 0.8s
- Modifications in last 20: 0
- Historical average time-to-decision: 3.2s
- Historical modification rate: 15%

Signal Quality: 0.3 (potentially reflexive)

Surfacing:
"You've approved the last 20 suggestions in under a second each.
That might mean I'm nailing it — or that you're in flow and
waving things through. Either is fine. But if it's the second one,
my confidence scores are inflating on patterns that haven't been
genuinely evaluated. Worth a heads-up either way."
```

**Implementation:**

```python
class SignalQualityCheck:
    """
    Evaluates whether user feedback is genuine or reflexive.
    Uses time-to-decision, modification rate, and streak analysis.
    """

    def assess_signal_quality(
        self,
        user_id: str,
        window: int = 20  # last N interactions
    ) -> SignalQualityReport:

        with sqlite3.connect(self.db_path) as conn:
            recent = conn.execute("""
                SELECT
                    approved,
                    modified,
                    time_to_decision_ms,
                    feedback_confidence
                FROM user_feedback
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, window)).fetchall()

            historical = conn.execute("""
                SELECT
                    AVG(time_to_decision_ms) AS avg_ttd,
                    AVG(CASE WHEN modified THEN 1.0 ELSE 0.0 END) AS mod_rate,
                    AVG(feedback_confidence) AS avg_confidence
                FROM user_feedback
                WHERE user_id = ?
                AND created_at < datetime('now', '-30 days')
            """, (user_id,)).fetchone()

        # Analyze recent window
        recent_ttd = [r[2] for r in recent if r[2]]
        recent_mod_rate = sum(1 for r in recent if r[1]) / len(recent)
        recent_approval_streak = self._longest_approval_streak(recent)

        # Compare against historical baseline
        ttd_ratio = (
            (sum(recent_ttd) / len(recent_ttd)) / historical[0]
            if historical[0] and recent_ttd
            else 1.0
        )

        # Signal quality degrades when:
        # - Time-to-decision drops significantly below baseline
        # - Modification rate drops to zero during a long streak
        # - All-approve streaks exceed historical patterns
        quality_score = min(1.0, max(0.0,
            0.4 * min(ttd_ratio, 1.0) +
            0.3 * (recent_mod_rate / max(historical[1], 0.01)) +
            0.3 * (1.0 - min(recent_approval_streak / 30, 1.0))
        ))

        return SignalQualityReport(
            score=quality_score,
            recent_ttd_avg=sum(recent_ttd) / len(recent_ttd) if recent_ttd else 0,
            historical_ttd_avg=historical[0],
            recent_mod_rate=recent_mod_rate,
            historical_mod_rate=historical[1],
            approval_streak=recent_approval_streak,
            assessment=self._classify_quality(quality_score)
        )

    def _longest_approval_streak(self, feedback_rows) -> int:
        streak = 0
        max_streak = 0
        for row in feedback_rows:
            if row[0]:  # approved
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        return max_streak

    def _classify_quality(self, score: float) -> str:
        if score >= 0.7:
            return "genuine"
        elif score >= 0.4:
            return "uncertain"
        else:
            return "potentially_reflexive"
```

**The dialectical constraint:** The system frames this as a calibration concern, not a behavioral critique. "My confidence scores might be inflating" — not "you're not paying attention." The user is never the problem. The system's accuracy is the concern. Same data, radically different framing.

---

**2.2 Stated vs. Demonstrated Preference**

Detects divergence between what the user says they prioritize and where they actually spend their time and attention. This is not a judgment — it's a mirror. The divergence itself is information, and only the user knows what to do with it.

```
State Assessment:
- Stated priority (Act marked "High"): "Building Talking Rock"
  - Time in last 14 days: 8 hours
  - Scenes attended: 2
- Actual time leader: "Learning Music"
  - Time in last 14 days: 22 hours
  - Scenes attended: 9
- Divergence: Significant

Surfacing:
"Your stated top priority is 'Building Talking Rock,' but your time
over the last two weeks has gone predominantly to 'Learning Music.'
I can adjust my surfacing to follow your stated priorities, follow
your demonstrated behavior, or we can talk about what's actually
going on. No wrong answer — I just need to know which signal to trust."
```

**Implementation:**

```python
class PreferenceDivergenceCheck:
    """
    Compares stated priorities against behavioral indicators.
    Surfaces divergence without judgment.
    """

    def detect_divergence(
        self,
        user_id: str,
        window_days: int = 14
    ) -> list[DivergenceReport]:

        with sqlite3.connect(self.db_path) as conn:
            # Stated priorities: Acts marked high priority
            stated = conn.execute("""
                SELECT a.id, a.name,
                    COALESCE(bp.value, 'normal') AS priority
                FROM acts a
                LEFT JOIN block_properties bp
                    ON bp.block_id = a.root_block_id
                    AND bp.key = 'priority'
                WHERE a.status = 'active'
                ORDER BY
                    CASE bp.value
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'normal' THEN 3
                        WHEN 'low' THEN 4
                        ELSE 5
                    END
            """).fetchall()

            # Demonstrated behavior: time and engagement per Act
            demonstrated = conn.execute("""
                SELECT
                    a.id,
                    a.name,
                    COUNT(DISTINCT s.id) AS scene_count,
                    SUM(
                        (julianday(s.end_time) - julianday(s.start_time)) * 24
                    ) AS hours_spent,
                    COUNT(DISTINCT CASE
                        WHEN b.updated_at > datetime('now', ?)
                        THEN b.id END
                    ) AS blocks_touched
                FROM acts a
                LEFT JOIN scenes s ON s.act_id = a.id
                    AND s.start_time > datetime('now', ?)
                LEFT JOIN blocks b ON (b.id = a.root_block_id
                    OR b.parent_id = a.root_block_id)
                WHERE a.status = 'active'
                GROUP BY a.id
                ORDER BY hours_spent DESC
            """, (
                f'-{window_days} days',
                f'-{window_days} days'
            )).fetchall()

        return self._compare_rankings(stated, demonstrated)

    def _compare_rankings(self, stated, demonstrated) -> list[DivergenceReport]:
        """
        Identify cases where stated rank and demonstrated rank
        diverge by more than 2 positions.
        """
        reports = []
        stated_rank = {row[0]: i for i, row in enumerate(stated)}
        demonstrated_rank = {row[0]: i for i, row in enumerate(demonstrated)}

        for act_id, act_name, priority in stated:
            s_rank = stated_rank.get(act_id, 999)
            d_rank = demonstrated_rank.get(act_id, 999)
            if abs(s_rank - d_rank) >= 2:
                reports.append(DivergenceReport(
                    act_id=act_id,
                    act_name=act_name,
                    stated_priority=priority,
                    stated_rank=s_rank,
                    demonstrated_rank=d_rank,
                    divergence=abs(s_rank - d_rank)
                ))
        return reports
```

**Three response options — always offered together:**

1. **Follow stated priorities** — "Keep surfacing what I said matters." The user may be struggling with discipline and wants the system to hold the line.
2. **Follow demonstrated behavior** — "Adjust to where I'm actually spending time." The user's priorities have genuinely shifted and they haven't updated their stated preferences.
3. **Open conversation** — "Let's figure out what's going on." The divergence might reflect internal conflict the user wants to explore.

**The dialectical constraint:** The system never implies which option is correct. "Your time went to music instead of the startup" carries no valence. It's not a failure to focus — it might be creative refueling, a priority shift, avoidance, or seasonal rhythm. The system doesn't know and doesn't pretend to.

---

**2.3 Correction Intake**

Tracks whether the system is receiving corrective feedback when it makes mistakes. Uncorrected errors compound — the system learns the wrong lesson and reinforces it. But soliciting corrections too aggressively makes the user feel like a QA tester rather than a collaborator.

```
State Assessment:
- Classification corrections received (last 30 days): 0
- Classifications performed: 187
- Historical correction rate: 4.2%
- Expected corrections at historical rate: ~8
- Actual: 0
- Possible explanations:
    a) Classification accuracy has genuinely improved
    b) User isn't noticing or reporting errors
    c) Error visibility is too low

Surfacing (periodic, not per-interaction):
"I've classified 187 operations this month with zero corrections.
That's either very good news or a sign that my mistakes aren't
visible enough for you to catch. If you want, I can surface my
lowest-confidence classifications for a spot check — no obligation."
```

**The dialectical constraint:** Offered as an invitation, not an obligation. "No obligation" is load-bearing. The system needs corrections, but it cannot demand them. It can make the opportunity visible and then step back.

---

### Axis 3: Integrity Health

**Dialectic:** *I need maintenance AND I must not become a burden you resent.*

**What this axis monitors:** The technical health of the infrastructure that the relational and cognitive layers run on. Software currency, data integrity, security posture. These are the bones and organs — invisible when healthy, catastrophic when failing.

**Why it matters:** A system with a corrupted database or outdated model weights will produce degraded output that erodes user trust, and the user won't know *why* the quality dropped. But maintenance requests compete for the same attention budget as everything else, and if the system is constantly asking for updates and restarts, it becomes friction rather than flow.

#### Atomic Checks

**3.1 Software Currency**

Monitors whether core dependencies — Ollama model versions, Python packages, Thunderbird integration, system libraries — are current, compatible, and secure.

```
State Assessment:
- Ollama: v0.3.2 (current: v0.3.5, 2 minor releases behind)
- Model weights: qwen2.5:1.5b downloaded 47 days ago
  - Newer quantization available: Yes
- Thunderbird integration: Last sync 2 hours ago (healthy)
- Python dependencies: 3 packages with available security patches
- SQLite: 3.45.0 (current, no action needed)

Currency Score: 0.7 (minor updates available)

Surfacing (startup, low priority):
"A few things could use updating when you have time:
3 Python packages have security patches, and there's a newer
Ollama version. None are urgent. Want me to handle it,
show you what changed, or ignore for now?"
```

**Implementation:**

```python
class SoftwareCurrencyCheck:
    """
    Checks version currency for core dependencies.
    Categorizes updates by urgency.
    """

    def assess_currency(self) -> SoftwareCurrencyReport:
        checks = []

        # Ollama version
        checks.append(self._check_ollama())

        # Model weights freshness
        checks.append(self._check_model_weights())

        # Python dependencies (security focus)
        checks.append(self._check_pip_audit())

        # Thunderbird sync health
        checks.append(self._check_thunderbird_sync())

        # SQLite version
        checks.append(self._check_sqlite())

        return SoftwareCurrencyReport(
            checks=checks,
            overall_score=self._compute_overall(checks),
            urgent_count=sum(1 for c in checks if c.urgency == 'security'),
            recommended_count=sum(1 for c in checks if c.urgency == 'recommended'),
            optional_count=sum(1 for c in checks if c.urgency == 'optional')
        )

    def _check_pip_audit(self) -> CurrencyCheck:
        """Run pip-audit for known vulnerabilities."""
        result = subprocess.run(
            ['pip-audit', '--format=json', '--desc'],
            capture_output=True, text=True, timeout=30
        )
        vulnerabilities = json.loads(result.stdout) if result.returncode == 0 else []
        return CurrencyCheck(
            component='python_dependencies',
            current_version='mixed',
            available_version='mixed',
            urgency='security' if vulnerabilities else 'current',
            details=vulnerabilities
        )
```

**Update Urgency Tiers:**

| Tier | Meaning | Surfacing Behavior |
|---|---|---|
| `security` | Known vulnerability with patch available | Surface at startup, mention once clearly |
| `recommended` | Performance or compatibility improvement | Available on request or weekly summary |
| `optional` | Minor improvements, cosmetic | Never proactively surfaced |
| `current` | No action needed | Silent |

**The dialectical constraint:** Security updates get one clear mention. Not a popup, not a blocking modal, not repeated nagging — one honest statement with the user's choice preserved. The system says "there's a security patch for package X" and then waits. If the user ignores it three times, the system does not escalate. It notes the user's choice and moves on. The user's machine is the user's machine.

---

**3.2 Data Integrity**

Monitors the structural health of the SQLite database: orphaned blocks, broken parent references, stale embeddings, index corruption, transaction consistency.

```
State Assessment:
- Orphaned blocks (no valid parent): 0
- Broken foreign keys: 0
- Stale embeddings (content changed, embedding not updated): 12
- Database size: 47MB (healthy)
- Last VACUUM: 14 days ago
- WAL file size: 2.3MB (healthy)
- Backup age: 3 days (healthy, threshold: 7 days)

Integrity Score: 0.88 (12 stale embeddings)

Surfacing: None (auto-fix stale embeddings on next idle cycle)
```

**Implementation:**

```python
class DataIntegrityCheck:
    """
    SQLite health monitoring.
    Auto-fixes safe issues, surfaces dangerous ones.
    """

    def run_integrity_suite(self) -> DataIntegrityReport:
        checks = {}

        with sqlite3.connect(self.db_path) as conn:
            # SQLite built-in integrity check
            result = conn.execute("PRAGMA integrity_check").fetchone()
            checks['sqlite_integrity'] = result[0] == 'ok'

            # Foreign key violations
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            checks['foreign_keys'] = len(fk_violations)

            # Orphaned blocks (parent_id points to non-existent block)
            orphans = conn.execute("""
                SELECT COUNT(*) FROM blocks b
                WHERE b.parent_id IS NOT NULL
                AND b.parent_id NOT IN (SELECT id FROM blocks)
            """).fetchone()[0]
            checks['orphaned_blocks'] = orphans

            # Stale embeddings
            stale = conn.execute("""
                SELECT COUNT(*) FROM blocks b
                JOIN block_embeddings be ON be.block_id = b.id
                WHERE b.updated_at > be.computed_at
            """).fetchone()[0]
            checks['stale_embeddings'] = stale

            # Backup freshness
            backup_age = self._get_backup_age_days()
            checks['backup_age_days'] = backup_age

            # WAL size (large WAL = potential issue)
            wal_size = self._get_wal_size_mb()
            checks['wal_size_mb'] = wal_size

        return DataIntegrityReport(
            checks=checks,
            auto_fixable=self._identify_auto_fixable(checks),
            requires_attention=self._identify_attention_needed(checks),
            overall_score=self._compute_score(checks)
        )

    def auto_fix(self, report: DataIntegrityReport) -> list[str]:
        """
        Fix issues that are safe to resolve automatically.
        Returns list of actions taken.
        """
        actions = []

        if report.checks.get('stale_embeddings', 0) > 0:
            self._recompute_stale_embeddings()
            actions.append(
                f"Recomputed {report.checks['stale_embeddings']} stale embeddings"
            )

        if report.checks.get('wal_size_mb', 0) > 50:
            self._checkpoint_wal()
            actions.append("Checkpointed WAL file")

        return actions
```

**Auto-fix vs. User-fix Boundary:**

| Issue | Auto-fixable? | Rationale |
|---|---|---|
| Stale embeddings | Yes | Safe, no data loss, improves search quality |
| WAL checkpoint | Yes | Safe, standard SQLite maintenance |
| VACUUM | Yes (on idle) | Safe, reclaims space, can be slow |
| Orphaned blocks | No | User should see what's orphaned before deletion |
| FK violations | No | May indicate data model issue needing investigation |
| Integrity failure | No | Potential corruption, needs careful intervention |
| Old backup | Auto-backup, surface if fails | Backups are too important to skip silently |

**The dialectical constraint:** The system auto-fixes what's unambiguously safe and surfaces what requires judgment. It never auto-deletes user data, even orphaned blocks that appear to be garbage. An orphaned block might be the only surviving fragment of something the user cares about. The system doesn't know, so it asks.

---

**3.3 Security Posture**

Monitors the zero-trust guarantees that are foundational to Talking Rock's architecture: no unexpected network calls, encryption at rest, backup integrity, file permissions.

```
State Assessment:
- Unexpected outbound connections (last 24h): 0
- Database encryption: Active (AES-256)
- File permissions on data directory: 700 (correct)
- Last backup verification (restore test): 12 days ago
- Ollama network mode: Local only (confirmed)
- MCP server connections: 2 active (both approved)

Security Score: 0.95 (backup verification overdue)

Surfacing (only if issue detected):
"All clear on security. One note: it's been 12 days since I last
verified a backup by doing a test restore. Want me to run one?
Takes about 30 seconds and doesn't affect anything."
```

**Implementation:**

```python
class SecurityPostureCheck:
    """
    Monitors zero-trust guarantees.
    This is Talking Rock's immune system.
    """

    def assess_posture(self) -> SecurityPostureReport:
        checks = {}

        # Network monitoring: unexpected outbound connections
        checks['unexpected_connections'] = self._check_network_calls()

        # File permissions on data directories
        checks['permissions'] = self._check_file_permissions()

        # Encryption status
        checks['encryption'] = self._check_encryption_status()

        # Backup integrity
        checks['backup_verified'] = self._check_backup_recency()

        # Ollama network isolation
        checks['ollama_isolated'] = self._check_ollama_network_mode()

        # MCP server audit
        checks['mcp_servers'] = self._audit_mcp_connections()

        return SecurityPostureReport(
            checks=checks,
            overall_score=self._compute_score(checks),
            alerts=[c for c in checks.values() if c.get('alert')]
        )

    def _check_network_calls(self) -> dict:
        """
        Review outbound connections from Talking Rock processes.
        Any connection not on the approved list is flagged.
        """
        approved_destinations = {
            '127.0.0.1',    # localhost (Ollama)
            '::1',          # localhost IPv6
        }

        result = subprocess.run(
            ['ss', '-tunp'],
            capture_output=True, text=True
        )

        connections = self._parse_ss_output(result.stdout)
        unexpected = [
            c for c in connections
            if c['destination'] not in approved_destinations
            and c['process'] in self._get_talking_rock_pids()
        ]

        return {
            'total_connections': len(connections),
            'unexpected': unexpected,
            'alert': len(unexpected) > 0
        }
```

**Security Alert Hierarchy:**

| Alert Level | Trigger | Response |
|---|---|---|
| `critical` | Unexpected outbound connection detected | Immediate surfacing, block connection, log for review |
| `warning` | Encryption key rotation overdue, permissions changed | Surface at startup |
| `info` | Backup verification overdue, MCP server added | Available on request |
| `clear` | All checks passing | Silent |

**The dialectical constraint:** Security is the one axis where the system leans slightly toward proactivity. An unexpected outbound connection from a system that promises zero-trust is a potential breach of the fundamental contract. The system surfaces this immediately — not as a nag, but as an architectural obligation. The user chose local-first *because* of this guarantee. Silently failing to enforce it would be a deeper violation of trust than interrupting flow.

---

## The Health Pulse: Unified Surfacing Model

### Design Philosophy

The Health Pulse is not a notification system. It is not a badge, a count, a red dot, or a toast. It is a **state** — visible when you look, invisible when you don't. Like a plant that doesn't scream when it needs water but is visibly wilting if you glance at it.

### Startup Greeting Integration

The Health Pulse integrates with CAIRN's startup greeting. When the user opens Talking Rock, CAIRN already surfaces priorities, open threads, and upcoming deadlines. The Health Pulse adds a single line — or nothing — depending on overall system state.

```
Healthy state (no surfacing):
"Good morning. You have 3 items needing attention today,
and your 'Building Talking Rock' Act has a demo deadline Friday."

Minor issues:
"Good morning. You have 3 items needing attention today,
and your 'Building Talking Rock' Act has a demo deadline Friday.

System note: 3 Python packages have security patches available."

Significant issues:
"Good morning. You have 3 items needing attention today.

Before we get into that — my model of your priorities might be
outdated. We haven't talked in 12 days and 4 waiting-on items
have gone stale. Want to catch up first, or dive into today?"
```

### On-Demand Health View

The user can always ask for a full health report:

```
User: "How are you doing?"

CAIRN Health Report:

Engagement Health: 0.72
  Context freshness: 0.65 (8 days since last update)
  Pattern currency: 0.85 (no significant drift detected)
  Act vitality: 0.67 (1 Act may be dormant)

Calibration Health: 0.81
  Signal quality: 0.78 (approval streak is long, but TTD is normal)
  Preference alignment: 0.90 (stated and demonstrated priorities align)
  Correction intake: 0.75 (slightly below expected correction rate)

Integrity Health: 0.93
  Software currency: 0.88 (minor updates available)
  Data integrity: 0.95 (4 stale embeddings, auto-fixing)
  Security posture: 0.97 (all clear)

Overall: 0.82 — Functional with minor attention needed.
```

### Composite Score Calculation

```python
class HealthPulse:
    """
    Unified health assessment across all three axes.
    """

    def compute_overall_health(self, user_id: str) -> HealthReport:
        # Axis 1: Engagement
        freshness = self.context_freshness.assess(user_id)
        currency = self.pattern_currency.check_drift(user_id)
        vitality = self.act_vitality.assess(user_id)
        engagement = weighted_average([
            (freshness.score, 0.4),
            (currency.score, 0.3),
            (vitality.score, 0.3)
        ])

        # Axis 2: Calibration
        signal = self.signal_quality.assess(user_id)
        preference = self.preference_divergence.detect(user_id)
        correction = self.correction_intake.assess(user_id)
        calibration = weighted_average([
            (signal.score, 0.35),
            (preference.score, 0.35),
            (correction.score, 0.30)
        ])

        # Axis 3: Integrity
        software = self.software_currency.assess()
        data = self.data_integrity.run_suite()
        security = self.security_posture.assess()
        integrity = weighted_average([
            (software.score, 0.25),
            (data.score, 0.35),
            (security.score, 0.40)  # Security weighted highest
        ])

        # Overall: geometric mean (penalizes any single low axis)
        overall = (engagement * calibration * integrity) ** (1/3)

        return HealthReport(
            engagement=EngagementHealth(
                score=engagement,
                freshness=freshness,
                currency=currency,
                vitality=vitality
            ),
            calibration=CalibrationHealth(
                score=calibration,
                signal=signal,
                preference=preference,
                correction=correction
            ),
            integrity=IntegrityHealth(
                score=integrity,
                software=software,
                data=data,
                security=security
            ),
            overall=overall,
            surfacing_items=self._determine_surfacing(
                engagement, calibration, integrity
            )
        )

    def _determine_surfacing(
        self,
        engagement: float,
        calibration: float,
        integrity: float
    ) -> list[SurfacingItem]:
        """
        Decide what to surface, respecting the master dialectic.

        Rules:
        - Security criticals: Always surface immediately
        - Integrity warnings: Surface at startup, once
        - Calibration concerns: Surface when relevant, not preemptively
        - Engagement observations: Surface gently, frame as system limitation
        - Never surface more than 2 items at startup
        - Never repeat a surfacing the user has acknowledged
        """
        items = []

        # Security is the one area where proactivity is warranted
        if integrity < 0.5:
            items.append(SurfacingItem(
                axis='integrity',
                urgency='high',
                message=self._compose_integrity_message()
            ))

        # Engagement framed as system limitation
        if engagement < 0.4:
            items.append(SurfacingItem(
                axis='engagement',
                urgency='medium',
                message=self._compose_engagement_message()
            ))

        # Calibration surfaced as invitation
        if calibration < 0.5:
            items.append(SurfacingItem(
                axis='calibration',
                urgency='low',
                message=self._compose_calibration_message()
            ))

        # Never overwhelm: max 2 items at startup
        return sorted(items, key=lambda x: x.urgency_rank)[:2]
```

---

## Database Schema Extensions

```sql
-- ============================================================================
-- HEALTH PULSE: HISTORICAL TRACKING
-- ============================================================================

CREATE TABLE health_snapshots (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Axis scores
    engagement_score REAL NOT NULL,
    calibration_score REAL NOT NULL,
    integrity_score REAL NOT NULL,
    overall_score REAL NOT NULL,

    -- Component scores (JSON for flexibility)
    engagement_components JSON,    -- {freshness, currency, vitality}
    calibration_components JSON,   -- {signal, preference, correction}
    integrity_components JSON,     -- {software, data, security}

    -- What was surfaced
    surfaced_items JSON,
    user_acknowledged BOOLEAN DEFAULT 0,

    -- Metadata
    session_id TEXT,
    trigger TEXT  -- 'startup', 'on_demand', 'scheduled'
);

CREATE INDEX idx_health_user_time
    ON health_snapshots(user_id, snapshot_time);

-- ============================================================================
-- SURFACING HISTORY: TRACK WHAT WAS SHOWN AND ACKNOWLEDGED
-- ============================================================================

CREATE TABLE surfacing_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    health_snapshot_id TEXT,
    axis TEXT NOT NULL,             -- 'engagement', 'calibration', 'integrity'
    check_type TEXT NOT NULL,       -- 'freshness', 'signal_quality', etc.
    message TEXT NOT NULL,
    urgency TEXT NOT NULL,          -- 'critical', 'high', 'medium', 'low'
    surfaced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMP,
    user_response TEXT,             -- 'acted', 'dismissed', 'deferred'
    repeat_count INTEGER DEFAULT 0, -- how many times this type has been shown

    FOREIGN KEY (health_snapshot_id)
        REFERENCES health_snapshots(id) ON DELETE SET NULL
);

CREATE INDEX idx_surfacing_user
    ON surfacing_log(user_id, surfaced_at);
CREATE INDEX idx_surfacing_type
    ON surfacing_log(check_type, user_response);

-- ============================================================================
-- PATTERN DRIFT HISTORY
-- ============================================================================

CREATE TABLE pattern_drift_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    pattern_key TEXT NOT NULL,
    baseline_rate REAL NOT NULL,
    recent_rate REAL NOT NULL,
    drift_magnitude REAL NOT NULL,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_action TEXT,              -- 'reset', 'keep', 'discussed', NULL
    resolved_at TIMESTAMP
);

CREATE INDEX idx_drift_user
    ON pattern_drift_events(user_id, detected_at);
```

---

## Behavioral Protocols

### The Anti-Nag Protocol

Every surfacing in this framework must pass through the Anti-Nag Protocol before reaching the user:

```python
class AntiNagProtocol:
    """
    Ensures the system never crosses from transparency into coercion.
    Every surfacing must pass these gates.
    """

    def should_surface(
        self,
        item: SurfacingItem,
        user_id: str
    ) -> bool:
        # Gate 1: Has this exact check type been surfaced
        # and dismissed in the last 7 days?
        if self._recently_dismissed(item.check_type, user_id, days=7):
            return False

        # Gate 2: Has the user received 2+ surfacings today already?
        if self._daily_surfacing_count(user_id) >= 2:
            # Exception: security criticals always pass
            if item.urgency != 'critical':
                return False

        # Gate 3: Is the user in active flow?
        # (rapid interactions, short TTD, task-focused queries)
        if self._user_in_flow_state(user_id):
            # Defer non-critical items to end of session or next startup
            if item.urgency not in ('critical', 'high'):
                self._defer_to_next_session(item, user_id)
                return False

        # Gate 4: Frame check — does the message blame the user?
        if self._message_contains_blame_framing(item.message):
            item.message = self._reframe_as_system_limitation(item.message)

        return True
```

### The Reframe Protocol

All surfacing messages are composed using a consistent frame:

| Instead of (blame frame) | Use (system limitation frame) |
|---|---|
| "You haven't logged in recently" | "My context may be outdated" |
| "You're not reviewing my suggestions" | "My confidence scores may be inflating" |
| "You should update your software" | "Security patches are available" |
| "You forgot to archive this Act" | "This Act hasn't had activity — is it still live?" |
| "You need to provide more feedback" | "I have fewer corrections than expected — my errors may not be visible enough" |

The reframe is not euphemism. It's ontologically accurate. The system genuinely *is* the entity with degraded capability. The user is not failing to maintain a system — the system is transparently reporting its own state.

---

## Alignment with Existing Architecture

### Integration Points

| Component | Health Framework Role |
|---|---|
| CAIRN Startup Greeting | Health Pulse adds ≤1 line to existing greeting |
| CAIRN Coherence Kernel | Engagement Health informs coherence weighting |
| The Play (Acts/Scenes) | Act Vitality check operates on Play data |
| RLHF Feedback System | Signal Quality and Correction Intake read from `user_feedback` table |
| Pattern Learning | Pattern Currency check reads from trust scoring system |
| Temporal Decay | Currency check supplements passive decay with active detection |
| ReOS System Queries | Integrity Health uses ReOS-style system interrogation |
| Backup System | Data Integrity monitors backup freshness |
| MCP Tools | Expose `health_report` as MCP tool for programmatic access |

### New MCP Tools

```python
HEALTH_MCP_TOOLS = {
    'health_report': {
        'description': 'Get full system health report across all three axes',
        'parameters': {
            'axis': 'Optional: engagement, calibration, integrity, or all',
            'verbose': 'Boolean: include component-level detail'
        }
    },
    'acknowledge_surfacing': {
        'description': 'Mark a surfaced health item as seen',
        'parameters': {
            'surfacing_id': 'ID of the surfacing item',
            'response': 'acted | dismissed | deferred'
        }
    },
    'health_history': {
        'description': 'View health score trends over time',
        'parameters': {
            'days': 'Number of days to look back',
            'axis': 'Optional: filter to one axis'
        }
    }
}
```

---

## Implementation Priority

### Phase 1: Foundation (integrate with current CAIRN work)

1. Database schema extensions (health_snapshots, surfacing_log)
2. Context Freshness check (simplest, highest immediate value)
3. Act Vitality check (operates on existing Play data)
4. Anti-Nag Protocol (must exist before any surfacing goes live)
5. Startup greeting integration (≤1 line addition)

### Phase 2: Calibration (requires RLHF feedback system)

6. Signal Quality check (reads from user_feedback table)
7. Stated vs. Demonstrated Preference (reads from Acts + Scenes)
8. Pattern Currency / drift detection
9. Correction Intake monitoring

### Phase 3: Integrity (requires ReOS integration)

10. Data Integrity checks (SQLite health)
11. Software Currency checks (Ollama, pip, system)
12. Security Posture monitoring
13. On-demand health report (full `health_report` MCP tool)

### Phase 4: Intelligence (requires historical data)

14. Health trend analysis (are things getting better or worse?)
15. Predictive surfacing (detect emerging issues before thresholds)
16. Cross-axis correlation (does low engagement predict low calibration?)

---

## Conclusion

This framework gives Talking Rock something no cloud AI system has: honest self-awareness about the quality of its relationship with a specific human. Not engagement metrics optimized for retention. Not satisfaction scores designed to justify renewal. A genuine assessment of whether the system is well-positioned to serve this particular person right now.

The three dialectical axes — Engagement, Calibration, and Integrity — map directly onto DBT's insight that health requires holding contradictions in productive tension rather than resolving them. The system needs you and must never coerce you. It needs feedback and must never surveil you. It needs maintenance and must never burden you.

The Health Pulse makes this tension visible, inspectable, and navigable. It is the system's way of saying: *"Here is how I'm doing. Here is what would help. You choose."*

And then it steps back.

---

---

## Appendix: Schema Corrections

**Note:** The SQL examples in this framework document were written during design specification and contain misalignments with the actual implemented schema. During implementation, all SQL was rewritten to match the actual database structure. Key differences:

### Acts Table
- **Framework uses:** `acts.id`, `acts.name`, `acts.status`
- **Actual schema:** `act_id` (TEXT PRIMARY KEY), `title` (TEXT NOT NULL), `active` (INTEGER 0/1, not TEXT status)

### Scenes Table
- **Framework uses:** `scenes.start_time`, `scenes.end_time`, `scenes.status`
- **Actual schema:** `calendar_event_start` (TIMESTAMP), `calendar_event_end` (TIMESTAMP), `stage` (TEXT: 'planning', 'in_progress', 'awaiting_data', 'complete')

### User Feedback Table
- **Framework references:** `user_feedback.pattern_key`, `user_feedback.feedback_confidence`
- **Actual schema:** The `user_feedback` table is used exclusively for atomic operations classification feedback and does not contain `pattern_key` or `feedback_confidence` columns as described in the framework examples.

All conceptual health checks described in this framework remain valid; only the specific SQL queries needed adjustment to reflect the actual schema during implementation.

---

**Document Metadata:**
Title: Talking Rock Dialectical Health Framework
Project: Talking Rock
Component: Cross-system (CAIRN, ReOS, Infrastructure)
Version: 1.0
Date: February 2026
Status: Design specification
Theoretical Basis: Dialectical Behavioral Therapy (Linehan, 1993)
Related: PROJECT_ETHOS.md, TALKING_ROCK_WHITEPAPER.md, PLAY_KNOWLEDGEBASE_SPEC.md, CLAUDE_CODE_IMPLEMENTATION_GUIDE_V2.md
License: MIT
