# Installing xml-lsp in Doom Emacs

This guide will help you install and configure the xml-lsp language server in Doom Emacs.

## Prerequisites

- Doom Emacs installed and configured
- Python 3.12 or later
- Git

## Installation Steps

### 1. Clone the xml-lsp Repository

```bash
cd ~
git clone https://github.com/SerdoSchofield/xml-lsp.git
```

### 2. Set Up Python Environment

```bash
cd ~/xml-lsp
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Doom Emacs

#### Add Package to `packages.el`

Add this line to your `~/.doom.d/packages.el`:

```elisp
(package! xml-lsp
  :recipe (:local-repo "~/xml-lsp"))
```

Alternatively, to install from GitHub:

```elisp
(package! xml-lsp
  :recipe (:host github :repo "SerdoSchofield/xml-lsp"))
```

#### Configure in `config.el`

Add the following to your `~/.doom.d/config.el`:

```elisp
(use-package! xml-lsp
  :after nxml-mode
  :config
  ;; Set the installation directory
  (setq xml-lsp-server-install-dir (expand-file-name "~/xml-lsp"))
  
  ;; Configure schema locators (customize these paths for your setup)
  (setq xml-lsp-schema-locators
        '(;; Look for schemas based on root element name
          (:rootElement t
           :searchPaths ["/path/to/your/schemas"])
          
          ;; Use a schema location hint map
          (:locationHint "/path/to/schema-cache/schema_map.json")
          
          ;; Pattern-based schema matching
          (:patterns [(:pattern "*.csproj"
                       :path "/path/to/Microsoft.Build.Core.xsd"
                       :useDefaultNamespace t)
                      (:pattern "pom.xml"
                       :path "/path/to/maven-4.0.0.xsd")])))
  
  ;; Optional: Set log level for debugging
  ;; (setq xml-lsp-log-level "DEBUG")
  ;; (setq xml-lsp-log-file "/tmp/xmllsp.log")
  
  ;; Choose your LSP client:
  
  ;; Option A: Use with lsp-mode (recommended)
  (add-hook 'nxml-mode-hook #'xml-lsp-mode)
  
  ;; Option B: Use with eglot (alternative)
  ;; (add-hook 'nxml-mode-hook #'xml-lsp-eglot-ensure)
  )
```

### 4. Sync Packages

Run the following command in Doom Emacs:

```
M-x doom/reload
```

Or from the terminal:

```bash
~/.emacs.d/bin/doom sync
```

### 5. Restart Emacs

Restart Doom Emacs for the changes to take effect.

## Schema Configuration

The xml-lsp server needs to know where to find XML schemas (XSD files) for validation. There are three methods:

### Method 1: Root Element Locator

The server looks for a schema file named `<RootElement>.xsd` in the specified search paths.

Example:
```elisp
(:rootElement t
 :searchPaths ["/home/user/schemas"
               "/usr/share/xml/schemas"])
```

For an XML file with root element `<project>`, it will look for `project.xsd` in those directories.

### Method 2: Location Hint with Schema Map

Create a JSON file that maps schema locations (from `xsi:schemaLocation` attributes) to local schema files.

Schema map file (`schema_map.json`):
```json
{
  "http://maven.apache.org/xsd/maven-4.0.0.xsd": "maven-4.0.0.xsd",
  "http://www.w3.org/2001/XMLSchema": "XMLSchema.xsd"
}
```

Configuration:
```elisp
(:locationHint "/home/user/.xml-schemas/schema_map.json")
```

The schema files should be in the same directory as the `schema_map.json` file.

### Method 3: Pattern-Based Matching

Match files by glob patterns and assign specific schemas.

```elisp
(:patterns [(:pattern "*.csproj"
             :path "/usr/share/schemas/Microsoft.Build.Core.xsd"
             :useDefaultNamespace t)
            (:pattern "pom.xml"
             :path "/usr/share/schemas/maven-4.0.0.xsd")])
```

The `useDefaultNamespace` option is useful for schemas that define a namespace but the XML files don't use one (like MSBuild .csproj files).

## Usage

Once configured, xml-lsp will automatically start when you open an XML file in `nxml-mode`. You'll get:

- **Validation**: Real-time schema validation with error highlighting
- **Completion**: Auto-completion suggestions for XML elements
- **Diagnostics**: Detailed error messages for validation failures

## Troubleshooting

### Server not starting

1. Check that Python environment is set up correctly:
   ```bash
   cd ~/xml-lsp
   source .venv/bin/activate
   python -m xml_language_server.xmllsp --help
   ```

2. Check the server log file (default: `/tmp/xmllsp.log`) for errors:
   ```bash
   tail -f /tmp/xmllsp.log
   ```

3. Enable debug logging:
   ```elisp
   (setq xml-lsp-log-level "DEBUG")
   ```

### No schema found

Check that:
- Your schema locator configuration is correct
- Schema files exist at the specified paths
- File permissions allow reading the schema files

### LSP features not working

Make sure you have either `lsp-mode` or `eglot` enabled in your Doom Emacs configuration:

For lsp-mode, ensure this is in your `init.el`:
```elisp
:tools
lsp
```

For eglot, ensure this is in your `init.el`:
```elisp
:tools
(lsp +eglot)
```

## Advanced Configuration

### Per-project Configuration

You can use directory-local variables to set project-specific schema locators. Create a `.dir-locals.el` file in your project root:

```elisp
((nxml-mode . ((xml-lsp-schema-locators . ((:patterns [(:pattern "*.xml"
                                                         :path "./schemas/my-schema.xsd")]))))))
```

### Custom Keybindings

Add custom keybindings for xml-lsp commands:

```elisp
(map! :map nxml-mode-map
      :localleader
      :desc "Restart XML LSP" "r" #'lsp-workspace-restart
      :desc "Show XML LSP version" "v" #'xml-lsp-version)
```

## Support

For issues and questions:
- GitHub Issues: https://github.com/SerdoSchofield/xml-lsp/issues
- Check the log file at `/tmp/xmllsp.log` for detailed error messages

## License

Copyright © 2025 Google LLC. Licensed under the Apache License, Version 2.0.
