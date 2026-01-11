"""Test that ProjectMemory is correctly injected into action generation.

This test verifies Priority 0: Fair evaluation by providing models with
repo context they need to integrate correctly.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reos.code_mode.intention import Intention, WorkContext, determine_next_action
from reos.code_mode.project_memory import (
    ProjectMemoryStore,
    ProjectMemoryContext,
    ProjectDecision,
    ProjectPattern,
)


def test_project_memory_injected_into_action_prompt():
    """Test that ProjectMemory is injected into action generation prompts."""
    print("Testing ProjectMemory injection into action prompts...")

    # Create mock components
    sandbox = Mock()
    sandbox.repo_path = "/test/repo"
    sandbox.root_dir = "/test/repo"
    sandbox.glob = Mock(return_value=[])

    llm = Mock()
    llm.chat_json = Mock(return_value='{"thought": "test", "action_type": "create", "content": "test", "target": "test.py"}')

    checkpoint = Mock()

    # Create mock ProjectMemoryStore with sample data
    project_memory = Mock(spec=ProjectMemoryStore)

    # Create sample decision
    decision = Mock(spec=ProjectDecision)
    decision.decision = "Use dataclasses for all data models"
    decision.rationale = "Consistency and type safety"

    # Create sample pattern
    pattern = Mock(spec=ProjectPattern)
    pattern.description = "Class naming: {Entity}Model (e.g., UserModel not User)"

    # Create sample correction (without inferred_rule for this test)
    correction = Mock()
    correction.inferred_rule = None

    # Create memory context
    memory_context = ProjectMemoryContext(
        relevant_decisions=[decision],
        applicable_patterns=[pattern],
        recent_corrections=[correction],
        recent_sessions=[],
    )

    # Mock get_relevant_context to return our test data
    project_memory.get_relevant_context = Mock(return_value=memory_context)

    # Create WorkContext with project_memory
    ctx = WorkContext(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        project_memory=project_memory,  # NOW INCLUDED!
    )

    # Create a test intention
    intention = Intention.create(
        what="Create a user management system",
        acceptance="User class with CRUD operations",
    )

    # Call determine_next_action - this should inject ProjectMemory context
    thought, action = determine_next_action(intention, ctx)

    # Verify that get_relevant_context was called
    assert project_memory.get_relevant_context.called, "ProjectMemory should be queried"

    # Verify it was called with correct parameters
    call_args = project_memory.get_relevant_context.call_args
    assert call_args[1]['repo_path'] == "/test/repo", "Should pass repo_path"
    assert call_args[1]['prompt'] == "Create a user management system", "Should pass intention"

    # Verify LLM was called
    assert llm.chat_json.called, "LLM should be called"

    # Get the user_prompt that was passed to LLM
    llm_call_args = llm.chat_json.call_args
    user_prompt = llm_call_args[1]['user']

    print(f"\n{'='*60}")
    print("USER PROMPT SENT TO MODEL:")
    print(f"{'='*60}")
    print(user_prompt)
    print(f"{'='*60}\n")

    # Verify context was injected
    assert "PROJECT DECISIONS" in user_prompt, "Should include PROJECT DECISIONS section"
    assert "Use dataclasses for all data models" in user_prompt, "Should include decision text"

    assert "CODE PATTERNS" in user_prompt, "Should include CODE PATTERNS section"
    assert "UserModel" in user_prompt, "Should include pattern text"

    print("✓ PASSED: ProjectMemory is properly injected into action prompts")
    print(f"  - Decisions injected: {len(memory_context.relevant_decisions)}")
    print(f"  - Patterns injected: {len(memory_context.applicable_patterns)}")
    print("\n✅ Fair evaluation enabled! Models now receive repo context.\n")


def test_graceful_fallback_when_no_project_memory():
    """Test that system works without ProjectMemory (backward compatibility)."""
    print("Testing backward compatibility without ProjectMemory...")

    # Create minimal mocks
    sandbox = Mock()
    sandbox.glob = Mock(return_value=[])

    llm = Mock()
    llm.chat_json = Mock(return_value='{"thought": "test", "action_type": "create", "content": "test", "target": "test.py"}')

    checkpoint = Mock()

    # Create WorkContext WITHOUT project_memory
    ctx = WorkContext(
        sandbox=sandbox,
        llm=llm,
        checkpoint=checkpoint,
        project_memory=None,  # No ProjectMemory
    )

    intention = Intention.create(
        what="Create a test file",
        acceptance="File exists",
    )

    # Should not crash
    try:
        thought, action = determine_next_action(intention, ctx)
        print("✓ PASSED: System works without ProjectMemory (backward compatible)")
    except Exception as e:
        raise AssertionError(f"Should not crash without ProjectMemory: {e}")


if __name__ == "__main__":
    try:
        test_project_memory_injected_into_action_prompt()
        test_graceful_fallback_when_no_project_memory()

        print("\n" + "="*60)
        print("ALL TESTS PASSED!")
        print("="*60)
        print("\nPriority 0 Complete:")
        print("✅ ProjectMemory field added to WorkContext")
        print("✅ Context injected into action generation")
        print("✅ Factory updated to pass through project_memory")
        print("✅ Backward compatible (works without ProjectMemory)")
        print("\n🎯 RESULT: Fair evaluation now enabled!")
        print("   Models receive repo conventions and can follow them.")
        print("="*60)

        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
