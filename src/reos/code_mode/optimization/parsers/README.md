# Multi-Language AST Parsers

Tree-sitter-based parsers for accurate code analysis across multiple languages.

## Overview

This module provides language-agnostic code parsing using [tree-sitter](https://tree-sitter.github.io/tree-sitter/), replacing regex-based extraction with proper syntax understanding.

### Benefits

- **Accurate:** Handles edge cases that regex misses (nested functions, complex decorators, etc.)
- **Fast:** Incremental parsing - only reparses changed sections
- **Multi-language:** Same API across Python, JavaScript, Rust, Go, etc.
- **Structured queries:** Query language for finding patterns in AST
- **Graceful degradation:** Falls back to regex if tree-sitter unavailable

## Installation

```bash
# Install tree-sitter support (optional)
pip install -e ".[parsing]"
```

Tree-sitter is optional. If not installed, fast paths fall back to regex extraction.

## Usage

```python
from reos.code_mode.optimization.parsers import get_parser, is_tree_sitter_available

# Check availability
if is_tree_sitter_available():
    print("Tree-sitter is available!")

# Get a parser for a language
parser = get_parser("python")
if parser:
    # Find all functions
    functions = parser.find_functions(code)
    for func in functions:
        print(f"Found {func.name} at line {func.start_line}")
        print(f"  Parameters: {func.parameters}")
        print(f"  Is async: {func.is_async}")

    # Find imports
    imports = parser.find_imports(code)
    for imp in imports:
        print(f"Import {imp.module} at line {imp.start_line}")

    # Validate syntax
    is_valid, error = parser.validate_syntax(code)
    if not is_valid:
        print(f"Syntax error: {error}")

    # Find best location to insert import
    line_num = parser.get_import_location(code)
    print(f"Insert import at line {line_num}")
```

## Supported Languages

| Language | Parser Module | Status | Grammar Package |
|----------|--------------|--------|-----------------|
| Python | `python_parser.py` | ✅ Full | `tree-sitter-python` |
| JavaScript | `javascript_parser.py` | ✅ Full | `tree-sitter-javascript` |
| TypeScript | `javascript_parser.py` | ✅ Full | `tree-sitter-javascript` |
| Rust | — | 📋 Planned | `tree-sitter-rust` |
| Go | — | 📋 Planned | `tree-sitter-go` |

## Architecture

### Base Classes

**`CodeParser` (Abstract)**
- Defines the interface all language parsers implement
- Methods: `find_functions()`, `find_classes()`, `find_imports()`, `validate_syntax()`

**`CodeNode` (Data)**
- Represents any AST node with position info and text
- Specialized subclasses: `FunctionNode`, `ClassNode`, `ImportNode`

### Language Parsers

Each language parser:
1. Wraps the tree-sitter grammar for that language
2. Provides tree-sitter queries for common patterns
3. Converts tree-sitter nodes to our `CodeNode` types
4. Handles language-specific edge cases

### Integration with Fast Paths

Fast path handlers use parsers automatically:

```python
# In fast_path.py

def _extract_function_name(what: str, code: str | None = None, file_path: str | None = None):
    """Extract function name - uses tree-sitter if available."""
    if code and file_path:
        parser = get_parser(_infer_language_from_path(file_path))
        if parser:
            # Use AST parsing
            functions = parser.find_functions(code)
            for func in functions:
                if func.name in what:
                    return func.name

    # Fall back to regex
    match = re.search(r"function\s+(\w+)", what)
    return match.group(1) if match else None
```

## Performance

Tree-sitter is designed for speed:

- **Incremental parsing:** Only reparses changed sections
- **Error recovery:** Continues parsing despite syntax errors
- **Small overhead:** ~1ms to parse typical Python file

Benchmarks (on typical 200-line Python file):
- Tree-sitter parse: ~1.2ms
- AST parse (`ast.parse`): ~0.8ms
- Regex extraction: ~0.3ms per pattern

The overhead is worth it for:
- Accuracy (no regex edge cases)
- Multi-language support
- Structured queries (find all functions calling X)

## Extending

### Adding a New Language

1. **Install grammar:** `pip install tree-sitter-{language}`

2. **Create parser:** `src/reos/code_mode/optimization/parsers/{language}_parser.py`

```python
from reos.code_mode.optimization.parsers.base import CodeParser
import tree_sitter_{language} as ts_lang
from tree_sitter import Language, Parser

LANGUAGE = Language(ts_lang.language())

class MyLanguageParser(CodeParser):
    def __init__(self):
        self.parser = Parser(LANGUAGE)

    # Implement required methods...
```

3. **Register in `__init__.py`:**

```python
def get_parser(language: str):
    if language_lower == "mylang":
        from .mylang_parser import MyLangParser
        return MyLangParser()
```

4. **Add to supported list** in this README

## Testing

```bash
# Unit tests for parsers
pytest tests/test_parsers.py -v

# Integration tests with fast paths
pytest tests/test_fast_path_parsers.py -v
```

## References

- [Tree-sitter Documentation](https://tree-sitter.github.io/tree-sitter/)
- [Available Grammars](https://github.com/tree-sitter)
- [Query Syntax](https://tree-sitter.github.io/tree-sitter/using-parsers#pattern-matching-with-queries)
- [Python Bindings](https://github.com/tree-sitter/py-tree-sitter)

## License

Tree-sitter is MIT licensed. All grammar packages have permissive licenses (MIT/Apache 2.0).
