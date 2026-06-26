"""
Configuration for pytest.
"""
from pathlib import Path

def pytest_bdd_apply_tag(tag, function):
    """Apply tag to test function."""
    return None

def pytest_configure(config):
    """Configure pytest-bdd."""
    # Register fixtures used across multiple steps 
    config.addinivalue_line("markers", "grep: mark test as a grep test")

"""Common fixtures for all step definitions."""

import os
import pytest
import tempfile
import shutil
from pathlib import Path
from pytest_bdd import given, when, then, parsers
from mcp_grep.core import MCPGrep


# Re-export steps from the step definition files
from tests.step_defs.test_grep_tool_steps import *
from tests.step_defs.test_grep_info_steps import *
from tests.step_defs.test_client_prompts_steps import *


@pytest.fixture
def grep_params():
    """Fixture to store grep parameters for verification."""
    return {}


@pytest.fixture
def prompt_text():
    """Fixture to store the current prompt text."""
    return ""


@pytest.fixture
def test_dir():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Clean up after tests
    shutil.rmtree(temp_dir)


@pytest.fixture
def test_file_path(test_dir):
    """Create a temporary test file path."""
    return os.path.join(test_dir, "test_file.txt")


@pytest.fixture
def test_file_content():
    """Store test file content."""
    return ""


@pytest.fixture
def grep_results():
    """Store grep search results."""
    return {"results": [], "match_count": 0}


@pytest.fixture
def mcp_grep_instance():
    """Create an instance of MCPGrep for testing."""
    return MCPGrep("test_pattern")  # Default instance for testing


@pytest.fixture
def mcp_connection():
    """Mock fixture for MCP connection."""
    # In a real implementation, this would connect to the MCP server
    return {"connected": True}


@pytest.fixture
def prompt_parser():
    """Fixture that provides a function to parse prompts into grep parameters."""
    def _parse_prompt(prompt_text: str):
        """Parse a natural language prompt into grep parameters."""
        import re
        params = {}
        
        # Extract pattern - look for text in quotes
        pattern_match = re.search(r"['\"]([^'\"]+)['\"]", prompt_text)
        if pattern_match:
            params["pattern"] = pattern_match.group(1)
            
        # Extract paths - look for "in <path>" patterns
        path_match = re.search(r"in\s+([^\s,\.]+)", prompt_text)
        if path_match:
            params["paths"] = path_match.group(1)
            
        # Check for case-insensitive option
        if "regardless of case" in prompt_text.lower() or "case-insensitiv" in prompt_text.lower():
            params["ignore_case"] = True
            
        # Check for context lines
        context_match = re.search(r"show\s+(\d+)\s+lines\s+(before|after|of context|context)", prompt_text)
        if context_match:
            context_num = int(context_match.group(1))
            context_type = context_match.group(2)
            
            if context_type == "before":
                params["before_context"] = context_num
            elif context_type == "after":
                params["after_context"] = context_num
            else:  # "of context" or "context"
                params["before_context"] = context_num
                params["after_context"] = context_num
                
        # Check for recursive search
        if "subdirectories" in prompt_text or "recursive" in prompt_text:
            params["recursive"] = True
            
        # Check for fixed strings
        if "exact string" in prompt_text:
            params["fixed_strings"] = True
            
        # Check for max count
        count_match = re.search(r"first\s+(\d+)", prompt_text) or re.search(r"limit\s+to\s+(\d+)", prompt_text)
        if count_match:
            params["max_count"] = int(count_match.group(1))
            
        # Check for regex
        if "regex" in prompt_text or "regular expression" in prompt_text:
            # Pattern is already a regex pattern
            pass
            
        # Check for inverted match
        if "don't contain" in prompt_text or "that don't" in prompt_text:
            params["invert_match"] = True
            
        # Check for file patterns
        if "all JavaScript and TypeScript files" in prompt_text:
            params["paths"] = "*.js *.ts"
            
        return params
        
    return _parse_prompt