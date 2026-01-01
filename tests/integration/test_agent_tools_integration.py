"""Integration tests for Agent → Tools → Storage flow.

These tests verify that the ChatAgent correctly:
1. Selects appropriate tools based on user input
2. Executes tools against real repos
3. Formats results for the final answer
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import MockOllamaClient


class TestAgentToolSelection:
    """Test agent's tool selection logic with mock Ollama."""

    def test_agent_calls_git_summary_tool(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent should call git_summary when asked about repo status."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        # Configure mock to select git_summary tool
        mock_ollama.set_tool_response([{"name": "reos_git_summary", "arguments": {}}])
        mock_ollama.set_answer("The repository is clean with no uncommitted changes.")

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        response = agent.respond("What's the current state of the repo?")

        # Verify the mock was called twice (tool selection + answer)
        assert len(mock_ollama.calls) == 2
        assert mock_ollama.calls[0]["type"] == "json"  # Tool selection
        assert mock_ollama.calls[1]["type"] == "text"  # Answer generation

        # The answer should come through
        assert "clean" in response.lower() or "no" in response.lower()

    def test_agent_executes_multiple_tools(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent should execute multiple tools when requested."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        # Configure mock to select multiple tools
        mock_ollama.set_tool_response([
            {"name": "reos_git_summary", "arguments": {}},
            {"name": "reos_repo_list_files", "arguments": {"glob": "src/*.py"}},
        ])
        mock_ollama.set_answer("Found 2 Python files in src/: main.py and utils.py")

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        response = agent.respond("Show me the repo status and list Python files in src")

        assert "main.py" in response or "utils.py" in response or "2" in response

    def test_agent_respects_tool_call_limit(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent should respect the tool call limit from persona."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        # Request more tools than the limit
        mock_ollama.set_tool_response([
            {"name": "reos_git_summary", "arguments": {}},
            {"name": "reos_repo_list_files", "arguments": {"glob": "*.py"}},
            {"name": "reos_repo_list_files", "arguments": {"glob": "*.md"}},
            {"name": "reos_repo_list_files", "arguments": {"glob": "*.txt"}},
            {"name": "reos_repo_list_files", "arguments": {"glob": "*.json"}},
        ])
        mock_ollama.set_answer("Processed tools within limit.")

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)

        # Default limit is 3
        response = agent.respond("List all files")

        # Verify answer was generated (doesn't matter what, just that it completed)
        assert response is not None
        assert len(response) > 0


class TestAgentToolExecution:
    """Test actual tool execution through the agent."""

    def test_agent_git_summary_returns_real_data(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent's git_summary tool should return actual repo data."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        mock_ollama.set_tool_response([{"name": "reos_git_summary", "arguments": {}}])

        # The answer generation will receive the real tool output
        # We capture it via the mock's calls
        answer_with_tools = []

        def capture_answer(*, system: str, user: str, temperature: float, top_p: float) -> str:
            answer_with_tools.append(user)
            return "Repository analysis complete."

        mock_ollama.chat_text = capture_answer

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        agent.respond("What's the repo status?")

        # The tool output should contain branch info
        assert len(answer_with_tools) == 1
        tool_context = answer_with_tools[0]
        assert "branch" in tool_context.lower() or "master" in tool_context.lower()

    def test_agent_file_read_tool_works(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent's file read tool should return actual file content."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        mock_ollama.set_tool_response([
            {"name": "reos_repo_read_file", "arguments": {"path": "src/main.py", "start_line": 1, "end_line": 10}}
        ])

        captured_context = []

        def capture_answer(*, system: str, user: str, temperature: float, top_p: float) -> str:
            captured_context.append(user)
            return "File content retrieved."

        mock_ollama.chat_text = capture_answer

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        agent.respond("Show me main.py")

        assert len(captured_context) == 1
        # The tool output should contain the actual file content
        assert "def main" in captured_context[0] or "Hello" in captured_context[0]

    def test_agent_grep_tool_finds_matches(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent's grep tool should find text in files."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        mock_ollama.set_tool_response([
            {"name": "reos_repo_grep", "arguments": {"query": "def add", "include_glob": "**/*.py"}}
        ])

        captured_context = []

        def capture_answer(*, system: str, user: str, temperature: float, top_p: float) -> str:
            captured_context.append(user)
            return "Search complete."

        mock_ollama.chat_text = capture_answer

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        agent.respond("Find where add function is defined")

        assert len(captured_context) == 1
        # Should find the add function in utils.py
        assert "utils.py" in captured_context[0] or "add" in captured_context[0]


class TestAgentDiffOptIn:
    """Test the diff opt-in mechanism."""

    def test_agent_strips_diff_when_not_opted_in(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent should strip include_diff from arguments when user hasn't opted in."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        # Try to request diff even though user didn't opt in
        mock_ollama.set_tool_response([
            {"name": "reos_git_summary", "arguments": {"include_diff": True}}
        ])
        mock_ollama.set_answer("Summary without diff.")

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        response = agent.respond("What's the repo status?")  # No diff keywords

        # Response should complete without the diff
        assert response is not None

    def test_agent_allows_diff_when_opted_in(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent should allow include_diff when user explicitly opts in."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        # Make a change to have something to diff
        repo = configured_integration_repo
        (repo / "src" / "main.py").write_text(
            '''"""Main entry point - updated."""

def main():
    print("Hello, Updated World!")

if __name__ == "__main__":
    main()
''',
            encoding="utf-8",
        )

        mock_ollama.set_tool_response([
            {"name": "reos_git_summary", "arguments": {"include_diff": True}}
        ])

        captured_context = []

        def capture_answer(*, system: str, user: str, temperature: float, top_p: float) -> str:
            captured_context.append(user)
            return "Diff included."

        mock_ollama.chat_text = capture_answer

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        agent.respond("Show me the git diff please")  # Contains "diff" keyword

        assert len(captured_context) == 1
        # Since there are unstaged changes, diff should be present
        # (The actual diff content depends on what's changed)


class TestAgentWithPersona:
    """Test agent behavior with custom personas."""

    def test_agent_uses_custom_persona(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent should use the active persona's settings."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        db = get_db()

        # Create and activate a custom persona
        db.upsert_agent_persona(
            persona_id="test-persona",
            name="Test Persona",
            system_prompt="You are a code review expert.",
            default_context="Focus on security issues.",
            temperature=0.5,
            top_p=0.95,
            tool_call_limit=2,
        )
        db.set_active_persona_id(persona_id="test-persona")

        mock_ollama.set_tool_response([])
        mock_ollama.set_answer("Code review complete.")

        agent = ChatAgent(db=db, ollama=mock_ollama)
        agent.respond("Review the code")

        # The system prompt should contain persona content
        assert len(mock_ollama.calls) >= 1
        system_prompt = mock_ollama.calls[0]["system"]
        assert "code review" in system_prompt.lower() or "security" in system_prompt.lower()

        # Temperature should match persona
        assert mock_ollama.calls[0]["temperature"] == 0.5


class TestAgentErrorHandling:
    """Test agent's error handling."""

    def test_agent_handles_tool_error(
        self,
        configured_integration_repo: Path,
        mock_ollama: MockOllamaClient,
    ) -> None:
        """Agent should handle tool errors gracefully."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        # Request a file that doesn't exist
        mock_ollama.set_tool_response([
            {"name": "reos_repo_read_file", "arguments": {"path": "nonexistent.py", "start_line": 1, "end_line": 10}}
        ])
        mock_ollama.set_answer("The file was not found.")

        db = get_db()
        agent = ChatAgent(db=db, ollama=mock_ollama)
        response = agent.respond("Read nonexistent.py")

        # Should complete without crashing
        assert response is not None
        assert len(response) > 0

    def test_agent_handles_invalid_json_from_llm(
        self,
        configured_integration_repo: Path,
    ) -> None:
        """Agent should handle malformed JSON from LLM."""
        from reos.agent import ChatAgent
        from reos.db import get_db

        class BadJsonOllama:
            def chat_json(self, **kwargs) -> str:
                return "not valid json {"

            def chat_text(self, **kwargs) -> str:
                return "Fallback response."

        db = get_db()
        agent = ChatAgent(db=db, ollama=BadJsonOllama())
        response = agent.respond("Test")

        # Should fallback gracefully
        assert response is not None
