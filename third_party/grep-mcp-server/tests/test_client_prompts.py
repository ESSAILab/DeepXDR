"""
Test file for client_prompts feature using pytest-bdd.
"""
import os
import pytest
from pytest_bdd import scenario, given, when, then

# Get the absolute path to the feature file
FEATURE_FILE = os.path.join(os.path.dirname(__file__), 'features', 'client_prompts.feature')

# Import all step definitions from the step_defs directory
from tests.step_defs.test_client_prompts_steps import *

# Run all scenarios from the feature file
@scenario(FEATURE_FILE, 'Basic file search prompt')
def test_basic_file_search_prompt():
    """Test basic file search prompt."""
    pass

@scenario(FEATURE_FILE, 'Case-insensitive search prompt')
def test_case_insensitive_search_prompt():
    """Test case-insensitive search prompt."""
    pass

@scenario(FEATURE_FILE, 'Search with context lines prompt')
def test_search_with_context_lines_prompt():
    """Test search with context lines prompt."""
    pass

@scenario(FEATURE_FILE, 'Recursive directory search prompt')
def test_recursive_directory_search_prompt():
    """Test recursive directory search prompt."""
    pass

@scenario(FEATURE_FILE, 'Fixed string search prompt')
def test_fixed_string_search_prompt():
    """Test fixed string search prompt."""
    pass

@scenario(FEATURE_FILE, 'Limited results prompt')
def test_limited_results_prompt():
    """Test limited results prompt."""
    pass

@scenario(FEATURE_FILE, 'Regular expression search prompt')
def test_regular_expression_search_prompt():
    """Test regular expression search prompt."""
    pass

@scenario(FEATURE_FILE, 'Inverted match prompt')
def test_inverted_match_prompt():
    """Test inverted match prompt."""
    pass

@scenario(FEATURE_FILE, 'Multiple file type search prompt')
def test_multiple_file_type_search_prompt():
    """Test multiple file type search prompt."""
    pass

@scenario(FEATURE_FILE, 'Combined options prompt')
def test_combined_options_prompt():
    """Test combined options prompt."""
    pass