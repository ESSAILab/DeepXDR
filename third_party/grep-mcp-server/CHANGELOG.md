# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2025-04-08

### Added

- support for Smithery.

## [0.2.0] - 2025-04-05

### Added

- Improved testing
- MCP Inspector integration (`mcp_grep.inspector`)
- New command-line entry point: `mcp-grep-inspector`
- Web-based UI for interactive debugging and testing of the MCP-Grep server
- Documentation for inspector usage

### Changed
- Updated package configuration to include the new inspector entry point

## [0.1.2] - 2025-03-31

### Fixed
- Fixed result parsing for special characters in grep output
- Improved error handling for missing grep binary

## [0.1.1] - 2025-03-15

### Added
- Initial release
- MCP server implementation for grep functionality
- Resource API for grep binary information
- Tool API for searching files using grep
- Basic test suite with BDD features