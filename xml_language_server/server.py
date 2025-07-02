import logging
import re
import threading

import lxml.etree as ET
import xmlschema
from cachetools import TTLCache
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

server = LanguageServer("xml-language-server", "v0.2")


# Cache for storing document-specific sessions
# Sessions expire after 180 seconds of inactivity
session_cache = TTLCache(maxsize=128, ttl=180)


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
        xml_doc = ET.parse(file_path)

        validation_errors = list(ls.schema.iter_errors(xml_doc))
        if not validation_errors:
            logging.info(f"Validation successful for {uri}: No errors found.")
            ls.publish_diagnostics(uri, [])
        else:
            diagnostics = []
            for error in validation_errors:
                # The xmlschema library provides 1-based line/column numbers.
                # LSP positions are 0-based.
                logging.info(f"Schema validation error: {error.message}")

                line, column = 1, 1

                # error.sourceline is the line number of the element that the error
                # is associated with. For child validation errors, this is the parent.
                if hasattr(error, "sourceline") and error.sourceline:
                    line = error.sourceline
                    logging.info(f"  at line={error.sourceline}")

                if hasattr(error, "path"):
                    logging.info(f"  path: {error.path}")

                # For errors about unexpected children, we can get a more precise line number.
                if hasattr(error, "reason") and hasattr(error, "elem"):
                    logging.info(f"  reason: {error.reason}")
                    match = re.search(r"position (\d+)", error.reason)
                    if match:
                        position = int(match.group(1))  # 1-based index
                        try:
                            # The 'elem' attribute on the error is the parent element.
                            # Children can be accessed by index.
                            child_element = error.elem[position - 1]
                            if (
                                hasattr(child_element, "sourceline")
                                and child_element.sourceline
                            ):
                                line = child_element.sourceline
                        except IndexError:
                            pass  # child not found, use parent's line number

                # LSP positions are 0-based.
                pos = Position(line=line - 1, character=column - 1)

                diagnostic = Diagnostic(
                    range=Range(start=pos, end=pos),
                    message=error.reason or error.message,
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
    logging.info(f"File opened: {uri}, creating session.")
    session_cache[uri] = {}
    _validate_document(ls, uri)


@server.feature("textDocument/didChange")
def did_change(ls, params):
    """Document changed."""
    uri = params.text_document.uri
    logging.info(f"File changed: {uri}")

    # Ensure session exists, refreshing its TTL
    if uri not in session_cache:
        logging.info(f"Session not found for {uri}, creating one.")
        session_cache[uri] = {}
    session = session_cache[uri]

    # Immediate validation
    _validate_document(ls, uri)

    # Debounced validation with a timer
    if session.get("timer"):
        session["timer"].cancel()
        logging.info(f"Cancelled previous timer for {uri}.")

    def debounced_validation(ls_instance, doc_uri):
        logging.info(f"Running debounced validation for {doc_uri}.")
        _validate_document(ls_instance, doc_uri)

    timer = threading.Timer(5.0, debounced_validation, args=[ls, uri])
    session["timer"] = timer
    timer.start()
    logging.info(f"Scheduled debounced validation for {uri}.")


def main():
    """The main entry point for the server."""
    logging.info("Starting XML language server.")
    server.start_io()


if __name__ == "__main__":
    main()
