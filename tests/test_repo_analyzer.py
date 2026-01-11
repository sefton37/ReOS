"""Test ActRepoAnalyzer by analyzing talking_rock itself.

This demonstrates the repo understanding system in action.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reos.code_mode.repo_analyzer import ActRepoAnalyzer, RepoContext
from reos.play_fs import Act
from reos.providers.ollama import OllamaProvider


async def test_analyze_talking_rock():
    """Analyze talking_rock repo to demonstrate the system."""
    print("\n" + "="*70)
    print("REPO UNDERSTANDING SYSTEM - Demo on talking_rock")
    print("="*70)

    # Create a mock Act for talking_rock
    repo_path = Path(__file__).parent.parent.resolve()
    act = Act(
        act_id="talking_rock_demo",
        title="Talking Rock Development",
        repo_path=str(repo_path),
        artifact_type="python",
        active=True,
    )

    print(f"\nAnalyzing: {act.title}")
    print(f"Repo path: {repo_path}")

    # Check if Ollama is available
    try:
        llm = OllamaProvider()
        print(f"LLM provider: {llm.provider_type}")

        # Check health
        health = llm.check_health()
        if not health.available:
            print(f"\n❌ Ollama not available: {health.error}")
            print("   Install: curl -fsSL https://ollama.com/install.sh | sh")
            print("   Then run: ollama pull llama3.2:3b")
            return

        print(f"LLM ready: {health.message}")

    except Exception as e:
        print(f"\n❌ Could not initialize LLM: {e}")
        return

    # Create analyzer
    print("\nCreating ActRepoAnalyzer...")
    analyzer = ActRepoAnalyzer(act, llm)
    print(f"Context will be saved to: {analyzer.context_dir}")

    # Run analysis
    print("\n" + "-"*70)
    print("ANALYZING REPOSITORY STRUCTURE (using cheap local LLM)")
    print("-"*70)

    try:
        context = await analyzer.analyze_if_needed()

        # Display results
        print("\n✅ ANALYSIS COMPLETE!")
        print("\n" + "="*70)
        print("DISCOVERED STRUCTURE")
        print("="*70)

        if context.structure:
            struct = context.structure

            print(f"\n📊 Components ({len(struct.components)}):")
            for comp in struct.components:
                print(f"  • {comp['name']}")
                print(f"    Purpose: {comp['purpose']}")
                print(f"    Path: {comp.get('path', 'N/A')}")
                print()

            print(f"🚀 Entry Points ({len(struct.entry_points)}):")
            for ep in struct.entry_points:
                print(f"  • {ep}")

            print(f"\n🧪 Test Strategy:")
            print(f"  {struct.test_strategy}")

            print(f"\n📚 Documentation:")
            print(f"  {struct.docs_location}")

            print(f"\n⏰ Analyzed at: {struct.analyzed_at}")

            # Show where it's saved
            analysis_file = analyzer.context_dir / "repo_analysis.json"
            if analysis_file.exists():
                print(f"\n💾 Analysis saved to:")
                print(f"   {analysis_file}")
                print(f"   Size: {analysis_file.stat().st_size} bytes")

        else:
            print("\n⚠️  No structure analysis available")

        print("\n" + "="*70)
        print("NEXT STEPS")
        print("="*70)
        print("\n1. This context will be injected into ProjectMemory")
        print("2. When generating actions, models will see:")
        print("   - Component organization")
        print("   - Entry points")
        print("   - Test strategy")
        print("\n3. Future analyses will add:")
        print("   - Architecture patterns (MVC, Clean, etc.)")
        print("   - Coding conventions (naming, imports)")
        print("   - Type definitions (User.id: str)")
        print("   - Import dependencies")
        print("   - Anti-patterns to avoid")
        print("\n4. Cost for this analysis: ~$0.0002 (300x cheaper than GPT-4!)")
        print("\n" + "="*70)

        return context

    except Exception as e:
        print(f"\n❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("\n🔬 Testing Repo Understanding System")
    print("   Using talking_rock as the test subject")

    # Run async analysis
    context = asyncio.run(test_analyze_talking_rock())

    if context and context.structure:
        print("\n✅ SUCCESS: Repo analysis working!")
        sys.exit(0)
    else:
        print("\n⚠️  Analysis incomplete (may need Ollama setup)")
        sys.exit(1)
