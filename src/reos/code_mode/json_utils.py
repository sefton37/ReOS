"""JSON parsing utilities for LLM responses.

LLMs often wrap JSON in markdown code blocks like ```json ... ```.
These utilities safely extract and parse JSON from such responses.
"""

from __future__ import annotations

import json
import re
from typing import Any


def strip_markdown_code_block(content: str) -> str:
    """Strip markdown code block formatting from content.

    LLMs often wrap code/JSON in ```language ... ``` blocks.
    This extracts the inner content.

    Examples:
        >>> strip_markdown_code_block('```json\\n{"a": 1}\\n```')
        '{"a": 1}'
        >>> strip_markdown_code_block('{"a": 1}')
        '{"a": 1}'
    """
    content = content.strip()

    # Match ```language\n...\n``` or ```\n...\n```
    match = re.match(r'^```(?:\w+)?\s*\n(.*)\n```$', content, re.DOTALL)
    if match:
        return match.group(1)

    # Match just ```...``` (no newlines)
    match = re.match(r'^```(?:\w+)?\s*(.*?)\s*```$', content, re.DOTALL)
    if match:
        return match.group(1)

    return content


def fix_json_escapes(text: str) -> str:
    """Fix common escape sequence issues in LLM-generated JSON.

    LLMs sometimes generate invalid escape sequences like:
    - \\' (should be just ')
    - \n inside strings without proper escaping
    - Invalid unicode escapes

    This function attempts to fix these issues.
    """
    # Fix invalid escape sequences by escaping the backslash
    # This handles cases like \' which should be just ' or \a which is invalid
    # We need to be careful not to break valid escapes like \n, \t, \\, \", etc.
    valid_escapes = {'n', 't', 'r', 'b', 'f', '\\', '"', '/', 'u'}

    result = []
    i = 0
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            next_char = text[i + 1]
            if next_char in valid_escapes:
                # Valid escape sequence - keep both chars
                result.append(text[i:i + 2])
                i += 2
            elif next_char == "'":
                # \' is not valid in JSON - just use '
                result.append("'")
                i += 2
            elif next_char.isalpha():
                # Invalid escape like \a - escape the backslash
                result.append("\\\\")
                result.append(next_char)
                i += 2
            else:
                # Other cases - keep as is
                result.append(text[i])
                i += 1
        else:
            result.append(text[i])
            i += 1

    return ''.join(result)


def parse_llm_json(response: str) -> Any:
    """Parse JSON from an LLM response, handling markdown code blocks.

    This function:
    1. Strips markdown code block wrappers if present
    2. Fixes common escape sequence issues
    3. Parses the JSON content

    Args:
        response: Raw LLM response string (may be wrapped in ```json...```)

    Returns:
        Parsed JSON data

    Raises:
        json.JSONDecodeError: If the response is not valid JSON after cleanup
    """
    if not response or not response.strip():
        raise json.JSONDecodeError("Empty response", response, 0)

    clean = strip_markdown_code_block(response)

    # Try parsing as-is first
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Try fixing escape sequences
    fixed = fix_json_escapes(clean)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Last attempt: try to extract just the JSON object/array
    # Sometimes LLMs add commentary before/after
    json_match = re.search(r'(\{.*\}|\[.*\])', clean, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            # Try with escape fixes
            try:
                return json.loads(fix_json_escapes(json_match.group(1)))
            except json.JSONDecodeError:
                pass

    # Give up - raise with original error
    return json.loads(clean)
