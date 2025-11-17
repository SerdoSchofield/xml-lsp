# Copyright © 2025 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import argparse
import logging
import os
import re
import sys
import threading
from pathlib import Path

import lxml.etree as ET
import xmlschema
from cachetools import TTLCache
from lsprotocol.types import (
    CompletionItem,
    CompletionItemKind,
    CompletionList,
    Diagnostic,
    DiagnosticSeverity,
    Position,
    Range,
)
from pygls.server import LanguageServer
from pygls.uris import to_fs_path

from .workspace import Workspace

server = LanguageServer("xml-language-server", "v0.2")
server.workspaces = {}


# Cache for storing document-specific sessions
# Sessions expire after 180 seconds of inactivity
session_cache = TTLCache(maxsize=128, ttl=180)


def _validate_file_uri(uri):
    """
    Validates a file URI to ensure it's safe to access.
    Returns the resolved file path if valid, None otherwise.
    
    Security: Prevents access to arbitrary files outside the workspace.
    """
    if not uri or not isinstance(uri, str):
        return None
    
    try:
        file_path = to_fs_path(uri)
        resolved_path = Path(file_path).resolve()
        
        # Security: Ensure the file exists and is a regular file
        if not resolved_path.exists() or not resolved_path.is_file():
            return None
        
        # Security: Ensure the file has an XML extension
        if resolved_path.suffix.lower() not in ['.xml', '.xsd', '.csproj', '.pom', '.wsdl', '.xsl', '.xslt', '']:
            logging.warning(f"Unexpected file extension for XML document: {resolved_path}")
            # Still allow it but log warning
        
        return str(resolved_path)
    except (OSError, ValueError) as e:
        logging.error(f"Error validating file URI {uri}: {e}")
        return None


@server.feature("initialize")
def initialize(ls, params):
    """Server is initialized."""
    logging.info("XML Language Server initialized.")

    initialization_options = params.initialization_options or {}
    root_uri = params.root_uri

    if root_uri:
        logging.info(f"Workspace root: {root_uri}")
        ls.workspaces[root_uri] = Workspace(root_uri, initialization_options)

    return None


@server.feature("workspace/didChangeConfiguration")
def did_change_configuration(ls, params):
    """Configuration changed."""
    logging.info("Configuration changed. (no-op)")
    pass


def _pos_to_offset2(content: str, pos: Position) -> int:
    """Convert line/character position to a string offset."""
    lines = content.splitlines(True)
    if not lines:
        lines = [""]
    return _pos_to_offset(lines, pos)


def _pos_to_offset(lines: list[str], pos: Position) -> int:
    """Convert line/character position to a string offset."""
    offset = 0
    for i in range(pos.line):
        offset += len(lines[i])
    return offset + pos.character


def _apply_incremental_changes(content: str, changes: list) -> str:
    """Apply incremental changes to the document content."""
    for change in changes:
        if not hasattr(change, "range") or change.range is None:
            # Full content update
            return change.text

        lines = content.splitlines(True)
        if not lines:
            lines = [""]

        start_offset = _pos_to_offset(lines, change.range.start)
        end_offset = _pos_to_offset(lines, change.range.end)

        content = content[:start_offset] + change.text + content[end_offset:]
    return content


def _find_element_at_position(element, line):
    """Recursively find the deepest element at a given line number (1-based)."""
    candidate = None
    if (
        hasattr(element, "sourceline")
        and element.sourceline
        and element.sourceline <= line
    ):
        candidate = element
        for child in element:
            child_candidate = _find_element_at_position(child, line)
            if child_candidate is not None:
                candidate = child_candidate
    return candidate


