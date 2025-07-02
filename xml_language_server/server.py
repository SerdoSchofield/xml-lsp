import logging
from pygls.server import LanguageServer

# Configure logging to a file for debugging.
# This is useful as stdout is used for LSP communication.
logging.basicConfig(filename="/tmp/xml-language-server.log", level=logging.DEBUG, filemode="w")

server = LanguageServer("xml-language-server", "v0.1")

@server.feature('initialize')
def initialize(ls, params):
    """Server is initialized."""
    logging.info("XML Language Server initialized.")
    return None


def main():
    """The main entry point for the server."""
    logging.info('Starting XML language server.')
    server.start_io()


if __name__ == '__main__':
    main()
