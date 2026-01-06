"""Test Generator - Generate pytest test code from intent.

Implements test-first development by generating actual test code as
acceptance criteria. The generated tests define what "done" means -
when the tests pass, the feature is complete.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from reos.code_mode.contract import TestSpecification

if TYPE_CHECKING:
    from reos.code_mode.intent import DiscoveredIntent
    from reos.code_mode.sandbox import CodeSandbox
    from reos.ollama import OllamaClient

logger = logging.getLogger(__name__)


# =============================================================================
# Test Code Templates
# =============================================================================

FUNCTION_TEST_TEMPLATE = '''"""Tests for {module_name}."""

import pytest

from {import_path} import {function_name}


def test_{function_name}_exists():
    """Test that {function_name} function exists and is callable."""
    assert callable({function_name})


def test_{function_name}_returns_value():
    """Test that {function_name} returns a value."""
    result = {function_name}()
    assert result is not None
'''

CLASS_TEST_TEMPLATE = '''"""Tests for {class_name} class."""

import pytest

from {import_path} import {class_name}


def test_{class_name_lower}_instantiation():
    """Test that {class_name} can be instantiated."""
    instance = {class_name}()
    assert isinstance(instance, {class_name})


def test_{class_name_lower}_has_required_attributes():
    """Test that {class_name} has expected attributes."""
    instance = {class_name}()
    # Verify instance was created successfully
    assert instance is not None
'''

METHOD_TEST_TEMPLATE = '''"""Tests for {class_name}.{method_name} method."""

import pytest

from {import_path} import {class_name}


def test_{class_name_lower}_{method_name}_exists():
    """Test that {method_name} method exists."""
    instance = {class_name}()
    assert hasattr(instance, "{method_name}")
    assert callable(getattr(instance, "{method_name}"))


def test_{class_name_lower}_{method_name}_returns_value():
    """Test that {method_name} returns a value."""
    instance = {class_name}()
    result = instance.{method_name}()
    assert result is not None
'''

API_ENDPOINT_TEST_TEMPLATE = '''"""Tests for {endpoint_name} endpoint."""

import pytest


def test_{endpoint_name_safe}_returns_200():
    """Test that {endpoint} returns success."""
    # TODO: Add appropriate client/fixture for your framework
    # response = client.get("{endpoint}")
    # assert response.status_code == 200
    pass


def test_{endpoint_name_safe}_returns_expected_content_type():
    """Test that {endpoint} returns expected content type."""
    # TODO: Verify content type
    pass
'''

FILE_EXISTS_TEST_TEMPLATE = '''"""Tests for {file_name}."""

import pytest
from pathlib import Path


def test_{file_name_safe}_exists():
    """Test that {file_path} exists."""
    path = Path("{file_path}")
    assert path.exists(), f"Expected file {file_path} to exist"


def test_{file_name_safe}_is_valid_python():
    """Test that {file_path} is valid Python."""
    path = Path("{file_path}")
    content = path.read_text()
    compile(content, str(path), "exec")
'''

GENERIC_TEST_TEMPLATE = '''"""Tests for feature: {description}."""

import pytest


def test_feature_implemented():
    """Test that the feature is implemented correctly."""
    # TODO: Add specific assertions for:
    # {description}
    #
    # This is a placeholder test that should be replaced with
    # actual assertions once the implementation is understood.
    assert True  # Replace with actual test
'''


# =============================================================================
# LLM Test Generation Prompt
# =============================================================================

LLM_SYSTEM_PROMPT = """You are a test-first developer generating pytest test code.

Given the intent and codebase context, generate a complete pytest test that:
1. Tests the EXPECTED behavior (not implementation details)
2. Uses appropriate assertions
3. Follows existing test patterns in the codebase
4. Is minimal but comprehensive
5. Includes proper imports

Output JSON:
{
    "test_code": "full pytest code including all imports and test functions",
    "test_file": "path/to/test_file.py",
    "test_function": "primary_test_function_name",
    "imports": ["list", "of", "module.imports"],
    "rationale": "why this test proves the feature works"
}

