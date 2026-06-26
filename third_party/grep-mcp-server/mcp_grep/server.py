"""MCP Server implementation for grep functionality using system grep binary."""

from pathlib import Path
import json
import subprocess
import shutil
import os
import fnmatch
from typing import Dict, List, Optional, Union, Any

from mcp.server.fastmcp import FastMCP
from mcp_grep.core import MCPGrep

# Create an MCP server
mcp = FastMCP("grep-server")

def get_grep_info() -> Dict[str, Optional[str]]:
    """Get information about the system grep binary."""
    info = {
        "path": None,
        "version": None,
        "supports_pcre": False,
        "supports_color": False
    }
    
    # Find grep path
    grep_path = shutil.which("grep")
    if grep_path:
        info["path"] = grep_path
        
        # Get version
        try:
            version_output = subprocess.check_output([grep_path, "--version"], text=True)
            info["version"] = version_output.split("\n")[0].strip()
            
            # Check for PCRE support
            try:
                subprocess.check_output([grep_path, "--perl-regexp", "test", "-"], 
                                      input="test", text=True, stderr=subprocess.DEVNULL)
                info["supports_pcre"] = True
            except subprocess.CalledProcessError:
                pass
                
            # Check for color support
            try:
                subprocess.check_output([grep_path, "--color=auto", "test", "-"], 
                                      input="test", text=True)
                info["supports_color"] = True
            except subprocess.CalledProcessError:
                pass
        except subprocess.CalledProcessError:
            pass
    
    return info

# Register grep info as a resource
@mcp.resource("grep://info")
def grep_info() -> str:
    """Resource providing information about the grep binary."""
    return json.dumps(get_grep_info(), indent=2)

def _format_results(results: List[Dict[str, Any]], count: int) -> Dict:
    """Format grep results for the MCP response."""
    # Truncate results if there are too many matches to avoid response size issues
    env_value = os.environ.get("MCP_GREP_MAX_RESULTS", "50")
    print(f"[DEBUG] Raw environment variable MCP_GREP_MAX_RESULTS={env_value}")
    max_results = int(env_value)
    if len(results) > max_results:
        truncated_results = results[:max_results]
        truncated_message = f"Found {count} matches, showing first {max_results}."
        results_json = json.dumps(truncated_results, indent=2)
        return {
            "content": [
                {
                    "type": "text",
                    "text": truncated_message + "\n\n" + results_json
                }
            ],
            "isError": False
        }
    else:
        results_json = json.dumps(results, indent=2)
        return {
            "content": [
                {
                    "type": "text",
                    "text": results_json
                }
            ],
            "isError": False
        }

