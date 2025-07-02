import logging

import xmlschema
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
        return

    try:
        file_path = to_fs_path(uri)
        validation_errors = list(ls.schema.iter_errors(file_path))
        if not validation_errors:
            logging.info(f"Validation successful for {uri}: No errors found.")
        else:
            logging.warning(
                f"Validation of {uri} found {len(validation_errors)} errors:"
            )
            for error in validation_errors:
                logging.warning(f"  - {error}")
    except Exception as e:
        # AI!
        # The exception will be of the form:
        # "invalid XML syntax: not well-formed (invalid token): line 4, column 2"
        #
        # Extract the line and column number from the exception, and send back a
        # publishDiagnostics notification, passing the document's URI and a Diagnostic object,
        # containing the appropriate range, the message , and the severity. In this case,
        # the severity is Error.  The range is determine by the line and column you
        # extracted above.  The message should be the
        # full exception message, with the line and column information trimmed off.
        # In the above example, the message returned in the Diagnostic should be:
        # "invalid XML syntax: not well-formed (invalid token)"
        logging.error(f"Error during validation of {uri}: {e}", exc_info=True)


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
