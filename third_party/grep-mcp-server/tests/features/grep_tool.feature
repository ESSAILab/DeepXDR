Feature: Grep Tool Functionality
  As Claude (an LLM using MCP)
  I want to search files for patterns through grep
  So I can find and analyze relevant information

  Scenario: Finding matches in a file
    Given I'm connected to the MCP grep server
    And a file with content "Line one has apple\nLine two has banana\nLine three has orange"
    When I invoke the grep tool with pattern "apple" and the file path
    Then I should receive results with 1 matching line
    And the result should include line number 1
    And the result should contain "apple"

  Scenario: Case-insensitive search
    Given I'm connected to the MCP grep server
    And a file with content "Line one has Apple\nLine two has APPLE\nLine three has apple"
    When I invoke the grep tool with pattern "apple" and ignore_case=True
    Then I should receive results with 3 matching lines

  Scenario: Search with context
    Given I'm connected to the MCP grep server
    And a file with content "Line one\nLine two has banana\nLine three\nLine four\nLine five has banana\nLine six"
    When I invoke the grep tool with pattern "banana" and before_context=1 and after_context=1
    Then I should receive results with 2 matching lines
    And each match should include context lines

  Scenario: Fixed string search
    Given I'm connected to the MCP grep server
    And a file with content "Line with a dot.\nLine with a [regex]"
    When I invoke the grep tool with pattern "." and fixed_strings=True
    Then I should receive results with 1 matching line
    And the result should contain "dot."

  Scenario: Recursive directory search
    Given I'm connected to the MCP grep server
    And a directory with multiple files containing the word "secret"
    When I invoke the grep tool with pattern "secret" and recursive=True
    Then I should receive results from multiple files

  Scenario: Limiting result count
    Given I'm connected to the MCP grep server
    And a file with content "match\nmatch\nmatch\nmatch\nmatch"
    When I invoke the grep tool with pattern "match" and max_count=3
    Then I should receive results with no more than 3 matching lines

  Scenario: Regular expression search
    Given I'm connected to the MCP grep server
    And a file with content "apple123\nbanana456\napple789\norange101112"
    When I invoke the grep tool with pattern "apple\d+" and regexp=True
    Then I should receive results with 2 matching lines
    And the results should contain "apple123" and "apple789"

  Scenario: Inverted match search
    Given I'm connected to the MCP grep server
    And a file with content "apple\nbanana\norange\ngrape"
    When I invoke the grep tool with pattern "apple" and invert_match=True
    Then I should receive results with 3 matching lines
    And the results should contain "banana", "orange", and "grape"
    
  Scenario: Controlling line number display
    Given I'm connected to the MCP grep server
    And a file with content "Line one\nLine two\nLine three"
    When I invoke the grep tool with pattern "two" and line_number=False
    Then I should receive results with 1 matching line
    And the result should not include line numbers
    
  Scenario: Multiple file pattern support
    Given I'm connected to the MCP grep server
    And multiple files with extensions ".txt" and ".log"
    When I invoke the grep tool with pattern "error" and file_pattern="*.log"
    Then I should receive results only from log files
    
  Scenario: Variable context line control
    Given I'm connected to the MCP grep server
    And a file with content "Line 1\nLine 2\nLine 3\nLine 4\nLine with match\nLine 6\nLine 7\nLine 8\nLine 9"
    When I invoke the grep tool with pattern "match" and context=3
    Then I should receive results with 1 matching line
    And the result should include 3 lines before and 3 lines after the match