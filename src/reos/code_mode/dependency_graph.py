"""Dependency graph builder for Python source files.

Analyzes import statements to build a graph of file dependencies.
Used by RepoMap to track which files depend on which.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportInfo:
    """Information about a single import statement."""

    module: str  # The module being imported
    symbols: list[str] = field(default_factory=list)  # Specific symbols imported
    import_type: str = "import"  # "import" or "from_import"
    level: int = 0  # For relative imports (0 = absolute, 1 = ., 2 = .., etc.)


class DependencyGraphBuilder:
    """Build dependency graph from import analysis.

    Resolves import statements to file paths within the repository,
    tracking which files depend on which other files.
    """

    def __init__(self, repo_path: Path):
        """Initialize with repository root path.

        Args:
            repo_path: Absolute path to the repository root
        """
        self.repo_path = repo_path.resolve()
        self._file_cache: dict[str, Path | None] = {}

    def analyze_imports(self, content: str) -> list[ImportInfo]:
        """Extract all import statements from Python source.

        Args:
            content: Python source code

        Returns:
            List of ImportInfo objects describing each import
        """
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        imports: list[ImportInfo] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportInfo(
                            module=alias.name,
                            symbols=[alias.asname or alias.name.split(".")[-1]],
                            import_type="import",
                            level=0,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                symbols = [
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name != "*"
                ]
                # Handle star imports
                if any(alias.name == "*" for alias in node.names):
                    symbols.append("*")

                imports.append(
                    ImportInfo(
                        module=module,
                        symbols=symbols,
                        import_type="from_import",
                        level=node.level,  # For relative imports
                    )
                )

        return imports

    def resolve_import(
        self,
        import_info: ImportInfo,
        from_file: str,
    ) -> str | None:
        """Resolve an import to a file path within the repository.

        Args:
            import_info: Import information
            from_file: Path of the file containing the import (relative to repo)

        Returns:
            Relative file path if the import resolves to a repo file, else None
        """
        if import_info.level > 0:
            # Relative import
            return self._resolve_relative_import(import_info, from_file)
        else:
            # Absolute import
            return self._resolve_absolute_import(import_info.module)

    def _resolve_relative_import(
        self,
        import_info: ImportInfo,
        from_file: str,
    ) -> str | None:
        """Resolve a relative import (from . import x, from .. import y).

        Args:
            import_info: Import with level > 0
            from_file: Importing file path

        Returns:
            Resolved file path or None
        """
        from_path = Path(from_file)

        # Start from the directory containing the importing file
        current = from_path.parent

        # Go up directories based on level
        for _ in range(import_info.level - 1):
            current = current.parent

        # Add the module path
        if import_info.module:
            module_parts = import_info.module.split(".")
            current = current / "/".join(module_parts)

        # Try to resolve to a file
        return self._find_module_file(str(current))

    def _resolve_absolute_import(self, module: str) -> str | None:
        """Resolve an absolute import to a repo file.

        Args:
            module: Module name (e.g., "reos.code_mode.sandbox")

        Returns:
            Relative file path or None
        """
        if not module:
            return None

        return self._find_module_file(module.replace(".", "/"))

    def _find_module_file(self, module_path: str) -> str | None:
        """Find the actual file for a module path.

        Checks for:
        - module_path.py (direct file)
        - module_path/__init__.py (package)

        Args:
            module_path: Path-like module representation (e.g., "src/reos/agent")

        Returns:
            Relative file path or None
        """
        # Check cache
        if module_path in self._file_cache:
            cached = self._file_cache[module_path]
            return str(cached) if cached else None

        # Common source directories to check
        search_paths = [
            "",  # repo root
            "src",  # src layout
        ]

        for prefix in search_paths:
            if prefix:
                base = self.repo_path / prefix / module_path
            else:
                base = self.repo_path / module_path

            # Check for direct .py file
            py_file = base.with_suffix(".py")
            if py_file.exists():
                result = py_file.relative_to(self.repo_path)
                self._file_cache[module_path] = result
                return str(result)

            # Check for package __init__.py
            init_file = base / "__init__.py"
            if init_file.exists():
                result = init_file.relative_to(self.repo_path)
                self._file_cache[module_path] = result
                return str(result)

        # Not found in repo
        self._file_cache[module_path] = None
        return None

    def get_dependencies(
        self,
        file_path: str,
        content: str,
    ) -> list[tuple[str, list[str]]]:
        """Get all dependencies for a file.

        Args:
            file_path: Relative path of the file
            content: File content

        Returns:
            List of (target_file, imported_symbols) tuples
        """
        imports = self.analyze_imports(content)
        dependencies: list[tuple[str, list[str]]] = []

        for import_info in imports:
            resolved = self.resolve_import(import_info, file_path)
            if resolved:
                dependencies.append((resolved, import_info.symbols))

        return dependencies

    def get_dependents(
        self,
        file_path: str,
        file_contents: dict[str, str],
    ) -> list[str]:
        """Find all files that depend on a given file.

        Args:
            file_path: The file to check dependents for
            file_contents: Dict of file_path -> content for all repo files

        Returns:
            List of file paths that import the target file
        """
        dependents: list[str] = []

        for other_path, content in file_contents.items():
            if other_path == file_path:
                continue

            deps = self.get_dependencies(other_path, content)
            for target, _ in deps:
                if target == file_path:
                    dependents.append(other_path)
                    break

        return dependents

    def clear_cache(self) -> None:
        """Clear the file resolution cache."""
        self._file_cache.clear()
