import json
import logging
import os
import re
import threading

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

# Configure logging to a file for debugging.
# This is useful as stdout is used for LSP communication.
logging.basicConfig(
    filename="/tmp/xml-language-server.log", level=logging.DEBUG, filemode="w"
)

server = LanguageServer("xml-language-server", "v0.2")
server.workspaces = {}


# Cache for storing document-specific sessions
# Sessions expire after 180 seconds of inactivity
session_cache = TTLCache(maxsize=128, ttl=180)


@server.feature("initialize")
def initialize(ls, params):
    """Server is initialized."""
    logging.info("XML Language Server initialized.")

    initialization_options = params.initialization_options or {}
    root_uri = params.root_uri

    if root_uri:
        logging.info(f"Workspace root: {root_uri}")
        ls.workspaces[root_uri] = {
            "options": initialization_options,
            "schemas": {},
            "roots": {},
        }

    return None


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


def _find_schema_path_by_rootelement(xml_doc, searchpaths):
    """Finds schema file path based on root element name."""
    root_element_name = xml_doc.tag
    for searchpath in searchpaths:
        schema_path = os.path.join(searchpath, f"{root_element_name}.xsd")
        if os.path.exists(schema_path):
            logging.info(f"Found schema for {root_element_name} at {schema_path}")
            return schema_path
    return None


def _find_schema_path_by_location_hint(xml_doc, searchpaths):
    """Finds schema file path based on xsi:schemaLocation hint."""
    XSI = "http://www.w3.org/2001/XMLSchema-instance"
    schemaLocation_attr = f"{{{XSI}}}schemaLocation"
    attr_value = xml_doc.attrib.get(schemaLocation_attr)
    if not attr_value:
        return None

    hints = attr_value.split()
    for searchpath in searchpaths:
        map_path = os.path.join(searchpath, "schema_map.json")
        if os.path.exists(map_path):
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    schema_map = json.load(f)

                for hint in hints:
                    if hint in schema_map:
                        schema_filename = schema_map[hint]
                        schema_path = os.path.join(searchpath, schema_filename)
                        if os.path.exists(schema_path):
                            logging.info(
                                f"Found schema hint '{hint}' pointing to {schema_path}"
                            )
                            return schema_path
            except Exception as e:
                logging.error(f"Error processing schema_map.json at {map_path}: {e}")
    return None


def _get_schema_for_doc(ls, uri, content):
    """Finds and loads the schema for a given document."""
    root_uri = uri.rpartition("/")[0]
    workspace = ls.workspaces.get(root_uri)

    if not workspace:
        logging.warning(f"No workspace found for root URI: {root_uri}")
        return None

    try:
        xml_doc = ET.fromstring(content.encode("utf-8"))
    except ET.XMLSyntaxError:
        return None  # Invalid XML, can't determine schema

    root_element_name = xml_doc.tag
    workspace["roots"][uri] = root_element_name

    # Check cache first
    if root_element_name in workspace["schemas"]:
        return workspace["schemas"][root_element_name]

    options = workspace.get("options", {})
    schema_options = options.get("schema", {})
    locators = schema_options.get("locators", [])
    searchpaths = schema_options.get("searchpaths", [])

    if not locators:
        logging.warning("No schema locators specified.")

    for locator in locators:
        schema_path = None
        if locator.get("rootelement"):
            logging.info(f"Trying locator rootelement")
            schema_path = _find_schema_path_by_rootelement(xml_doc, searchpaths)
        elif locator.get("location_hint"):
            logging.info(f"Trying locator location_hint")
            schema_path = _find_schema_path_by_location_hint(xml_doc, searchpaths)

        if schema_path:
            try:
                schema = xmlschema.XMLSchema11(schema_path)
                logging.info(f"Successfully loaded schema {schema_path}")
                logging.info(f"   Defined elements: {list(schema.elements.keys())}")
                # Cache it
                workspace["schemas"][root_element_name] = schema
                return schema
            except Exception as e:
                logging.error(f"Failed to load schema {schema_path}: {e}")
                # Don't try other locators if we found a file but it failed to load
                return None

    logging.warning(f"No schema located for {uri}")
    return None


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


def _validate_document(ls, uri, content, schema):
    """Validate the document against the schema."""
    if not schema:
        logging.info("No schema available, skipping validation.")
        ls.publish_diagnostics(uri, [])
        return

    try:
        xml_doc = ET.fromstring(content.encode("utf-8"))
        validation_errors = list(schema.iter_errors(xml_doc))
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
    logging.info(f"didOpen: {uri}, creating session.")
    content = params.text_document.text
    session_cache[uri] = {"content": content}
    schema = _get_schema_for_doc(ls, uri, content)
    _validate_document(ls, uri, content, schema)


