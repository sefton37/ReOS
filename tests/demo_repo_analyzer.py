"""Demonstrate ActRepoAnalyzer - shows what it discovers about talking_rock.

This demo works even without Ollama by showing the analysis structure.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reos.code_mode.repo_analyzer import ActRepoAnalyzer
from reos.play_fs import Act


def demo_directory_tree():
    """Show what the analyzer sees when it looks at talking_rock."""
    print("\n" + "="*70)
    print("STEP 1: DIRECTORY TREE ANALYSIS")
    print("="*70)
    print("\nThis is what the local LLM sees when analyzing structure:")
    print()

    # Create mock Act
    repo_path = Path(__file__).parent.parent.resolve()
    act = Act(
        act_id="talking_rock_demo",
        title="Talking Rock Development",
        repo_path=str(repo_path),
        artifact_type="python",
        active=True,
    )

    # Create analyzer (will fail on LLM but can show tree)
    from unittest.mock import Mock
    mock_llm = Mock()

    try:
        analyzer = ActRepoAnalyzer(act, mock_llm)

        # Get the tree that would be sent to LLM
        tree = analyzer._get_directory_tree(max_depth=3)

        print(tree)
        print()
        print("="*70)
        print()

        return tree

    except Exception as e:
        print(f"Could not create analyzer: {e}")
        return None


def show_example_analysis():
    """Show what a completed analysis would look like."""
    print("\n" + "="*70)
    print("STEP 2: WHAT LOCAL LLM DISCOVERS")
    print("="*70)
    print("\nThe cheap local LLM (Llama3, ~$0.0007 cost) analyzes the tree and")
    print("code samples to extract this understanding:")
    print()

    # This is what we'd expect from analyzing talking_rock
    example_components = [
        {
            "name": "src/reos/code_mode",
            "purpose": "RIVA - Recursive Intention-Verification Architecture for code generation",
            "path": "src/reos/code_mode"
        },
        {
            "name": "src/reos/code_mode/optimization",
            "purpose": "Verification layers, metrics, trust budget, pattern learning",
            "path": "src/reos/code_mode/optimization"
        },
        {
            "name": "src/reos/providers",
            "purpose": "LLM provider integrations (Anthropic, Ollama, OpenAI)",
            "path": "src/reos/providers"
        },
        {
            "name": "src/reos/services",
            "purpose": "Play service, session management, HTTP services",
            "path": "src/reos/services"
        },
        {
            "name": "tests",
            "purpose": "Test suite for all components",
            "path": "tests"
        },
        {
            "name": "scripts",
            "purpose": "Analysis and benchmarking scripts",
            "path": "scripts"
        },
    ]

    example_entry_points = [
        "src/reos/__init__.py",
        "src/reos/code_mode/intention.py (work function)",
        "scripts/benchmark_verification.py",
        "scripts/analyze_verification_metrics.py",
    ]

    example_test_strategy = "pytest with tests/ directory, integration tests for RIVA"

    example_docs = "README.md, inline docstrings, and assessment docs (*.md)"

    print("📊 STRUCTURE ANALYSIS:")
    print("\nComponents discovered:")
    for comp in example_components:
        print(f"  • {comp['name']}")
        print(f"    {comp['purpose']}")

    print(f"\n\nEntry points discovered:")
    for ep in example_entry_points:
        print(f"  • {ep}")

    print(f"\n\nTest strategy: {example_test_strategy}")
    print(f"Documentation: {example_docs}")

    # Convention analysis
    print("\n\n🎨 CONVENTION ANALYSIS:")
    print("\nCoding patterns discovered:")
    print("  • Import style: 'from X import Y', grouped by stdlib/third-party/local")
    print("  • Class naming: PascalCase, often with descriptive suffixes")
    print("    Example: ExecutionMetrics, WorkContext, StructureAnalysis")
    print("  • Function naming: snake_case throughout")
    print("    Example: determine_next_action, analyze_if_needed")
    print("  • Type hints: Comprehensive usage with modern Python syntax")
    print("    Example: list[dict[str, str]], ActInfo | None")
    print("  • Docstring style: Google-style with Args/Returns/Raises sections")
    print("  • Error handling: Specific exception types, try/except with logging")

    print("\n" + "="*70)


def show_context_injection():
    """Show how this gets injected into action generation."""
    print("\n" + "="*70)
    print("STEP 3: CONTEXT INJECTION (Priority 0 Active!)")
    print("="*70)
    print("\nThis analysis gets injected into ProjectMemory, then into action prompts:")
    print()

    prompt_example = """INTENTION: Add user authentication to the API

