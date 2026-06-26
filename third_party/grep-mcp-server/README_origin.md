# MCP-Grep
[![smithery badge](https://smithery.ai/badge/@erniebrodeur/mcp-grep)](https://smithery.ai/server/@erniebrodeur/mcp-grep)

A grep server implementation that exposes grep functionality through the Model Context Protocol (MCP).

## Installation

### Installing via Smithery

To install Grep Server for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@erniebrodeur/mcp-grep):

```bash
npx -y @smithery/cli install @erniebrodeur/mcp-grep --client claude
```

### Manual Installation
```bash
pip install mcp-grep
```

## Usage

MCP-Grep runs as a server that can be used by MCP-compatible clients:

```bash
# Start the MCP-Grep server
mcp-grep-server

# Or use the MCP Inspector for interactive debugging and testing
mcp-grep-inspector
```

The server exposes the following MCP functionality:

- **Resource:** `grep://info` - Returns information about the system grep binary
- **Tool:** `grep` - Searches for patterns in files using the system grep binary

## Features

- Information about the system grep binary (path, version, supported features)
- Search for patterns in files using regular expressions
- Support for common grep options:
  - Case-insensitive matching
  - Context lines (before and after matches)
  - Maximum match count
  - Fixed string matching (non-regex)
  - Recursive directory searching
- Natural language prompt understanding for easier use with LLMs
- Interactive debugging and testing through MCP Inspector

## Example API Usage

Using the MCP Python client:

```python
from mcp.client import MCPClient

# Connect to the MCP-Grep server
client = MCPClient()

# Get information about the grep binary
grep_info = client.get_resource("grep://info")
print(grep_info)

# Search for a pattern in files
result = client.use_tool("grep", {
    "pattern": "search_pattern",
    "paths": ["file.txt", "directory/"],
    "ignore_case": True,
    "recursive": True
})
print(result)
```

## Natural Language Prompts

MCP-Grep understands natural language prompts, making it easier to use with LLMs. Examples:

```
# Basic search
Search for 'error' in log.txt

# Case-insensitive search
Find all instances of 'WARNING' regardless of case in system.log

# With context lines
Search for 'exception' in error.log and show 3 lines before and after each match

# Recursive search
Find all occurrences of 'deprecated' in the src directory and its subdirectories

# Fixed string search (non-regex)
Search for the exact string '.*' in config.js

# Limited results
Show me just the first 5 occurrences of 'TODO' in the project files

# Multiple options
Find 'password' case-insensitively in all .php files, show 2 lines of context, and limit to 10 results
```

## MCP Inspector Integration

MCP-Grep includes an MCP Inspector integration for interactive debugging and testing:

```bash
# Start the MCP Inspector with MCP-Grep
mcp-grep-inspector
```

This opens a web-based UI where you can:
- Explore available resources and tools
- Test grep operations with different parameters
- View formatted results
- Debug issues with your grep queries

## Development

```bash
# Clone the repository
git clone https://github.com/erniebrodeur/mcp-grep.git
cd mcp-grep

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest
```

## License

MIT