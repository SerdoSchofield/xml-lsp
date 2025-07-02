import logging
import xmlschema
from pygls.server import LanguageServer

# Configure logging to a file for debugging.
# This is useful as stdout is used for LSP communication.
logging.basicConfig(filename="/tmp/xml-language-server.log", level=logging.DEBUG, filemode="w")

server = LanguageServer("xml-language-server", "v0.1")

@server.feature('initialize')
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
        except Exception as e:
            # Using error level for exceptions.
            logging.error(f"Failed to load schema from {schema_path}: {e}", exc_info=True)
    else:
        logging.info("No schema path provided.")

    return None


@server.feature('textDocument/didOpen')
def did_open(ls, params):
    """Document opened."""
    logging.info(f"File opened: {params.text_document.uri}")


def main():
    """The main entry point for the server."""
    logging.info('Starting XML language server.')
    server.start_io()


if __name__ == '__main__':
    main()
