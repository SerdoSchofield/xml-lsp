import logging
import re

import xmlschema
from lsprotocol.types import (
    Diagnostic,
    DiagnosticSeverity,
    Position,
    Range,
)
from pygls.server import LanguageServer
from pygls.uris import to_fs_path

# Configure logging to a file for debugging.
# This is useful as stdout is used for LSP communication.
logging.basicConfig(
    filename="/tmp/xml-language-server.log", level=logging.DEBUG, filemode="w"
)

server = LanguageServer("xml-language-server", "v0.1")


@server.feature("initialize")
def initialize(ls, params):
    """Server is initialized."""
    logging.info("XML Language Server initialized.")

    initialization_options = params.initialization_options or {}
    schema_path = initialization_options.get("schema")
    ls.schema_path = schema_path
    ls.schema = None

    if schema_path:
        logging.info(f"Schema path set to: {schema_path}")
        try:
            ls.schema = xmlschema.XMLSchema11(schema_path)
            logging.info(f"Successfully loaded schema: {schema_path}")
            logging.info(f"   Defined elements: {list(ls.schema.elements.keys())}")

        except Exception as e:
            # Using error level for exceptions.
            logging.error(
                f"Failed to load schema from {schema_path}: {e}", exc_info=True
            )
    else:
        logging.info("No schema path provided.")

    return None


def _validate_document(ls, uri):
    """Validate the document against the schema."""
    if not ls.schema:
        logging.info("No schema available, skipping validation.")
        ls.publish_diagnostics(uri, [])
        return

    try:
        file_path = to_fs_path(uri)
        validation_errors = list(ls.schema.iter_errors(file_path))
        if not validation_errors:
            logging.info(f"Validation successful for {uri}: No errors found.")
            ls.publish_diagnostics(uri, [])
        else:
            diagnostics = []
            for error in validation_errors:
                # The xmlschema library provides 1-based line/column numbers.
                # LSP positions are 0-based.
                # line = (error.line or 1) - 1
                # column = (error.column or 1) - 1

                # AI! Here, print out the error information to the log.
                # There may or may not be line and column information available
                # on the error.

                line = 1
                column = 1

                pos = Position(line=line, character=column)

                diagnostic = Diagnostic(
                    range=Range(start=pos, end=pos),
                    message=error.message,
                    severity=DiagnosticSeverity.Error,
                )
                diagnostics.append(diagnostic)

            logging.warning(f"Validation of {uri} found {len(diagnostics)} errors.")
            ls.publish_diagnostics(uri, diagnostics)
    except Exception as e:
        msg = str(e)
        diagnostics = []
        match = re.search(r": line (\d+), column (\d+)", msg)

        if match:
            line = int(match.group(1))
            column = int(match.group(2))
            error_message = msg[: match.start()]

            # LSP positions are 0-based.
            # For some reason we need to subtract 2?, not just 1
            pos = Position(line=line - 2, character=column - 1)

            diagnostic = Diagnostic(
                range=Range(start=pos, end=pos),
                message=error_message,
                severity=DiagnosticSeverity.Error,
            )
            diagnostics.append(diagnostic)

        ls.publish_diagnostics(uri, diagnostics)
        logging.error(f"Error during validation of {uri}: {e}", exc_info=False)


@server.feature("textDocument/didOpen")
def did_open(ls, params):
    """Document opened."""
    uri = params.text_document.uri
    logging.info(f"File opened: {uri}")
    _validate_document(ls, uri)


@server.feature("textDocument/didChange")
def did_change(ls, params):
    """Document changed."""
    uri = params.text_document.uri
    logging.info(f"File changed: {uri}")
    _validate_document(ls, uri)


def main():
    """The main entry point for the server."""
    logging.info("Starting XML language server.")
    server.start_io()


if __name__ == "__main__":
    main()
