"""Core functionality for MCP-Grep."""

import re
import os
import fnmatch
from pathlib import Path
from typing import Dict, Generator, List, Pattern, Union, Optional, Tuple


class MCPGrep:
    """MCP-Grep main class."""

    def __init__(
        self, 
        pattern: str, 
        ignore_case: bool = False, 
        fixed_strings: bool = False,
        regexp: bool = True,
        invert_match: bool = False,
        line_number: bool = True,
        before_context: int = 0,
        after_context: int = 0,
        context: Optional[int] = None,
        max_count: int = 0
    ):
        """Initialize with search pattern.

        Args:
            pattern: Regular expression pattern to search for
            ignore_case: Whether to perform case-insensitive matching
            fixed_strings: Treat pattern as literal text, not regex
            regexp: Explicitly use regular expressions for pattern
            invert_match: Select lines not matching pattern
            line_number: Show line numbers
            before_context: Number of lines to show before each match
            after_context: Number of lines to show after each match
            context: Number of lines to show before and after each match (overrides before/after_context)
            max_count: Stop after this many matches
        """
        # If context is provided, it overrides before_context and after_context
        if context is not None:
            self.before_context = context
            self.after_context = context
        else:
            self.before_context = before_context
            self.after_context = after_context
        
        self.invert_match = invert_match
        self.line_number = line_number
        self.max_count = max_count
        
        # Handle pattern based on flags
        if fixed_strings:
            # For fixed strings, escape the pattern to match it literally
            pattern = re.escape(pattern)
            regexp = True
        
        # Set regex flags
        flags = 0
        if ignore_case:
            flags |= re.IGNORECASE
        
        # Compile the pattern
        self.pattern = re.compile(pattern, flags) if regexp else None
        self.raw_pattern = pattern
        self.ignore_case = ignore_case
    
    def _matches_pattern(self, line: str) -> bool:
        """Check if a line matches the pattern based on invert_match setting."""
        if self.pattern:
            matches = bool(self.pattern.search(line))
        else:
            # For non-regexp matches, do simple string contains with case sensitivity
            if self.ignore_case:
                matches = self.raw_pattern.lower() in line.lower()
            else:
                matches = self.raw_pattern in line
                
        # Handle invert_match - return True if line should be included
        return matches != self.invert_match
    
    def search_file(self, file_path: Union[str, Path]) -> Generator[Dict, None, None]:
        """Search for pattern in a file.

        Args:
            file_path: Path to the file to search in

        Yields:
            Dict containing line number, matched line, and match spans
        """
        path = Path(file_path)
        
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Read the entire file to handle context and inversion properly
        with open(path, 'r', encoding='utf-8', errors='replace') as file:
            lines = file.readlines()
        
        # Process lines with context and other options
        match_count = 0
        matches_with_context = []
        
        # First pass: find all matching lines
        for line_idx, line in enumerate(lines):
            line_content = line.rstrip('\n')
            line_num = line_idx + 1  # 1-based line numbering
            
            # Check if line matches pattern
            if self._matches_pattern(line_content):
                # If we're showing context, build a context object
                if self.before_context > 0 or self.after_context > 0:
                    # Calculate context line ranges
                    before_start = max(0, line_idx - self.before_context)
                    after_end = min(len(lines), line_idx + self.after_context + 1)
                    
                    # Get matches for highlighting
                    matches = []
                    if self.pattern and not self.invert_match:
                        for m in self.pattern.finditer(line_content):
                            matches.append((m.start(), m.end()))
                    
                    # Create match result with context
                    match_with_context = {
                        "match": {
                            "file": str(path),
                            "line": line_content,
                            "matches": matches
                        }
                    }
                    
                    # Add line number if requested
                    if self.line_number:
                        match_with_context["match"]["line_num"] = line_num
                    
                    # Add before context
                    before_context = []
                    for j in range(before_start, line_idx):
                        context_line = {
                            "file": str(path), 
                            "line": lines[j].rstrip('\n')
                        }
                        if self.line_number:
                            context_line["line_num"] = j + 1
                        before_context.append(context_line)
                    match_with_context["before_context"] = before_context
                    
                    # Add after context
                    after_context = []
                    for j in range(line_idx + 1, after_end):
                        context_line = {
                            "file": str(path), 
                            "line": lines[j].rstrip('\n')
                        }
                        if self.line_number:
                            context_line["line_num"] = j + 1
                        after_context.append(context_line)
                    match_with_context["after_context"] = after_context
                    
                    matches_with_context.append(match_with_context)
                else:
                    # Simple match without context
                    match_result = {
                        "file": str(path),
                        "line": line_content,
                    }
                    
                    # Add line number if requested
                    if self.line_number:
                        match_result["line_num"] = line_num
                    
                    # Add match positions if not invert_match
                    if self.pattern and not self.invert_match:
                        match_result["matches"] = [
                            (m.start(), m.end()) for m in self.pattern.finditer(line_content)
                        ]
                    else:
                        match_result["matches"] = []
                    
                    yield match_result
                
                match_count += 1
                
                # Check max_count limit
                if self.max_count > 0 and match_count >= self.max_count:
                    break
        
        # If we have matches with context, yield them after processing all lines
        if matches_with_context:
            for match in matches_with_context[:self.max_count if self.max_count > 0 else None]:
                yield match
    
    def search_files(
        self, 
        file_paths: List[Union[str, Path]], 
        recursive: bool = False,
        file_pattern: Optional[str] = None
    ) -> Generator[Dict, None, None]:
        """Search for pattern in multiple files.

        Args:
            file_paths: List of file paths to search in
            recursive: Whether to search directories recursively
            file_pattern: Optional pattern to filter files (e.g., "*.txt")

        Yields:
            Dict containing file path, line number, matched line, and match spans
        """
        # Track total matches for max_count across all files
        total_matches = 0
        
        # Process each path
        for path in file_paths:
            path_obj = Path(path)
            
            # Handle directory case with recursion
            if path_obj.is_dir():
                if recursive:
                    # Walk through the directory recursively
                    for root, _, files in os.walk(path):
                        for file in files:
                            # Skip files that don't match the pattern
                            if file_pattern and not fnmatch.fnmatch(file, file_pattern):
                                continue
                                
                            file_path = os.path.join(root, file)
                            try:
                                for result in self.search_file(file_path):
                                    yield result
                                    total_matches += 1
                                    
                                    # Check overall max_count
                                    if self.max_count > 0 and total_matches >= self.max_count:
                                        return
                            except Exception as e:
                                print(f"Error searching {file_path}: {e}")
                else:
                    # If not recursive, just search files in the top directory
                    for item in path_obj.iterdir():
                        if item.is_file():
                            # Skip files that don't match the pattern
                            if file_pattern and not fnmatch.fnmatch(item.name, file_pattern):
                                continue
                                
                            try:
                                for result in self.search_file(item):
                                    yield result
                                    total_matches += 1
                                    
                                    # Check overall max_count
                                    if self.max_count > 0 and total_matches >= self.max_count:
                                        return
                            except Exception as e:
                                print(f"Error searching {item}: {e}")
            # Handle single file case
            elif path_obj.is_file():
                # Skip files that don't match the pattern
                if file_pattern and not fnmatch.fnmatch(path_obj.name, file_pattern):
                    continue
                    
                try:
                    for result in self.search_file(path_obj):
                        yield result
                        total_matches += 1
                        
                        # Check overall max_count
                        if self.max_count > 0 and total_matches >= self.max_count:
                            return
                except Exception as e:
                    print(f"Error searching {path_obj}: {e}")
            # Handle file pattern case (glob)
            elif "*" in str(path) or "?" in str(path):
                # Get the directory part and the pattern part
                dir_part = os.path.dirname(path) or "."
                base_pattern = os.path.basename(path)
                
                # Override file_pattern if the path itself has a pattern
                effective_file_pattern = base_pattern
                
                # Search files in the directory that match the pattern
                dir_path = Path(dir_part)
                if dir_path.exists() and dir_path.is_dir():
                    for item in dir_path.iterdir():
                        if item.is_file() and fnmatch.fnmatch(item.name, effective_file_pattern):
                            try:
                                for result in self.search_file(item):
                                    yield result
                                    total_matches += 1
                                    
                                    # Check overall max_count
                                    if self.max_count > 0 and total_matches >= self.max_count:
                                        return
                            except Exception as e:
                                print(f"Error searching {item}: {e}")
            else:
                print(f"Path not found or invalid: {path}")
