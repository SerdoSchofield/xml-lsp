# Changelog

All notable changes to xml-lsp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2025-11-17

### Added
- **Emacs Package (xml-lsp.el)**: Complete Emacs integration
  - Support for both lsp-mode and eglot
  - Auto-detection of server installation
  - Customizable schema locators
  - Installation helper command
  - Comprehensive documentation
- **Doom Emacs Guide**: Step-by-step installation guide (DOOM_EMACS_INSTALL.md)
- **Security Documentation**: SECURITY.md with security policy and best practices
- **Python Virtual Environment**: Added .gitignore for Python artifacts

### Security
- **Path Traversal Protection**: Fixed vulnerabilities in schema locator functions
  - Added validation in `_find_schemapath_by_rootelement`
  - Added validation in `_find_schemapath_by_location_hint`
  - Created `_validate_schema_path` helper function
  - Implemented canonical path resolution with directory boundary checks
- **File URI Validation**: Added `_validate_file_uri` to safely handle document URIs
- **Log File Security**: Validated log file paths to prevent arbitrary file writes
- **Input Sanitization**: Added character validation and path component checks
- **Dependency Pinning**: Pinned all dependencies to known-secure versions
  - xmlschema==4.2.0
  - lxml==6.0.2
  - cachetools==6.2.2
  - pygls==1.3.1
  - lsprotocol==2023.0.1

### Fixed
- **pygls Compatibility**: Downgraded from pygls 2.0 to 1.3.1 for API compatibility
- **Path Resolution**: All file paths now use `Path.resolve()` for canonicalization

### Changed
- **Requirements**: Updated requirements.txt with pinned versions
- **Imports**: Added `Path` from pathlib for secure path operations
- **Error Handling**: Improved error messages and logging for security events

## [0.1.0] - 2025-07-03

### Added
- Initial release of xml-lsp server
- XSD 1.0 and 1.1 schema validation
- Element completion suggestions
- Support for three schema locator methods:
  - Root element based lookup
  - xsi:schemaLocation hint with JSON mapping
  - Pattern-based file matching
- LSP features:
  - textDocument/didOpen
  - textDocument/didChange
  - textDocument/didSave
  - textDocument/didClose
  - textDocument/completion
  - publishDiagnostics
- Incremental document synchronization
- Deferred validation with debouncing
- Session caching with TTL
- Configurable logging (file and level)
- Support for default namespace override

### Documentation
- README.md with usage examples
- Eglot configuration examples
- Schema locator configuration guide
- LICENSE and NOTICE files
- CONTRIBUTING.md

[0.2.0]: https://github.com/SerdoSchofield/xml-lsp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SerdoSchofield/xml-lsp/releases/tag/v0.1.0