@mcp.tool()
def grep(
    pattern: str,
    paths: Union[str, List[str]],
    ignore_case: bool = False,
    before_context: int = 0,
    after_context: int = 0,
    context: Optional[int] = None,
    max_count: int = 0,
    fixed_strings: bool = False,
    recursive: bool = False,
    regexp: bool = True,
    invert_match: bool = False,
    line_number: bool = True,
    file_pattern: Optional[str] = None
) -> Dict:
    """Search for pattern in files using system grep.
    
    Args:
        pattern: Pattern to search for
        paths: File or directory paths to search in (string or list of strings)
        ignore_case: Case-insensitive matching (-i)
        before_context: Number of lines before match (-B)
        after_context: Number of lines after match (-A)
        context: Number of context lines around match (equal before/after)
        max_count: Stop after N matches (-m)
        fixed_strings: Treat pattern as literal text, not regex (-F)
        recursive: Search directories recursively (-r)
        regexp: Use regular expressions for pattern matching
        invert_match: Select non-matching lines (-v)
        line_number: Show line numbers (-n)
        file_pattern: Pattern to filter files (e.g., "*.txt")
        
    Returns:
        JSON string with search results
    """
    try:
        # Convert single path to list and expand user paths
        if isinstance(paths, str):
            paths = [os.path.expanduser(paths)]
        else:
            paths = [os.path.expanduser(p) for p in paths]
        
        # Use our MCPGrep implementation for more consistent and flexible searching
        grep_tool = MCPGrep(
            pattern=pattern,
            ignore_case=ignore_case,
            fixed_strings=fixed_strings,
            regexp=regexp,
            invert_match=invert_match,
            line_number=line_number,
            before_context=before_context,
            after_context=after_context,
            context=context,
            max_count=max_count
        )
        
        # Search for matches
        results = []
        match_count = 0
        
        # If any path contains a wildcard, handle it at the paths level
        wildcarded_paths = []
        standard_paths = []
        
        for path in paths:
            if "*" in path or "?" in path:
                wildcarded_paths.append(path)
            else:
                standard_paths.append(path)
        
        # Process standard paths
        if standard_paths:
            try:
                for result in grep_tool.search_files(standard_paths, recursive, file_pattern):
                    results.append(result)
                    match_count += 1
                    if max_count > 0 and match_count >= max_count:
                        break
            except Exception as e:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error searching files: {str(e)}"
                        }
                    ],
                    "isError": True
                }
        
        # Process wildcard paths
        if wildcarded_paths and match_count < (max_count if max_count > 0 else float('inf')):
            # For each wildcarded path
            for wild_path in wildcarded_paths:
                # Split into directory and pattern
                dir_path = os.path.dirname(wild_path) or "."
                base_pattern = os.path.basename(wild_path)
                
                # Find all matching files in the directory
                try:
                    dir_obj = Path(dir_path)
                    if dir_obj.exists() and dir_obj.is_dir():
                        matching_files = []
                        
                        # Gather files recursively if needed
                        if recursive:
                            for root, _, files in os.walk(dir_path):
                                for file in files:
                                    if fnmatch.fnmatch(file, base_pattern):
                                        # Also check file_pattern if specified
                                        if file_pattern and not fnmatch.fnmatch(file, file_pattern):
                                            continue
                                        matching_files.append(os.path.join(root, file))
                        else:
                            # Non-recursive search
                            for item in dir_obj.iterdir():
                                if item.is_file() and fnmatch.fnmatch(item.name, base_pattern):
                                    # Also check file_pattern if specified
                                    if file_pattern and not fnmatch.fnmatch(item.name, file_pattern):
                                        continue
                                    matching_files.append(str(item))
                        
                        # Search in the matching files
                        for file_path in matching_files:
                            try:
                                for result in grep_tool.search_file(file_path):
                                    results.append(result)
                                    match_count += 1
                                    if max_count > 0 and match_count >= max_count:
                                        break
                                
                                if max_count > 0 and match_count >= max_count:
                                    break
                            except Exception as e:
                                print(f"Error searching {file_path}: {e}")
                        
                        if max_count > 0 and match_count >= max_count:
                            break
                    else:
                        print(f"Directory not found: {dir_path}")
                except Exception as e:
                    print(f"Error processing wildcard path {wild_path}: {e}")
        
        # No results case
        if not results:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "No matches found"
                    }
                ],
                "isError": False
            }
        
        # Return the formatted results
        return _format_results(results, match_count)
        
    except Exception as e:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error executing grep: {str(e)}"
                }
            ],
            "isError": True
        }

