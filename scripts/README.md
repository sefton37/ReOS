# RIVA Verification Measurement Tools

This directory contains tools for measuring and validating RIVA's verification value proposition.

## Tools

### 1. `analyze_verification_metrics.py` - Real Usage Analysis

Analyzes metrics from actual RIVA sessions stored in the database.

**What it does:**
- Reads metrics from `riva_metrics` database table
- Calculates verification effectiveness (errors caught, catch rates, time overhead)
- Measures confidence calibration (prediction accuracy)
- Generates markdown report with findings

**Usage:**

```bash
# Analyze metrics from RIVA database
python scripts/analyze_verification_metrics.py \
    --db ~/.local/share/talking_rock/riva.db \
    --output verification_report.md

# View the report
cat verification_report.md
```

**Sample Output:**

```markdown
# RIVA Verification Impact Report

## Summary
- Total Sessions: 25
- Overall Success Rate: 92.0%
- First-Try Success Rate: 84.0%

## Verification Impact
- Total Errors Caught: 18
- Average Verification Time: 1,234ms

### Layer Effectiveness
| Layer | Catch Rate |
|-------|------------|
| Syntax | 15.2% |
| Semantic | 22.4% |
| Behavioral | 31.1% |
| Intent | 8.3% |

## Confidence Calibration
- High-Confidence Accuracy (≥0.9): 94.2%
- Calibration Error: 0.032
```

**When to use:**
- After collecting real RIVA usage data
- To validate the value proposition with actual metrics
- To identify which layers are most effective
- To measure actual time overhead vs benefit

---

### 2. `benchmark_verification.py` - Controlled A/B Testing

Runs controlled scenarios with and without verification to measure impact.

**What it does:**
- Defines test scenarios (simple functions, intentional errors, etc.)
- Runs each scenario twice: WITH and WITHOUT verification
- Compares outcomes (success rate, time, errors caught)
- Generates comparison report

**Usage:**

```bash
# Run benchmarks with default settings
python scripts/benchmark_verification.py

# Specify custom sandbox and output
python scripts/benchmark_verification.py \
    --sandbox /tmp/my_sandbox \
    --output benchmark_results.json

# View results
cat benchmark_results.json | jq '.comparison'
```

**Test Scenarios:**

1. **Simple scenarios** (baseline):
   - Create hello() function
   - Create math_utils.py module

2. **Error scenarios** (verification should catch):
   - Syntax error: missing colon → Layer 1 catches
   - Semantic error: undefined variable → Layer 2 catches
   - Semantic error: missing import → Layer 2 catches
   - Behavioral error: division by zero → Layer 3 catches
   - Intent error: wrong function (fibonacci vs factorial) → Layer 4 catches

**Sample Output:**

```json
{
  "comparison": {
    "success_rate_improvement": 0.18,
    "success_rate_improvement_pct": 18.0,
    "time_overhead_ms": 1523,
    "time_overhead_pct": 15.2,
    "errors_caught_by_verification": 4
  }
}
```

**When to use:**
- To validate claims before shipping ("80% → 98%")
- To test specific error scenarios
- To measure overhead in controlled conditions
- To establish baseline before making changes

---

## Workflow: Proving the Value Proposition

### Phase 1: Establish Baseline (Benchmarks)

```bash
# Run controlled benchmarks
python scripts/benchmark_verification.py --output baseline.json

# Review results
cat baseline.json | jq '.comparison'
```

**Goal:** Validate that verification catches errors in controlled scenarios

### Phase 2: Collect Real Usage Data

```bash
# Use RIVA normally for a week
# Metrics are automatically collected in the database

# Check that metrics are being collected
sqlite3 ~/.local/share/talking_rock/riva.db \
    "SELECT COUNT(*) FROM riva_metrics WHERE completed_at IS NOT NULL"
```

**Goal:** Accumulate real usage data (target: 25+ sessions)

### Phase 3: Analyze Real Impact

```bash
# Generate report from real usage
python scripts/analyze_verification_metrics.py \
    --db ~/.local/share/talking_rock/riva.db \
    --output real_usage_report.md

# Review findings
cat real_usage_report.md
```

**Goal:** Measure actual improvement in real-world scenarios

### Phase 4: Update Claims

Use findings to update README.md with measured claims:

**Before:**
> "RIVA achieves 80% → 98% confidence improvement"

**After (example):**
> "RIVA catches 18 errors per 25 sessions (72% error prevention) with 1.2s average overhead"

---

## Understanding the Metrics

### Success Rates

- **Overall Success Rate**: % of sessions that eventually succeeded
- **First-Try Success Rate**: % of sessions that succeeded without retries
  - **This is the key metric** - higher = better

### Verification Impact

- **Errors Caught**: Number of errors caught by verification before showing user
- **Catch Rate**: % of checks that failed (higher = more errors caught)
  - Syntax: 15% = 15% of syntax checks failed (verification caught them)
  - Semantic: 22% = 22% of semantic checks failed (caught typos, imports)
  - etc.

### Confidence Calibration

- **Accuracy**: How often predictions match reality
- **High-Confidence Accuracy**: When RIVA says ≥0.9, how often is it right?
  - Target: ≥90% (calibrated predictions)
- **Calibration Error**: Mean squared error between prediction and actual
  - Lower = better calibrated

### Time Overhead

- **Average Verification Time**: Extra time spent verifying per session
- **Time Overhead %**: Verification time as % of total time
  - Example: 1.5s verification / 10s total = 15% overhead

---

## Interpreting Results

### Good Results

✅ **First-try success rate: 80%+**
✅ **Errors caught: 10-20 per 25 sessions**
✅ **High-confidence accuracy: 90%+**
✅ **Time overhead: 1-3s (10-20%)**

**Verdict:** Verification provides clear value - catches errors with acceptable overhead

### Needs Improvement

❌ **First-try success rate: <70%**
❌ **Errors caught: <5 per 25 sessions**
❌ **High-confidence accuracy: <85%**
❌ **Time overhead: >5s (>30%)**

**Verdict:** Either verification isn't effective, or overhead is too high

### What to Optimize

**If catch rates are low (<10% per layer):**
- Layers aren't catching many errors
- Either: code quality is already high, or layers need tuning

**If time overhead is high (>3s):**
- Behavioral layer (pytest) might be slow
- Consider faster test strategies or caching

**If confidence calibration is poor (<80%):**
- Predictions aren't reliable
- Intent layer might need better prompts

---

## FAQ

**Q: How many sessions do I need for valid analysis?**
A: Minimum 20-25 sessions for statistical significance. More is better.

**Q: What if I don't have a database yet?**
A: Use RIVA normally and it will automatically create `riva_metrics` table and collect data.

**Q: Can I disable verification to compare?**
A: Yes, set `enable_multilayer_verification=False` in WorkContext (for benchmarking only)

**Q: Which tool should I use?**
A:
- **Real usage:** Use `analyze_verification_metrics.py`
- **Controlled testing:** Use `benchmark_verification.py`
- **Best:** Use both for comprehensive validation

**Q: How do I know if verification is worth the tradeoff?**
A: Calculate: errors_caught / (verification_time / 1000)
- Example: 18 errors / 1.2s = 15 errors per second → worth it!

---

## Next Steps

1. **Run benchmarks** to establish baseline
2. **Collect real usage data** (use RIVA normally)
3. **Analyze results** with metrics analysis tool
4. **Update README** with measured claims
5. **Optimize** based on findings (if needed)

This data-driven approach ensures RIVA's value proposition is provable, not just aspirational.
