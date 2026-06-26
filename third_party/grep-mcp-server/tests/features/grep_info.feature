Feature: Grep Info Resource
  As Claude (an LLM using MCP)
  I want to understand the grep capabilities available
  So I can use the most appropriate search options

  Scenario: Retrieving grep binary information
    Given I'm connected to the MCP grep server
    When I request the "grep://info" resource
    Then I should receive grep binary metadata as JSON
    And the metadata should include the binary path
    And the metadata should include version information
    And the metadata should include PCRE support status
    And the metadata should include color support status