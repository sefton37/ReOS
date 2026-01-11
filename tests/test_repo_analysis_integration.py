"""Test repo analysis integration with session initialization.

This test demonstrates the full flow:
1. Session starts with Act and ProjectMemory
2. ActRepoAnalyzer analyzes repository
3. Analysis results are converted to ProjectMemory entries
4. WorkContext is created with populated ProjectMemory
5. Action generation receives repo context
"""

import asyncio
from pathlib import Path
from unittest.mock import Mock


def test_analyze_repo_and_populate_memory_integration():
    """Test that repo analysis populates ProjectMemory correctly."""
    from reos.code_mode.optimization.factory import analyze_repo_and_populate_memory
    from reos.code_mode.repo_analyzer import StructureAnalysis, ConventionAnalysis, TypeAnalysis, RepoContext

    # Create mock Act
    act = Mock()
    act.act_id = "test-act"
    act.title = "Test Project"
    act.repo_path = str(Path(__file__).parent.parent)  # talking_rock repo

    # Create mock LLM provider (won't actually be called in this test)
    llm = Mock()

    # Create mock ProjectMemory
    project_memory = Mock()
    project_memory.record_decision = Mock()
    project_memory.record_pattern = Mock()

    # Create mock analyzer that returns predefined results
    mock_context = RepoContext(
        structure=StructureAnalysis(
            components=[
                {"name": "src/reos", "purpose": "Main package", "path": "src/reos"},
            ],
            entry_points=["src/reos/__init__.py"],
            test_strategy="pytest with tests/ directory",
            docs_location="README.md",
            analyzed_at="2024-01-01T00:00:00Z",
        ),
        conventions=ConventionAnalysis(
            import_style="from X import Y",
            class_naming="PascalCase",
            function_naming="snake_case",
            type_hints_usage="Always",
            docstring_style="Google-style",
            error_handling="Specific exceptions",
            examples={
                "import": "from pathlib import Path",
                "class": "class UserModel",
                "function": "def get_user()",
            },
            analyzed_at="2024-01-01T00:00:00Z",
        ),
        types=TypeAnalysis(
            data_models=[
                {
                    "name": "ExecutionMetrics",
                    "purpose": "Track execution metrics",
                    "file": "src/reos/code_mode/optimization/metrics.py",
                    "key_fields": {"session_id": "str", "started_at": "str"},
                }
            ],
            config_types=[],
            error_types=[],
            other_types=[],
            analyzed_at="2024-01-01T00:00:00Z",
        ),
    )

    # Patch ActRepoAnalyzer
    async def mock_analyze():
        return mock_context

    # Run the integration
    async def run_test():
        # Patch the analyzer
        import reos.code_mode.optimization.factory as factory_module
        original_analyzer = getattr(factory_module, 'ActRepoAnalyzer', None)

        # Create mock analyzer class
        mock_analyzer_class = Mock()
        mock_analyzer_instance = Mock()
        mock_analyzer_instance.analyze_if_needed = mock_analyze
        mock_analyzer_class.return_value = mock_analyzer_instance

        # Temporarily replace
        factory_module.ActRepoAnalyzer = mock_analyzer_class

        try:
            # Run the analysis
            await analyze_repo_and_populate_memory(
                act=act,
                llm=llm,
                project_memory=project_memory,
            )

            # Verify decisions were recorded
            assert project_memory.record_decision.called
            decision_calls = [call[1] for call in project_memory.record_decision.call_args_list]

            # Check test strategy decision
            test_strategy_recorded = any(
                "pytest" in str(call) for call in decision_calls
            )
            assert test_strategy_recorded, "Test strategy should be recorded as decision"

            # Verify patterns were recorded
            assert project_memory.record_pattern.called
            pattern_calls = [call[1] for call in project_memory.record_pattern.call_args_list]

            # Check import style pattern
            import_pattern_recorded = any(
                "import_style" in str(call) or "Import style" in str(call)
                for call in pattern_calls
            )
            assert import_pattern_recorded, "Import style should be recorded as pattern"

            # Check class naming pattern
            class_naming_recorded = any(
                "class_naming" in str(call) or "Class naming" in str(call)
                for call in pattern_calls
            )
            assert class_naming_recorded, "Class naming should be recorded as pattern"

            # Check type analysis pattern
            type_pattern_recorded = any(
                "ExecutionMetrics" in str(call)
                for call in pattern_calls
            )
            assert type_pattern_recorded, "Type definitions should be recorded as patterns"

        finally:
            # Restore
            if original_analyzer:
                factory_module.ActRepoAnalyzer = original_analyzer

    # Run async test
    asyncio.run(run_test())


def test_create_optimized_context_with_repo_analysis_api():
    """Test that create_optimized_context_with_repo_analysis has correct signature."""
    from reos.code_mode.optimization import create_optimized_context_with_repo_analysis
    import inspect

    # Verify it's async
    assert inspect.iscoroutinefunction(create_optimized_context_with_repo_analysis)

    # Verify signature
    sig = inspect.signature(create_optimized_context_with_repo_analysis)
    assert "act" in sig.parameters
    assert "local_llm" in sig.parameters
    assert "project_memory" in sig.parameters
    assert "enable_repo_analysis" in sig.parameters


def test_integration_exports():
    """Test that new integration functions are exported."""
    from reos.code_mode.optimization import (
        analyze_repo_and_populate_memory,
        create_optimized_context_with_repo_analysis,
    )

    # Just verify they're importable
    assert callable(analyze_repo_and_populate_memory)
    assert callable(create_optimized_context_with_repo_analysis)


if __name__ == "__main__":
    print("Running repo analysis integration tests...")
    test_analyze_repo_and_populate_memory_integration()
    print("✅ test_analyze_repo_and_populate_memory_integration passed")

    test_create_optimized_context_with_repo_analysis_api()
    print("✅ test_create_optimized_context_with_repo_analysis_api passed")

    test_integration_exports()
    print("✅ test_integration_exports passed")

    print("\n✨ All integration tests passed!")
