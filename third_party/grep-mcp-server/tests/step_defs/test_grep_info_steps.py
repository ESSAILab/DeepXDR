"""Step definitions for grep_info.feature tests."""

import pytest
import json
import subprocess
import shutil
from pytest_bdd import given, when, then
from mcp_grep.server import get_grep_info


@pytest.fixture
def mcp_connection():
    """Mock fixture for MCP connection."""
    # In real implementation, this would connect to the MCP server
    return {"connected": True}


@pytest.fixture
def grep_info_response():
    """Fixture to store grep info response."""
    # Use the actual implementation to get grep info
    return get_grep_info()


@given("I'm connected to the MCP grep server")
def connected_to_server(mcp_connection):
    """Verify connection to MCP grep server."""
    assert mcp_connection["connected"] is True


@when('I request the "grep://info" resource')
def request_grep_info(grep_info_response):
    """Request the grep info resource."""
    # This step relies on the fixture which already calls get_grep_info()
    return grep_info_response


@then("I should receive grep binary metadata as JSON")
def verify_grep_metadata_json(grep_info_response):
    """Verify that the response contains grep metadata in JSON format."""
    # Check that we can parse the response as JSON
    assert isinstance(grep_info_response, dict), "Response is not a dictionary"
    
    # Check the structure of the response
    assert "path" in grep_info_response, "Response missing 'path' field"
    assert "version" in grep_info_response, "Response missing 'version' field"
    assert "supports_pcre" in grep_info_response, "Response missing 'supports_pcre' field"
    assert "supports_color" in grep_info_response, "Response missing 'supports_color' field"


@then("the metadata should include the binary path")
def verify_grep_binary_path(grep_info_response):
    """Verify that the metadata includes the grep binary path."""
    assert "path" in grep_info_response, "Response missing 'path' field"
    assert grep_info_response["path"] is not None, "grep binary path is None"
    
    # Verify the path exists (using shutil.which to handle both absolute paths and PATH searches)
    grep_path = grep_info_response["path"]
    assert shutil.which(grep_path) is not None, f"grep binary not found at {grep_path}"


@then("the metadata should include version information")
def verify_grep_version(grep_info_response):
    """Verify that the metadata includes the grep version."""
    assert "version" in grep_info_response, "Response missing 'version' field"
    assert grep_info_response["version"] is not None, "grep version is None"
    
    # Check that the version follows the expected format
    assert "grep" in grep_info_response["version"].lower(), "Version string doesn't contain 'grep'"


@then("the metadata should include PCRE support status")
def verify_pcre_support(grep_info_response):
    """Verify that the metadata includes PCRE support status."""
    assert "supports_pcre" in grep_info_response, "Response missing 'supports_pcre' field"
    assert isinstance(grep_info_response["supports_pcre"], bool), "supports_pcre is not a boolean"
    
    # Optional: Verify PCRE support directly
    grep_path = grep_info_response["path"]
    if grep_path and shutil.which(grep_path):
        try:
            # Use subprocess.run instead of check_output for better error handling
            completed_proc = subprocess.run(
                [grep_path, "--perl-regexp", "test", "-"], 
                input="test".encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            # If return code is 0 (success) or 1 (no matches but valid syntax), PCRE is supported
            actual_pcre_support = completed_proc.returncode in [0, 1]
        except (subprocess.SubprocessError, FileNotFoundError):
            actual_pcre_support = False
            
        assert grep_info_response["supports_pcre"] == actual_pcre_support, \
            f"PCRE support mismatch: reported {grep_info_response['supports_pcre']}, actual {actual_pcre_support}"


@then("the metadata should include color support status")
def verify_color_support(grep_info_response):
    """Verify that the metadata includes color support status."""
    assert "supports_color" in grep_info_response, "Response missing 'supports_color' field"
    assert isinstance(grep_info_response["supports_color"], bool), "supports_color is not a boolean"
    
    # Optional: Verify color support directly
    grep_path = grep_info_response["path"]
    if grep_path and shutil.which(grep_path):
        try:
            # Use subprocess.run instead of check_output for better error handling
            completed_proc = subprocess.run(
                [grep_path, "--color=auto", "test", "-"], 
                input="test".encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            # If return code is 0 (success) or 1 (no matches but valid syntax), color is supported
            actual_color_support = completed_proc.returncode in [0, 1]
        except (subprocess.SubprocessError, FileNotFoundError):
            actual_color_support = False
            
        assert grep_info_response["supports_color"] == actual_color_support, \
            f"Color support mismatch: reported {grep_info_response['supports_color']}, actual {actual_color_support}"