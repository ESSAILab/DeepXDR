"""
Test file for grep_tool feature using pytest-bdd.
"""
import os
import pytest
from pytest_bdd import scenario, given, when, then

# Get the absolute path to the feature file
FEATURE_FILE = os.path.join(os.path.dirname(__file__), 'features', 'grep_tool.feature')

# Import all step definitions from the step_defs directory
from tests.step_defs.test_grep_tool_steps import *

# Run all scenarios from the feature file
@scenario(FEATURE_FILE, 'Finding matches in a file')
def test_finding_matches_in_a_file():
    """Test finding matches in a file."""
    pass

@scenario(FEATURE_FILE, 'Case-insensitive search')
def test_case_insensitive_search():
    """Test case-insensitive search."""
    pass

@scenario(FEATURE_FILE, 'Search with context')
def test_search_with_context():
    """Test search with context."""
    pass

@scenario(FEATURE_FILE, 'Fixed string search')
def test_fixed_string_search():
    """Test fixed string search."""
    pass

@scenario(FEATURE_FILE, 'Recursive directory search')
def test_recursive_directory_search():
    """Test recursive directory search."""
    pass

@scenario(FEATURE_FILE, 'Limiting result count')
def test_limiting_result_count():
    """Test limiting result count."""
    pass

@scenario(FEATURE_FILE, 'Regular expression search')
def test_regular_expression_search():
    """Test regular expression search."""
    pass

@scenario(FEATURE_FILE, 'Inverted match search')
def test_inverted_match_search():
    """Test inverted match search."""
    pass

@scenario(FEATURE_FILE, 'Controlling line number display')
def test_controlling_line_number_display():
    """Test controlling line number display."""
    pass

@scenario(FEATURE_FILE, 'Multiple file pattern support')
def test_multiple_file_pattern_support():
    """Test multiple file pattern support."""
    pass

@scenario(FEATURE_FILE, 'Variable context line control')
def test_variable_context_line_control():
    """Test variable context line control."""
    pass