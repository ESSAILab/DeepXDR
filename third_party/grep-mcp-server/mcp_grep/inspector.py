"""MCP Inspector integration for MCP-Grep."""

import os
import subprocess
import sys
from pathlib import Path


def run_inspector():
    """Run the MCP Inspector with the MCP-Grep server.
    
    This function launches the MCP Inspector web UI with the MCP-Grep server
    configured, allowing for interactive debugging and testing of the server's
    functionality.
    """
    # Get the path to the mcp_grep directory
    mcp_grep_dir = Path(__file__).parent.absolute()
    project_dir = mcp_grep_dir.parent
    server_path = mcp_grep_dir / "server.py"
    
    print("Starting MCP Inspector with MCP-Grep server...")
    print(f"Project directory: {project_dir}")
    print(f"Server path: {server_path}")
    print("\nThe MCP Inspector web UI should open in your browser shortly.")
    print("If it doesn't, navigate to the URL displayed in the terminal.")
    print("\nPress Ctrl+C to stop the server and exit.\n")
    
    # Set up environment variables
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_dir)
    
    # Build the npx command to run the inspector
    # This requires Node.js to be installed
    cmd = [
        "npx",
        "@modelcontextprotocol/inspector",
        sys.executable,  # Use the current Python interpreter
        str(server_path)
    ]
    
    try:
        # Run the inspector and wait for it to exit
        subprocess.run(cmd, env=env, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running MCP Inspector: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping MCP Inspector...")
        sys.exit(0)


if __name__ == "__main__":
    run_inspector()