def parse_grep_query(query: str) -> Dict:
    """Parse a natural language query for grep operations.
    
    Args:
        query: Natural language query for grep operations
        
    Returns:
        Dictionary with extracted parameters for the grep tool
    """
    # Default values
    params = {
        "pattern": "",
        "paths": ["."],  # Default to current directory
        "ignore_case": False,
        "before_context": 0,
        "after_context": 0,
        "context": None,
        "max_count": 0,
        "fixed_strings": False,
        "recursive": False,
        "regexp": True,
        "invert_match": False,
        "line_number": True,
        "file_pattern": None
    }
    
    # Extract pattern from quotation marks if present
    import re
    pattern_match = re.search(r"['\"](.*?)['\"]", query)
    if pattern_match:
        params["pattern"] = pattern_match.group(1)
    
    # Detect case insensitivity
    if re.search(r"case\s*insensitive|ignor.*case|regardless\s*of\s*case", query, re.IGNORECASE):
        params["ignore_case"] = True
    
    # Detect context lines
    context_match = re.search(r"(\d+)\s*lines\s*(before|after|of\s*context|context)", query)
    if context_match:
        context_num = int(context_match.group(1))
        context_type = context_match.group(2).lower()
        
        if "before" in context_type:
            params["before_context"] = context_num
        elif "after" in context_type:
            params["after_context"] = context_num
        else:  # General context
            params["context"] = context_num
    
    # Detect both before and after context
    both_context_match = re.search(r"(\d+)\s*lines\s*before\s*and\s*(\d+)\s*lines\s*after", query)
    if both_context_match:
        params["before_context"] = int(both_context_match.group(1))
        params["after_context"] = int(both_context_match.group(2))
    
    # Look for equal context on both sides
    equal_context_match = re.search(r"show\s*(\d+)\s*lines\s*before\s*and\s*after", query)
    if equal_context_match:
        params["context"] = int(equal_context_match.group(1))
    
    # Detect recursive search
    if re.search(r"recursiv|subdirector|all\s*files|and\s*its\s*subdirectories", query, re.IGNORECASE):
        params["recursive"] = True
    
    # Detect fixed string (exact match)
    if re.search(r"exact\s*string|exact\s*text|literal|fixed\s*string", query, re.IGNORECASE):
        params["fixed_strings"] = True
    
    # Detect max count
    max_count_match = re.search(r"(first|only|just|limit\s*to)\s*(\d+)", query, re.IGNORECASE)
    if max_count_match:
        params["max_count"] = int(max_count_match.group(2))
    
    # Detect regex flag
    if re.search(r"regex|regular\s*expression", query, re.IGNORECASE):
        params["regexp"] = True
    
    # Detect invert match
    if re.search(r"don't\s*contain|doesn't\s*contain|not\s*contain|invert\s*match|lines\s*that\s*don't", query, re.IGNORECASE):
        params["invert_match"] = True
    
    # Detect line number display
    if re.search(r"without\s*line\s*numbers|no\s*line\s*numbers", query, re.IGNORECASE):
        params["line_number"] = False
    
    # Detect file pattern
    file_pattern_match = re.search(r"in\s*all\s*([*\.a-zA-Z0-9]+)\s*files", query, re.IGNORECASE)
    if file_pattern_match:
        params["file_pattern"] = file_pattern_match.group(1)
        if not params["file_pattern"].startswith("*"):
            params["file_pattern"] = f"*.{params['file_pattern']}"
    
    # Multiple file extensions
    multi_ext_match = re.search(r"in\s*all\s*([a-zA-Z0-9]+)\s*and\s*([a-zA-Z0-9]+)\s*files", query, re.IGNORECASE)
    if multi_ext_match:
        ext1 = multi_ext_match.group(1)
        ext2 = multi_ext_match.group(2)
        # Create a pattern for multiple extensions
        params["paths"] = [f"*.{ext1}", f"*.{ext2}"]
        params["recursive"] = True
    
    # Extract the file path(s)
    file_match = re.search(r"in\s*([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]+)", query)
    if file_match:
        params["paths"] = [file_match.group(1)]
    
    # Extract directory
    dir_match = re.search(r"in\s*the\s*([a-zA-Z0-9_\-./\\]+)\s*directory", query)
    if dir_match:
        params["paths"] = [dir_match.group(1)]
        # If searching in a directory and recursive not explicitly specified, default to recursive
        if not re.search(r"recursiv|subdirector", query, re.IGNORECASE):
            params["recursive"] = True
    
    # If no pattern found in quotes, try to extract it from the query
    if not params["pattern"]:
        # Look for common patterns like "find X in Y" or "search for X in Y"
        find_pattern = re.search(r"(?:find|search\s*for|looking\s*for)\s*['\"]*([^'\"]+?)['\"]*\s*(?:in|across)", query, re.IGNORECASE)
        if find_pattern:
            params["pattern"] = find_pattern.group(1).strip()
        else:
            # Just grab the first word that isn't a common verb or preposition
            words = query.split()
            for word in words:
                if word.lower() not in ["search", "find", "for", "in", "grep", "look", "show", "get", "with", "and", "the"]:
                    params["pattern"] = word
                    break
    
    # Clean up pattern (remove unnecessary quotes)
    if params["pattern"].startswith(("'", '"')) and params["pattern"].endswith(("'", '"')):
        params["pattern"] = params["pattern"][1:-1]
    
    return params

if __name__ == "__main__":
    # Run the server with stdio transport for MCP
    mcp.run()