@server.feature("textDocument/didChange")
def did_change(ls, params):
    """Document changed."""
    uri = params.text_document.uri
    logging.info(f"didChange: {uri}")

    # Ensure session exists, refreshing its TTL
    if uri not in session_cache or "content" not in session_cache[uri]:
        logging.info(f"Session or content not found for {uri}, creating/re-reading.")
        try:
            with open(to_fs_path(uri), "r", encoding="utf-8") as f:
                content = f.read()
                session_cache[uri] = {"content": content}
        except Exception:
            logging.error("Could not read file %s", uri)
            return

    session = session_cache[uri]

    # infer the content
    current_content = session["content"]
    new_content = _apply_incremental_changes(current_content, params.content_changes)
    session["content"] = new_content

    # Schema lookup
    root_uri = uri.rpartition("/")[0]
    schema = None
    workspace = ls.workspaces.get(root_uri)
    if workspace:
        root_element_name = workspace["roots"].get(uri)
        if root_element_name:
            schema = workspace["schemas"].get(root_element_name)

    if not schema:
        return None

    # Immediate validation
    _validate_document(ls, uri, new_content, schema)

    # Deferred validation with a timer (debounced)
    if session.get("timer"):
        session["timer"].cancel()
        logging.info(f"Cancelled previous timer for {uri}.")

    def deferred_validation(ls_instance, doc_uri, doc_schema):
        logging.info(f"Running debounced validation for {doc_uri}.")
        if doc_uri in session_cache and "content" in session_cache[doc_uri]:
            content = session_cache[doc_uri]["content"]
            _validate_document(ls_instance, doc_uri, content, doc_schema)
        else:
            logging.warning(f"No content found for {doc_uri} in deferred validation.")

    timer = threading.Timer(4.0, deferred_validation, args=[ls, uri, schema])
    session["timer"] = timer
    timer.start()
    logging.info(f"Scheduled deferred validation for {uri}.")


@server.feature("textDocument/didSave")
def did_save(ls, params):
    """Document saved, so refresh content cache."""
    uri = params.text_document.uri
    logging.info(f"didSave: {uri}, refreshing content cache.")
    try:
        file_path = to_fs_path(uri)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        session_cache[uri] = {"content": content}
    except Exception as e:
        logging.error(f"Could not read file on save for {uri}: {e}")


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


def _get_element_context_at_position(
    schema: xmlschema.XMLSchema, xml_content: str, pos: Position
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

    default_xmlns = _namespace_for_element(root)

    # 3. Find the marker element in the resulting tree.
    # marker = root.find(f".//*[local-name()='{marker_tag}']")
    nodeset = root.xpath(f".//*[local-name()='{marker_tag}']")
    if not nodeset:
        logging.info(f"xpath returned nothing")
        return (None, [])  # Could not find the marker.

    marker = nodeset[0]
    logging.info(f"retrieved marker {marker}")

    # 4. Get the parent of the marker. This is our context.
    parent = marker.getparent()
    if parent is None:
        logging.info(f"no parent element")
        return (None, [])  # Marker is at the root, no parent.

    # 5. Find the schema definition for the parent element.
    def _get_child_by_name_recurse(schema_elt, childtag):
        if schema_elt.tag == childtag:
            return schema_elt

        foundchild = None
        if hasattr(schema_elt.type, "content"):
            if hasattr(schema_elt.type.content, "iter_elements"):
                for x in schema_elt.type.content.iter_elements():
                    if not foundchild:
                        if x.name == childtag:
                            foundchild = x
                        else:
                            foundchild = _get_child_by_name_recurse(x, childtag)
        return foundchild

    try:
        logging.info(f"looking for parent element {parent.tag}")
        parent_xsd_element = _get_child_by_name_recurse(
            schema.root_elements[0], parent.tag
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
    logging.info(f"found parent element in the schema {parent_xsd_element}")
    valid_children = []
    content_model = parent_xsd_element.type.content

    if hasattr(content_model, "iter_elements"):
        for element_node in content_model.iter_elements():
            # The 'name' of each element node is the valid tag.
            valid_children.append(element_node.name)
    else:
        logging.info(f"content_model has no iter_elements")

    # TODO: make this recurse.
    # As your schema uses extensions, we also need to check the base type's content.
    base_type = getattr(parent_xsd_element.type, "base_type", None)
    if base_type:
        if hasattr(base_type.content, "iter_elements"):
            for element_node in base_type.content.iter_elements():
                elt_xmlns = _namespace_for_element(element_node)
                if elt_xmlns == default_xmlns:
                    valid_children.append(_local_name_for_element(element_node))
                else:
                    valid_children.append(element_node.name)
        else:
            logging.info(f"base_type content has no iter_elements")
    else:
        logging.info(f"no base_type")

    # For a more advanced implementation, you would filter out elements that
    # already exist if they cannot appear more than once.
    # For now, we return all possibilities.
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
        logging.info(f"no workspace")
        return CompletionList(is_incomplete=False, items=[])

    logging.info(f"getting root element name for {uri}")
    root_element_name = workspace["roots"].get(uri)
    if not root_element_name:
        logging.info(f"no root_element_name")
        return CompletionList(is_incomplete=False, items=[])

    logging.info(f"getting schema for root element {root_element_name}")
    schema = workspace["schemas"].get(root_element_name)
    if not schema:
        logging.info(f"no schema")
        return CompletionList(is_incomplete=False, items=[])

    logging.info(f"got schema {schema}")
    logging.info(f"schema-defined elements: {list(schema.elements.keys())}")

    parent_element, completions = _get_element_context_at_position(schema, content, pos)
    logging.info(f"Found {len(completions)} completions: {completions}")

    items = [
        CompletionItem(
            label=label, kind=CompletionItemKind.Struct, insert_text=f"<{label}>"
        )
        for label in completions
    ]

    if parent_element is not None:
        items.append(
            CompletionItem(
                label=f"close {parent_element.tag}",
                kind=CompletionItemKind.Struct,
                insert_text=f"</{parent_element.tag}>",
            )
        )

    return CompletionList(is_incomplete=False, items=items)


def main():
    """The main entry point for the server."""
    logging.info("Starting XML language server.")
    server.start_io()


if __name__ == "__main__":
    main()