Existing files: src/reos/code_mode/intention.py, src/reos/services/...

PROJECT DECISIONS (must respect):
- Architecture: Code generation via RIVA in src/reos/code_mode [ANALYZED]
- Entry point: Main work loop is work() in intention.py [ANALYZED]
- Test strategy: Use pytest with tests/ directory [ANALYZED]

CODE PATTERNS (must follow):
- Import style: 'from X import Y', grouped by type [ANALYZED]
- Class naming: PascalCase with descriptive suffixes (e.g., AuthService) [ANALYZED]
- Function naming: snake_case (e.g., authenticate_user) [ANALYZED]
- Type hints: Always use for params and returns [ANALYZED]
- Docstrings: Google-style with Args/Returns sections [ANALYZED]

PROJECT STRUCTURE (must follow):
Components:
- src/reos/code_mode = RIVA verification system
- src/reos/services = HTTP and Play services
- tests/ = Test suite

Entry points:
- src/reos/code_mode/intention.py (work function)

What should we try next?"""

    print(prompt_example)
    print("\n" + "="*70)


def show_cost_advantage():
    """Show the cost comparison."""
    print("\n" + "="*70)
    print("STEP 4: COST ADVANTAGE (Why This Works)")
    print("="*70)
    print()

    print("📊 COST COMPARISON:")
    print("  Structure analysis: ~2,000 tokens")
    print("  Convention analysis: ~5,000 tokens")
    print("  Total per repo: ~7,000 tokens")
    print()
    print("  With GPT-4:")
    print("    7K tokens × $0.03/1K = $0.21 per analysis")
    print()
    print("  With Llama3 (local):")
    print("    7K tokens × $0.0001/1K = $0.0007 per analysis")
    print()
    print("  💰 SAVINGS: 300x cheaper!")
    print()
    print("  This means:")
    print("  • Can run 1000 analyses for cost of 3.3 GPT-4 calls")
    print("  • Can analyze repo every session start (< $0.01)")
    print("  • Can re-analyze after every git push (< $0.01)")
    print("  • Can run comprehensive analysis on every file change")
    print("  • Big tech can't afford this at scale - we can!")
    print()
    print("="*70)


def show_next_steps():
    """Show what comes next."""
    print("\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)
    print()

    print("✅ COMPLETED:")
    print("  [P0] ProjectMemory injection into action generation")
    print("  [P0] Repo analyzer foundation (structure analysis)")
    print("  [P0] Convention analysis (naming, imports, style)")
    print()

    print("📋 REMAINING (Phase 1 - This Week):")
    print("  1. Test with actual Ollama (requires httpx dependency)")
    print("  2. Add type analysis (User.id: str, etc.)")
    print("  3. Wire into session initialization")
    print("  4. Test injection into ProjectMemory")
    print()

    print("🎯 FUTURE (Phases 2-3):")
    print("  Phase 2:")
    print("    • Architecture detection (MVC, Clean, etc.)")
    print("    • Import graph analysis (circular detection)")
    print("    • Anti-pattern detection")
    print()
    print("  Phase 3:")
    print("    • Incremental analysis (only changed files)")
    print("    • Git commit triggers")
    print("    • Quality metrics")
    print()
    print("="*70)


if __name__ == "__main__":
    print("\n🔬 REPO UNDERSTANDING SYSTEM - Demonstration")
    print("   Using talking_rock as example")
    print()

    # Run demonstration
    tree = demo_directory_tree()

    if tree:
        show_example_analysis()
        show_context_injection()
        show_cost_advantage()
        show_next_steps()

        print("\n✅ Demonstration complete!")
        print("\n💡 KEY INSIGHT:")
        print("   We can build comprehensive repo understanding for pennies,")
        print("   then inject it into every action. This is our competitive")
        print("   advantage - big tech can't afford to run 100 analyses per")
        print("   session. We can (300x cheaper with local LLMs).")
        print()

        sys.exit(0)
    else:
        sys.exit(1)
