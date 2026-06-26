Feature: Client Prompt Examples for Grep MCP Server
  As a client using the MCP grep server
  I want examples of effective prompts
  So I can efficiently search for patterns in files

  Scenario: Basic file search prompt
    Given I need to search a specific file for a pattern
    When I use the prompt "Search for 'error' in log.txt"
    Then the MCP server should interpret this as a grep with:
      | parameter | value    |
      | pattern   | error    |
      | paths     | log.txt  |

  Scenario: Case-insensitive search prompt
    Given I need to search without case sensitivity
    When I use the prompt "Find all instances of 'WARNING' regardless of case in system.log"
    Then the MCP server should interpret this as a grep with:
      | parameter   | value      |
      | pattern     | WARNING    |
      | paths       | system.log |
      | ignore_case | true       |

  Scenario: Search with context lines prompt
    Given I need to see lines before and after matches
    When I use the prompt "Search for 'exception' in error.log and show 3 lines before and after each match"
    Then the MCP server should interpret this as a grep with:
      | parameter      | value      |
      | pattern        | exception  |
      | paths          | error.log  |
      | before_context | 3          |
      | after_context  | 3          |

  Scenario: Recursive directory search prompt
    Given I need to search across multiple files in a directory
    When I use the prompt "Find all occurrences of 'deprecated' in the src directory and its subdirectories"
    Then the MCP server should interpret this as a grep with:
      | parameter  | value        |
      | pattern    | deprecated   |
      | paths      | src          |
      | recursive  | true         |

  Scenario: Fixed string search prompt
    Given I need to search for a string containing special characters
    When I use the prompt "Search for the exact string '.*' in config.js"
    Then the MCP server should interpret this as a grep with:
      | parameter     | value     |
      | pattern       | .*        |
      | paths         | config.js |
      | fixed_strings | true      |

  Scenario: Limited results prompt
    Given I only want to see the first few matches
    When I use the prompt "Show me just the first 5 occurrences of 'TODO' in the project files"
    Then the MCP server should interpret this as a grep with:
      | parameter | value  |
      | pattern   | TODO   |
      | paths     | .      |
      | recursive | true   |
      | max_count | 5      |

  Scenario: Regular expression search prompt
    Given I need to search using a regex pattern
    When I use the prompt "Find all lines containing email addresses in users.txt using regex"
    Then the MCP server should interpret this as a grep with:
      | parameter | value                         |
      | pattern   | [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,} |
      | paths     | users.txt                     |

  Scenario: Inverted match prompt
    Given I need to find lines that don't match a pattern
    When I use the prompt "Show me all lines in config.json that don't contain the word 'default'"
    Then the MCP server should interpret this as a grep with:
      | parameter    | value       |
      | pattern      | default     |
      | paths        | config.json |
      | invert_match | true        |

  Scenario: Multiple file type search prompt
    Given I need to search only specific file types
    When I use the prompt "Find 'security' in all JavaScript and TypeScript files"
    Then the MCP server should interpret this as a grep with:
      | parameter | value     |
      | pattern   | security  |
      | paths     | *.js *.ts |
      | recursive | true      |

  Scenario: Combined options prompt
    Given I need to use multiple search options together
    When I use the prompt "Find 'password' case-insensitively in all .php files, show 2 lines of context, and limit to 10 results"
    Then the MCP server should interpret this as a grep with:
      | parameter      | value     |
      | pattern        | password  |
      | paths          | *.php     |
      | recursive      | true      |
      | ignore_case    | true      |
      | before_context | 2         |
      | after_context  | 2         |
      | max_count      | 10        |