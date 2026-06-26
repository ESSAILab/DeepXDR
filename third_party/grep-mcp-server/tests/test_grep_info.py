"""
Test file for grep_info feature using pytest-bdd.
"""
import os
import pytest
from pytest_bdd import scenario, given, when, then

# Get the absolute path to the feature file
FEATURE_FILE = os.path.join(os.path.dirname(__file__), 'features', 'grep_info.feature')

# Import all step definitions from the step_defs directory
from tests.step_defs.test_grep_info_steps import *

# Run all scenarios from the feature file
@scenario(FEATURE_FILE, 'Retrieving grep binary information')
def test_retrieving_grep_binary_information():
    """Test retrieving grep binary information."""
    pass