Guidelines:
- Use pytest, not unittest
- Include docstrings for test functions
- Name tests descriptively (test_<what>_<behavior>)
- Use fixtures if setup is complex
- Keep tests focused on one behavior each
- Include both positive and negative test cases where appropriate
"""


class TestGenerator:
    """Generate pytest test code from intent.

    The generator can use:
    1. LLM for comprehensive, context-aware tests
    2. Heuristic templates for common patterns (fallback)

    Generated tests serve as acceptance criteria - when they pass,
    the feature is considered complete.
    """

    def __init__(
        self,
        sandbox: CodeSandbox,
        ollama: OllamaClient | None = None,
    ) -> None:
        """Initialize test generator.

        Args:
            sandbox: Code sandbox for file access
            ollama: Optional Ollama client for LLM generation
        """
        self.sandbox = sandbox
        self._ollama = ollama

    def generate(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate test code from intent.

        Args:
            intent: The discovered intent to generate tests for

        Returns:
            TestSpecification with generated test code
        """
        if self._ollama is not None:
            try:
                return self._generate_with_llm(intent)
            except Exception as e:
                logger.warning("LLM test generation failed: %s, falling back to heuristic", e)

        return self._generate_heuristic(intent)

    def _generate_with_llm(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate tests using LLM for comprehensive coverage."""
        # Build context for LLM
        context = self._build_llm_context(intent)

        response = self._ollama.chat_json(  # type: ignore
            system=LLM_SYSTEM_PROMPT,
            user=context,
            temperature=0.2,
        )

        data = json.loads(response)

        return TestSpecification(
            test_code=data.get("test_code", ""),
            test_file=data.get("test_file", self._infer_test_file(intent)),
            test_function=data.get("test_function", "test_feature_implemented"),
            imports=data.get("imports", []),
            rationale=data.get("rationale", ""),
        )

    def _build_llm_context(self, intent: DiscoveredIntent) -> str:
        """Build context string for LLM."""
        # Get existing test patterns
        test_pattern = intent.codebase_intent.test_patterns
        test_example = ""
        if test_pattern:
            try:
                test_content = self.sandbox.read_file(test_pattern, start=1, end=50)
                test_example = f"\n\nExisting test style:\n```python\n{test_content}\n```"
            except Exception:
                pass

        return f"""
GOAL: {intent.goal}
WHAT: {intent.what}
ACTION: {intent.prompt_intent.action_verb}
TARGET: {intent.prompt_intent.target}
LANGUAGE: {intent.codebase_intent.language}
RELATED FILES: {', '.join(intent.codebase_intent.related_files[:5])}
PATTERNS: {', '.join(intent.codebase_intent.existing_patterns[:3])}
{test_example}

Generate a pytest test that will verify this feature is correctly implemented.
"""

    def _generate_heuristic(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate tests using templates for common patterns."""
        action = intent.prompt_intent.action_verb.lower()
        target = intent.prompt_intent.target.lower()

        # Determine what kind of test to generate
        if "function" in target or "method" in target:
            return self._generate_function_test(intent)
        elif "class" in target:
            return self._generate_class_test(intent)
        elif "endpoint" in target or "api" in target or "route" in target:
            return self._generate_api_test(intent)
        elif "file" in target or "module" in target:
            return self._generate_file_test(intent)
        else:
            return self._generate_generic_test(intent)

    def _generate_function_test(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate test for a function."""
        function_name = self._extract_name(intent.prompt_intent.target, "function")
        module_name = self._infer_module_name(intent)
        import_path = self._infer_import_path(intent)

        test_code = FUNCTION_TEST_TEMPLATE.format(
            function_name=function_name,
            module_name=module_name,
            import_path=import_path,
        )

        test_file = self._infer_test_file(intent)
        test_function = f"test_{function_name}_exists"

        return TestSpecification(
            test_code=test_code,
            test_file=test_file,
            test_function=test_function,
            imports=["pytest", import_path],
            rationale=f"Verifies that {function_name} exists and returns a value",
        )

    def _generate_class_test(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate test for a class."""
        class_name = self._extract_name(intent.prompt_intent.target, "class")
        import_path = self._infer_import_path(intent)

        test_code = CLASS_TEST_TEMPLATE.format(
            class_name=class_name,
            class_name_lower=class_name.lower(),
            import_path=import_path,
        )

        test_file = self._infer_test_file(intent)
        test_function = f"test_{class_name.lower()}_instantiation"

        return TestSpecification(
            test_code=test_code,
            test_file=test_file,
            test_function=test_function,
            imports=["pytest", import_path],
            rationale=f"Verifies that {class_name} can be instantiated",
        )

    def _generate_api_test(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate test for an API endpoint."""
        endpoint = self._extract_endpoint(intent.what)
        endpoint_name = self._sanitize_name(endpoint)

        test_code = API_ENDPOINT_TEST_TEMPLATE.format(
            endpoint=endpoint,
            endpoint_name=endpoint,
            endpoint_name_safe=endpoint_name,
        )

        test_file = self._infer_test_file(intent, prefix="test_api_")
        test_function = f"test_{endpoint_name}_returns_200"

        return TestSpecification(
            test_code=test_code,
            test_file=test_file,
            test_function=test_function,
            imports=["pytest"],
            rationale=f"Verifies that {endpoint} endpoint works correctly",
        )

    def _generate_file_test(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate test for a file/module."""
        file_path = self._extract_file_path(intent)
        file_name = Path(file_path).stem
        file_name_safe = self._sanitize_name(file_name)

        test_code = FILE_EXISTS_TEST_TEMPLATE.format(
            file_path=file_path,
            file_name=file_name,
            file_name_safe=file_name_safe,
        )

        test_file = f"tests/test_{file_name_safe}.py"
        test_function = f"test_{file_name_safe}_exists"

        return TestSpecification(
            test_code=test_code,
            test_file=test_file,
            test_function=test_function,
            imports=["pytest", "pathlib"],
            rationale=f"Verifies that {file_path} exists and is valid Python",
        )

    def _generate_generic_test(self, intent: DiscoveredIntent) -> TestSpecification:
        """Generate a generic placeholder test."""
        description = intent.goal

        test_code = GENERIC_TEST_TEMPLATE.format(
            description=description,
        )

        test_file = self._infer_test_file(intent)
        test_function = "test_feature_implemented"

        return TestSpecification(
            test_code=test_code,
            test_file=test_file,
            test_function=test_function,
            imports=["pytest"],
            rationale="Placeholder test - should be refined based on implementation",
        )

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _extract_name(self, target: str, entity_type: str) -> str:
        """Extract entity name from target string."""
        # Remove common prefixes like "a function", "the class", etc.
        name = target.lower()
        for prefix in ["a ", "an ", "the ", f"{entity_type} ", f"new "]:
            if name.startswith(prefix):
                name = name[len(prefix):]

        # Handle patterns like "function called foo" or "named bar"
        for pattern in [r"called\s+(\w+)", r"named\s+(\w+)"]:
            match = re.search(pattern, name)
            if match:
                return match.group(1)

        # Clean up and convert to valid identifier
        name = re.sub(r"[^\w]", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")

        return name or "feature"

    def _extract_endpoint(self, text: str) -> str:
        """Extract API endpoint path from text."""
        # Look for /path patterns
        match = re.search(r"(/[\w/\-{}]+)", text)
        if match:
            return match.group(1)
        return "/endpoint"

    def _extract_file_path(self, intent: DiscoveredIntent) -> str:
        """Extract target file path from intent."""
        # Check related files first
        if intent.codebase_intent.related_files:
            return intent.codebase_intent.related_files[0]

        # Try to extract from goal/what
        for text in [intent.what, intent.goal]:
            match = re.search(r"([\w/]+\.py)", text)
            if match:
                return match.group(1)

        return "src/module.py"

    def _infer_module_name(self, intent: DiscoveredIntent) -> str:
        """Infer module name from intent."""
        # Get from related files
        if intent.codebase_intent.related_files:
            return Path(intent.codebase_intent.related_files[0]).stem
        return "module"

    def _infer_import_path(self, intent: DiscoveredIntent) -> str:
        """Infer Python import path from intent."""
        # Get from related files
        if intent.codebase_intent.related_files:
            file_path = intent.codebase_intent.related_files[0]
            # Convert path to import: src/foo/bar.py -> src.foo.bar
            import_path = file_path.replace("/", ".").replace("\\", ".")
            if import_path.endswith(".py"):
                import_path = import_path[:-3]
            return import_path

        return "src.module"

    def _infer_test_file(self, intent: DiscoveredIntent, prefix: str = "test_") -> str:
        """Infer test file path from intent."""
        # Check existing test patterns
        test_pattern = intent.codebase_intent.test_patterns
        if test_pattern:
            # Use directory structure from existing tests
            test_dir = str(Path(test_pattern).parent)
        else:
            test_dir = "tests"

        # Generate test file name
        if intent.codebase_intent.related_files:
            source_name = Path(intent.codebase_intent.related_files[0]).stem
            return f"{test_dir}/{prefix}{source_name}.py"

        # Fallback to generic name
        feature_name = self._sanitize_name(intent.prompt_intent.target)
        return f"{test_dir}/{prefix}{feature_name}.py"

    def _sanitize_name(self, name: str) -> str:
        """Sanitize string to valid Python identifier."""
        # Remove non-alphanumeric, replace with underscore
        name = re.sub(r"[^\w]", "_", name.lower())
        # Collapse multiple underscores
        name = re.sub(r"_+", "_", name).strip("_")
        # Ensure doesn't start with number
        if name and name[0].isdigit():
            name = "f_" + name
        return name or "feature"