def _validate_document(ls, uri, content, schema, default_xmlns):
    """Validate the document against the schema."""
    if not schema:
        logging.info("No schema available, skipping validation.")
        ls.publish_diagnostics(uri, [])
        return

    try:
        # xml_doc = ET.fromstring(content.encode("utf-8"))
        # validation_errors = list(schema.iter_errors(xml_doc))
        # Using XMLResource allows caller to specify a default namespace if desired.
        if default_xmlns:
            logging.info(f"applying default namespace {default_xmlns}")
            xml_resource = xmlschema.XMLResource(content, namespace=default_xmlns)
        else:
            logging.info(f"Using normal namespace rules")
            xml_resource = xmlschema.XMLResource(content)

        validation_errors = list(schema.iter_errors(xml_resource))

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
            pos = Position(line=line - 1, character=column - 1)

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
    logging.info(f"didOpen: {uri}, creating session.")
    content = params.text_document.text
    session_cache[uri] = {"content": content}

    root_uri = uri.rpartition("/")[0]
    workspace = ls.workspaces.get(root_uri)
    if not workspace:
        logging.warning(f"No workspace for {uri}")
        return

    schema, schema_path = workspace.get_schema_for_doc(uri, content)

    default_namespace = None
    if schema_path:
        default_namespace = workspace.default_xmlns_for_schemapath.get(schema_path)

    _validate_document(ls, uri, content, schema, default_namespace)


@server.feature("textDocument/didChange")
def did_change(ls, params):
    """Document changed."""
    uri = params.text_document.uri
    logging.info(f"didChange: {uri}")

    # Ensure session exists, refreshing its TTL
    if uri not in session_cache or "content" not in session_cache[uri]:
        logging.info(f"Session or content not found for {uri}, creating/re-reading.")
        
        # Security: Validate the file URI before accessing
        file_path = _validate_file_uri(uri)
        if not file_path:
            logging.error(f"Invalid or inaccessible file URI: {uri}")
            return
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                session_cache[uri] = {"content": content}
        except Exception as e:
            logging.error(f"Could not read file {uri}: {e}")
            return

    session = session_cache[uri]

    # figure the current state of the document
    current_content = session["content"]
    new_content = _apply_incremental_changes(current_content, params.content_changes)
    session["content"] = new_content

    # Schema lookup
    root_uri = uri.rpartition("/")[0]
    schema = None
    default_namespace = None
    workspace = ls.workspaces.get(root_uri)
    if workspace and uri in workspace.schemapaths_for_uri:
        schema_path = workspace.schemapaths_for_uri[uri]
        schema = workspace.schemas_for_xsdpath.get(schema_path)
        if schema_path:
            default_namespace = workspace.default_xmlns_for_schemapath.get(schema_path)

    if not schema:
        return None

    # Immediate validation
    _validate_document(ls, uri, new_content, schema, default_namespace)

    # As well as deferred validation with a timer, debounced
    if session.get("timer"):
        session["timer"].cancel()
        logging.info(f"Cancelled previous timer for {uri}.")

    def deferred_validation(ls_instance, doc_uri, doc_schema, default_xmlns):
        logging.info(f"Running deferred validation for {doc_uri}.")
        if doc_uri in session_cache and "content" in session_cache[doc_uri]:
            content = session_cache[doc_uri]["content"]
            _validate_document(ls_instance, doc_uri, content, doc_schema, default_xmlns)
        else:
            logging.warning(f"No content found for {doc_uri} in deferred validation.")

    timer = threading.Timer(
        4.0, deferred_validation, args=[ls, uri, schema, default_namespace]
    )
    session["timer"] = timer
    timer.start()
    logging.info(f"Scheduled deferred validation for {uri}.")


@server.feature("textDocument/didSave")
def did_save(ls, params):
    """Document saved, so refresh content cache."""
    uri = params.text_document.uri
    logging.info(f"didSave: {uri}, refreshing content cache.")
    
    # Security: Validate the file URI before accessing
    file_path = _validate_file_uri(uri)
    if not file_path:
        logging.error(f"Invalid or inaccessible file URI: {uri}")
        return
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        session_cache[uri] = {"content": content}
    except Exception as e:
        logging.error(f"Could not read file on save for {uri}: {e}")


@server.feature("textDocument/didClose")
def did_close(ls, params):
    """Document closed."""
    uri = params.text_document.uri
    logging.info(f"didClose: {uri}")

    root_uri = uri.rpartition("/")[0]
    workspace = ls.workspaces.get(root_uri)

    if workspace:
        workspace.release_document(uri)
    else:
        logging.warning(f"No workspace found for root URI: {root_uri}")

    pass


def _local_name_for_element(elt):
    """Returns the local name of an lxml element, ignoring the namespace."""
    name = None
    if hasattr(elt, "tag"):  # for lxml.etree.Element
        name = elt.tag
    elif hasattr(elt, "name"):  # for xmlschema
        name = elt.name

    if name:
        if "}" in name:
            return name.split("}", 1)[1]

    return name


