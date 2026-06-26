"""Step definitions for client_prompts.feature tests."""

import re
import pytest
from pytest_bdd import given, when, then, parsers
from typing import Dict, Any


@pytest.fixture
def grep_params():
    """Fixture to store grep parameters for verification."""
    return {}


@pytest.fixture
def prompt_text():
    """Fixture to store the current prompt text."""
    return ""


@pytest.fixture
def prompt_parser():
    """Fixture that provides a function to parse prompts into grep parameters."""
    def _parse_prompt(prompt_text: str) -> Dict[str, Any]:
        """Parse a natural language prompt into grep parameters.
        
        This is a simplified mock implementation that would be replaced by the actual
        prompt parsing logic in a real implementation.
        """
        params = {}
        
        # Extract pattern - look for text in quotes
        pattern_match = re.search(r"['\"]([^'\"]+)['\"]", prompt_text)
        if pattern_match:
            params["pattern"] = pattern_match.group(1)
            
        # Extract paths - look for "in <path>" patterns
        path_match = re.search(r"in\s+([^\s]+)", prompt_text)
        if path_match:
            params["paths"] = path_match.group(1)
            
        # Check for case-insensitive option
        if "regardless of case" in prompt_text.lower() or "case-insensitiv" in prompt_text.lower():
            params["ignore_case"] = True
            
        # Check for context lines
        context_match = re.search(r"show\s+(\d+)\s+lines\s+(before|after|of context)", prompt_text)
        if context_match:
            context_num = int(context_match.group(1))
            context_type = context_match.group(2)
            
            if context_type == "before":
                params["before_context"] = context_num
            elif context_type == "after":
                params["after_context"] = context_num
            else:  # "of context"
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
            # In this case, pattern is already a regex pattern
            pass
            
        # Check for inverted match
        if "don't contain" in prompt_text or "that don't" in prompt_text:
            params["invert_match"] = True
            
        return params
        
    return _parse_prompt


@given("I need to search a specific file for a pattern")
def search_specific_file():
    """Setup for searching a specific file for a pattern."""
    # This is a setup step - no implementation needed
    pass


@given("I need to search without case sensitivity")
def search_case_insensitive():
    """Setup for case-insensitive search."""
    # This is a setup step - no implementation needed
    pass


@given("I need to see lines before and after matches")
def search_with_context():
    """Setup for searching with context lines."""
    # This is a setup step - no implementation needed
    pass


@given("I need to search across multiple files in a directory")
def search_multiple_files():
    """Setup for searching across multiple files."""
    # This is a setup step - no implementation needed
    pass


@given("I need to search for a string containing special characters")
def search_special_chars():
    """Setup for searching for special characters."""
    # This is a setup step - no implementation needed
    pass


@given("I only want to see the first few matches")
def search_limited_results():
    """Setup for limited results search."""
    # This is a setup step - no implementation needed
    pass


@given("I need to search using a regex pattern")
def search_with_regex():
    """Setup for regex pattern search."""
    # This is a setup step - no implementation needed
    pass


@given("I need to find lines that don't match a pattern")
def search_inverted_match():
    """Setup for inverted match search."""
    # This is a setup step - no implementation needed
    pass


@given("I need to search only specific file types")
def search_specific_file_types():
    """Setup for searching specific file types."""
    # This is a setup step - no implementation needed
    pass


@given("I need to use multiple search options together")
def search_multiple_options():
    """Setup for using multiple search options."""
    # This is a setup step - no implementation needed
    pass


@when(parsers.parse('I use the prompt "{prompt}"'))
def use_prompt(prompt, prompt_text, prompt_parser, grep_params):
    """Store the prompt text for later parsing."""
    # Parse the prompt text into grep parameters and store them
    parsed_params = prompt_parser(prompt)
    
    # Store the parsed parameters for verification
    grep_params.update(parsed_params)
    
    return prompt


@then("the MCP server should interpret this as a grep with:")
def verify_grep_interpretation():
    """Verify that the prompt is correctly interpreted."""
    # This is just a header step - verification happens in the next steps
    pass


@then(parsers.parse("| {parameter} | {value} |"))
def verify_parameter(parameter, value, grep_params):
    """Verify a specific grep parameter value."""
    # Convert string values to appropriate types
    if value.lower() == "true":
        expected_value = True
    elif value.lower() == "false":
        expected_value = False
    elif value.isdigit():
        expected_value = int(value)
    else:
        expected_value = value
        
    # Check if the parameter exists in the parsed parameters
    assert parameter in grep_params, f"Parameter '{parameter}' not found in parsed parameters"
    
    # Check if the parameter has the expected value
    assert grep_params[parameter] == expected_value, \
        f"Parameter '{parameter}' has value '{grep_params[parameter]}', expected '{expected_value}'"