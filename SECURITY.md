# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Security Features

### Path Traversal Protection

The xml-lsp server implements multiple layers of defense against path traversal attacks:

1. **Schema Path Validation**: All schema file paths are validated before use
   - Root element names are sanitized to prevent `../` traversal
   - Schema filenames from JSON maps are validated
   - Paths are canonicalized and verified to stay within intended directories

2. **File URI Validation**: Document URIs are validated before file access
   - URIs are resolved to canonical file paths
   - File existence and type are verified

3. **Log File Path Security**: Log file paths are validated to prevent arbitrary writes
   - Parent directories are created safely
   - Invalid paths fall back to secure defaults

### Input Sanitization

All user-controlled inputs are sanitized:

- XML element names (from parsed documents)
- Schema file paths (from configuration)
- File URIs (from LSP client)
- Log file paths (from command-line arguments)

### Dependency Security

All Python dependencies are pinned to specific versions:

```
xmlschema==4.2.0
lxml==6.0.2
cachetools==6.2.2
pygls==1.3.1
lsprotocol==2023.0.1
```

These versions have been scanned for known vulnerabilities using the GitHub Advisory Database.

## Reporting a Vulnerability

If you discover a security vulnerability in xml-lsp, please report it by:

1. **DO NOT** open a public GitHub issue
2. Email the maintainer directly (see repository for contact information)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will respond within 48 hours and provide a timeline for a fix.

## Security Best Practices for Users

### Schema Configuration

When configuring schema locators:

1. **Use absolute paths** for schema directories and files
2. **Restrict permissions** on schema directories to prevent unauthorized modifications
3. **Validate schema sources** - only use schemas from trusted sources
4. **Keep schemas updated** to match your XML file versions

Example secure configuration:

```elisp
(setq xml-lsp-schema-locators
  '((:rootElement t
     :searchPaths ["/usr/local/share/xml-schemas"])  ; System directory
    (:locationHint "~/.config/xml-lsp/schema_map.json")))  ; User config
```

### File Permissions

Set appropriate permissions on xml-lsp files:

```bash
# Schema directories should be readable but not writable by the server
chmod 755 /path/to/schemas
chmod 644 /path/to/schemas/*.xsd

# Log files should be writable only by the user
chmod 600 /tmp/xmllsp.log
```

### Virtual Environment

Always use a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This isolates dependencies and prevents conflicts with system packages.

### Network Security

The xml-lsp server:
- Does NOT make network requests
- Does NOT download schemas from URLs
- Does NOT expose network services
- Communicates only via stdio with the LSP client

All schema files must be local. Schema location hints that point to URLs are resolved using a local JSON mapping file.

## Security Audit History

| Date       | Action                           | Result                    |
|------------|----------------------------------|---------------------------|
| 2025-11-17 | Dependency scan                  | No vulnerabilities found  |
| 2025-11-17 | Path traversal review            | Vulnerabilities fixed     |
| 2025-11-17 | Input validation audit           | Improvements implemented  |

## Acknowledgments

We appreciate the security research community's efforts in keeping open source software secure. If you report a valid security issue, we'll be happy to acknowledge your contribution (with your permission).

## License

This security policy is part of xml-lsp and is licensed under the Apache License, Version 2.0.

Copyright © 2025 Google LLC.
