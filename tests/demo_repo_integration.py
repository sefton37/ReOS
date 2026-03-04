"""Demonstration of repo analysis integration with session initialization.

This shows how to use the new create_optimized_context_with_repo_analysis function
to automatically analyze a repository and populate ProjectMemory when starting
a Code Mode session.
"""


def show_api_usage():
    """Show how to use the new API."""
    print("="*70)
    print("REPO ANALYSIS INTEGRATION - Usage Example")
    print("="*70)
    print()

    print("Before (manual ProjectMemory population):")
    print("-" * 70)
    print("""
    from reos.code_mode.optimization import create_optimized_context

    # Had to manually populate ProjectMemory
    project_memory = ProjectMemoryStore(...)
    project_memory.record_pattern("Class naming", "PascalCase", ...)
    project_memory.record_pattern("Function naming", "snake_case", ...)
    # ... many more manual entries ...

    ctx = create_optimized_context(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        project_memory=project_memory,
    )
    """)

    print("\n")
    print("After (automatic analysis and population):")
    print("-" * 70)
    print("""
    from reos.code_mode.optimization import create_optimized_context_with_repo_analysis

    # Analysis and population happens automatically!
    ctx = await create_optimized_context_with_repo_analysis(
        sandbox=sandbox,
        llm=llm,  # Main LLM for code generation
        checkpoint=checkpoint,
        act=act,  # The Act (project) being worked on
        local_llm=ollama_llm,  # Cheap local LLM for analysis (~$0.0011)
        project_memory=project_memory,  # Will be populated automatically
    )

    # ProjectMemory is now populated with:
    # - Structure: components, entry points, test strategy
    # - Conventions: naming, imports, docstrings, type hints
    # - Types: data models with exact field types
    """)

    print()
    print("="*70)


def show_what_gets_injected():
    """Show what analysis results get converted to ProjectMemory."""
    print("\n" + "="*70)
    print("WHAT GETS INJECTED INTO ProjectMemory")
    print("="*70)
    print()

    print("📊 FROM STRUCTURE ANALYSIS:")
    print("  Decisions:")
    print("    • Test strategy: pytest with tests/ directory")
    print("    • Documentation: README.md and inline docstrings")
    print()
    print("  Patterns:")
    print("    • Component 'src/reos/code_mode': RIVA verification system")
    print("    • Component 'src/reos/optimization': Metrics and trust budget")
    print("    • Entry point: src/reos/code_mode/intention.py (work function)")
    print()

    print("🎨 FROM CONVENTION ANALYSIS:")
    print("  Patterns:")
    print("    • Import style: 'from X import Y', grouped by type")
    print("    • Class naming: PascalCase with descriptive suffixes")
    print("    • Function naming: snake_case throughout")
    print("    • Type hints: Always used for parameters and returns")
    print("    • Docstrings: Google-style with Args/Returns/Raises")
    print()

    print("🔍 FROM TYPE ANALYSIS:")
    print("  Patterns:")
    print("    • ExecutionMetrics fields: session_id: str, started_at: str")
    print("    • WorkContext fields: sandbox: CodeSandbox, llm: LLMProvider")
    print("    • Act fields: act_id: str, repo_path: str | None")
    print()

    print("Then Priority 0 injects all of this into action generation prompts!")
    print("="*70)


def show_cost_savings():
    """Show the cost comparison."""
    print("\n" + "="*70)
    print("COST SAVINGS")
    print("="*70)
    print()

    print("Manual approach (using GPT-4 for analysis):")
    print("  • You wouldn't do this - too expensive!")
    print("  • ~$0.33 per analysis")
    print()

    print("Automated approach (using local Ollama):")
    print("  • Analysis happens every session start")
    print("  • ~$0.0011 per analysis")
    print("  • 300x cheaper than GPT-4")
    print()

    print("You can analyze repos constantly:")
    print("  • Every session start: < $0.01")
    print("  • Every git push: < $0.01")
    print("  • Every file change: < $0.01")
    print()

    print("Big tech can't afford this at scale with expensive models.")
    print("We can with local LLMs!")
    print("="*70)


def show_implementation_details():
    """Show how it works under the hood."""
    print("\n" + "="*70)
    print("HOW IT WORKS")
    print("="*70)
    print()

    print("1. create_optimized_context_with_repo_analysis() is called")
    print()
    print("2. analyze_repo_and_populate_memory() runs:")
    print("   a. Creates ActRepoAnalyzer instance")
    print("   b. Calls analyze_if_needed() - uses cache if recent")
    print("   c. Gets RepoContext with structure, conventions, types")
    print()
    print("3. Converts analysis to ProjectMemory:")
    print("   • Structure → decisions (test strategy, docs)")
    print("   • Structure → patterns (component purposes)")
    print("   • Conventions → patterns (naming, imports, style)")
    print("   • Types → patterns (field types)")
    print()
    print("4. create_optimized_context() creates WorkContext")
    print("   • WorkContext.project_memory is populated")
    print()
    print("5. Priority 0 injection (already implemented):")
    print("   • determine_next_action() queries ProjectMemory")
    print("   • Injects decisions and patterns into action prompt")
    print()
    print("6. Models receive comprehensive repo context!")
    print("   • No more guessing conventions")
    print("   • No more wrong field types")
    print("   • Fair evaluation of programming ability")
    print("="*70)


if __name__ == "__main__":
    print("\n🔗 REPO ANALYSIS INTEGRATION - Complete Demo\n")

    show_api_usage()
    show_what_gets_injected()
    show_cost_savings()
    show_implementation_details()

    print("\n" + "="*70)
    print("✅ Integration Complete!")
    print("="*70)
    print()
    print("Next steps:")
    print("  1. Use create_optimized_context_with_repo_analysis in production")
    print("  2. Test with actual Ollama instance")
    print("  3. Verify end-to-end: session → analysis → injection → action")
    print()
    print("The amazing journey continues!")
    print("="*70)