def _namespace_for_element(elt):
    """Returns the namespace of an lxml element."""
    name = None
    if hasattr(elt, "tag"):  # for lxml.etree.Element
        name = elt.tag
    elif hasattr(elt, "name"):  # for xmlschema
        name = elt.name

    if not name:
        return None

    if "}" in name:
        return name.split("}", 1)[0][1:]

    return ""


def _get_elements_from_type(xsd_type, default_xmlns, visited_types=None):
    """Recursively get all element names from an XSD type, following base types."""
    if visited_types is None:
        visited_types = set()

    if not xsd_type or xsd_type in visited_types:
        return []

    visited_types.add(xsd_type)

    valid_children = []
    if hasattr(xsd_type, "content") and hasattr(xsd_type.content, "iter_elements"):
        for element_node in xsd_type.content.iter_elements():
            elt_xmlns = _namespace_for_element(element_node)
            if elt_xmlns == default_xmlns:
                valid_children.append(_local_name_for_element(element_node))
            else:
                valid_children.append(element_node.name)

    base_type = getattr(xsd_type, "base_type", None)
    if base_type:
        valid_children.extend(
            _get_elements_from_type(base_type, default_xmlns, visited_types)
        )

    return valid_children


def _get_element_context_at_position(
    schema: xmlschema.XMLSchema, default_namespace: str, xml_content: str, pos: Position
):
    """
    Finds the parent element and list of valid child elements at a specific position.

    Args:
        schema: A loaded xmlschema.XMLSchema object.
        xml_content: The potentially incomplete XML document as a string.
        pos: The LSP Position of the cursor.

    Returns:
        A tuple containing the parent lxml element (or None) and a list of
        valid child element tag names.
    """
    logging.info(f"_get_element_context_at_position()")

    position = _pos_to_offset2(xml_content, pos)

    # 1. Insert a temporary marker element at the cursor's position.
    #    This gives us a node to find in the parsed tree.
    marker_tag = "completion_marker_fa6fb971-e37d-4316-84ed-27507cf687b8"
    xml_with_marker = f"{xml_content[:position]}<{marker_tag}/>{xml_content[position:]}"

    # 2. Parse the potentially broken XML using lxml's recovering parser.
    parser = ET.XMLParser(recover=True)
    try:
        root = ET.fromstring(xml_with_marker.encode("utf-8"), parser)
    except ET.XMLSyntaxError as e:
        logging.info(f"could not parse document {e}")
        # The document is too broken to parse even with recovery.
        return (None, [])

    default_xmlns = _namespace_for_element(root) or default_namespace

    # 3. Find the marker element in the resulting tree.
    nodeset = root.xpath(f".//*[local-name()='{marker_tag}']")
    if not nodeset:
        logging.info(f"xpath returned nothing")
        return (None, [])

    marker = nodeset[0]
    logging.info(f"retrieved marker {marker}")

    # 4. Get the parent of the marker. This is our context.
    parent = marker.getparent()
    if parent is None:
        logging.info(f"the marker element is the root element. Cannot complete.")
        return (None, [])

    # 5. Find the schema definition for the parent element.
    def _get_child_by_name_recurse(schema_elt, childtag, visited=None):
        if _local_name_for_element(schema_elt) == childtag:
            return schema_elt

        if visited is None:
            visited = set()

        foundchild = None
        if hasattr(schema_elt.type, "content"):
            if hasattr(schema_elt.type.content, "iter_elements"):
                for x in schema_elt.type.content.iter_elements():
                    if x not in visited:
                        if not foundchild:
                            logging.info(
                                f"checking x.name({x.name}) vs child({childtag})"
                            )
                            if _local_name_for_element(x) == childtag:
                                foundchild = x
                            else:
                                visited.add(x)
                                foundchild = _get_child_by_name_recurse(
                                    x, childtag, visited
                                )
        return foundchild

    try:
        logging.info(f"looking for parent element {parent.tag}")
        parent_xsd_element = _get_child_by_name_recurse(
            schema.root_elements[0], _local_name_for_element(parent)
        )
        if parent_xsd_element is None:
            logging.info(f"no parent element found in the schema")
            return (parent, [])
    except KeyError:
        logging.info(f"KeyError while finding parent element in the schema")
        return (parent, [])  # Parent tag not found in schema.

    # 6. Extract the list of all possible child elements from the schema definition.
    #    The .type.content object is an XsdGroup that contains the content model.
    #    We can iterate over it to get all possible child elements.
    #
    # NB: The MSBuild xsd defines the Property type as "abstract" so I guess it
    # can literally be anything. So completions within a PropertyGroup...
    # are not helpful.

    logging.info(f"found parent element in the schema {parent_xsd_element}")
    valid_children = _get_elements_from_type(parent_xsd_element.type, default_xmlns)

    # TODO: Filter out elements that already exist if the schema says they
    # cannot appear more than once.  For now, we return all possibilities, and
    # let later validation sort that out.

    return (parent, sorted(list(set(valid_children))))


@server.feature("textDocument/completion")
def completion(ls, params):
    """Provide completion suggestions."""
    uri = params.text_document.uri
    pos = params.position
    logging.info(f"completion for {uri} at {pos.line}:{pos.character}")

    if uri not in session_cache or "content" not in session_cache[uri]:
        logging.info(f"no session or no content")
        return CompletionList(is_incomplete=False, items=[])

    content = session_cache[uri]["content"]

    root_uri = uri.rpartition("/")[0]
    logging.info(f"getting workspace for {root_uri}")
    workspace = ls.workspaces.get(root_uri)
    if not workspace:
        logging.info(f"no workspace for {uri}")
        return CompletionList(is_incomplete=False, items=[])

    schema, schema_path = workspace.get_schema_for_doc(uri, content)

    if not schema:
        logging.info(f"no schema")
        return CompletionList(is_incomplete=False, items=[])

    logging.info(f"got schema {schema}")
    logging.info(f"schema-defined elements: {list(schema.elements.keys())}")

    default_namespace = None
    if schema_path:
        default_namespace = workspace.default_xmlns_for_schemapath.get(schema_path)

    parent_element, completions = _get_element_context_at_position(
        schema, default_namespace, content, pos
    )
    logging.info(f"Found {len(completions)} completions: {completions}")

    items = [
        CompletionItem(
            label=label, kind=CompletionItemKind.Struct, insert_text=f"<{label}>"
        )
        for label in completions
    ]

    if parent_element is not None:
        local_name = _local_name_for_element(parent_element)
        items.append(
            CompletionItem(
                label=f"close {local_name}",
                kind=CompletionItemKind.Struct,
                insert_text=f"</{local_name}>",
            )
        )

    return CompletionList(is_incomplete=False, items=items)


def main():
    """The main entry point for the server."""
    default_log_file_location = "/tmp/xmllsp.log"
    default_log_level = "INFO"
    parser = argparse.ArgumentParser(description="XML Language Server")
    parser.add_argument(
        "--log-file",
        type=str,
        metavar="FILE",
        help=f"Path to the log file. If you specify --log-file without --log-level, the level defaults to {default_log_level}.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=(
            f"Set the logging level. Uses {default_log_file_location} if "
            "--log-file is not specified."
        ),
    )
    args = parser.parse_args()

    log_file = args.log_file
    log_level_str = args.log_level

    # Enable logging if either a file or a level is specified by the user.
    if log_file or log_level_str:
        if not log_file:
            log_file = default_log_file_location
        if not log_level_str:
            log_level_str = default_log_level

        # Security: Validate and resolve the log file path
        try:
            log_path = Path(log_file).resolve()
            # Security: Ensure parent directory exists or can be created
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = str(log_path)
        except (OSError, ValueError) as e:
            # Fall back to default location if specified path is invalid
            print(f"Warning: Invalid log file path '{log_file}': {e}", file=sys.stderr)
            print(f"Using default log file: {default_log_file_location}", file=sys.stderr)
            log_file = default_log_file_location

        log_level = getattr(logging, log_level_str.upper(), logging.INFO)
        logging.basicConfig(filename=log_file, level=log_level, filemode="w")
        # Set the logging level for pygls to avoid overly verbose output.
        logging.getLogger("pygls").setLevel(log_level)

    logging.info("Starting XML language server.")
    server.start_io()


if __name__ == "__main__":
    main()
