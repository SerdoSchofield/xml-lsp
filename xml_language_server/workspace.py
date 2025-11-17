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
import fnmatch
import json
import logging
import os
from pathlib import Path

import lxml.etree as ET
import xmlschema
from pygls.uris import to_fs_path


def _find_schemapath_by_rootelement(xml_doc, searchpaths):
    """Finds schema file path based on root element name."""
    root_element_name = xml_doc.tag
    
    # Extract local name from namespaced element names
    if "}" in root_element_name:
        root_element_name = root_element_name.split("}", 1)[1]
    
    # Security: Validate the root element name to prevent path traversal
    # Only allow alphanumeric characters, underscores, hyphens, and dots
    if not root_element_name or not all(c.isalnum() or c in "._-" for c in root_element_name):
        logging.warning(f"Invalid root element name: {root_element_name}")
        return None
    
    # Security: Prevent path traversal attempts
    if ".." in root_element_name or "/" in root_element_name or "\\" in root_element_name:
        logging.warning(f"Potential path traversal attempt in root element: {root_element_name}")
        return None
    
    for searchpath in searchpaths:
        try:
            # Resolve both paths to their canonical absolute paths
            search_dir = Path(searchpath).resolve()
            schema_file = (search_dir / f"{root_element_name}.xsd").resolve()
            
            # Security: Ensure the resolved path is still within the search directory
            if not str(schema_file).startswith(str(search_dir)):
                logging.warning(f"Path traversal attempt detected: {schema_file}")
                continue
                
            if schema_file.exists():
                schema_path = str(schema_file)
                logging.info(f"Found schema for {root_element_name} at {schema_path}")
                return schema_path
        except (OSError, ValueError) as e:
            logging.error(f"Error resolving path in {searchpath}: {e}")
            continue
    
    return None


def _validate_schema_path(schema_path):
    """
    Validates a schema file path to ensure it's safe to use.
    Returns the resolved absolute path if valid, None otherwise.
    
    Security: Prevents path traversal and ensures the file exists.
    """
    if not schema_path or not isinstance(schema_path, str):
        return None
    
    try:
        schema_file = Path(schema_path).resolve()
        
        # Security: Ensure the path exists and is a file
        if not schema_file.exists() or not schema_file.is_file():
            return None
        
        # Security: Ensure it has a valid extension
        if schema_file.suffix.lower() not in ['.xsd', '.xml']:
            logging.warning(f"Invalid schema file extension: {schema_file}")
            return None
            
        return str(schema_file)
    except (OSError, ValueError) as e:
        logging.error(f"Error validating schema path {schema_path}: {e}")
        return None


def _find_schemapath_by_location_hint(xml_doc, map_path, doc_uri=None):
    """Finds schema file path based on xsi:schemaLocation hint."""
    XSI = "http://www.w3.org/2001/XMLSchema-instance"
    schemaLocation_attr = f"{{{XSI}}}schemaLocation"
    attr_value = xml_doc.attrib.get(schemaLocation_attr)
    if not attr_value:
        return None

    hints = attr_value.split()
    
    # If doc_uri is provided, try to resolve file: URIs relative to document location
    if doc_uri:
        try:
            doc_path = Path(to_fs_path(doc_uri)).resolve()
            doc_dir = doc_path.parent
            
            for hint in hints:
                # Check if hint starts with "file:"
                if hint.startswith("file:"):
                    # Strip the "file:" prefix
                    file_path = hint[5:]  # Remove "file:" prefix
                    
                    # Security: Basic validation of the file path
                    if not file_path:
                        continue
                    
                    try:
                        # Resolve the path relative to the document directory
                        if Path(file_path).is_absolute():
                            schema_file = Path(file_path).resolve()
                        else:
                            schema_file = (doc_dir / file_path).resolve()
                        
                        # Security: Validate the resolved path
                        validated_path = _validate_schema_path(str(schema_file))
                        if validated_path and Path(validated_path).exists():
                            logging.info(
                                f"Found schema from file: URI '{hint}' at {validated_path}"
                            )
                            return validated_path
                    except (OSError, ValueError) as e:
                        logging.error(f"Error resolving file: URI '{hint}': {e}")
                        continue
        except Exception as e:
            logging.error(f"Error processing file: URIs for document {doc_uri}: {e}")
    
    try:
        map_file = Path(map_path).resolve()
        if not map_file.exists():
            return None
            
        with open(map_file, "r", encoding="utf-8") as f:
            schema_map = json.load(f)

        # Security: Ensure schema_map is a dictionary
        if not isinstance(schema_map, dict):
            logging.error(f"Invalid schema map format in {map_path}")
            return None

        searchpath = map_file.parent

        for hint in hints:
            if hint in schema_map:
                schema_filename = schema_map[hint]
                
                # Security: Validate schema_filename is a string
                if not isinstance(schema_filename, str):
                    logging.warning(f"Invalid schema filename type for hint {hint}")
                    continue
                
                # Security: Prevent path traversal in schema filename
                if ".." in schema_filename or "/" in schema_filename or "\\" in schema_filename:
                    logging.warning(f"Potential path traversal in schema filename: {schema_filename}")
                    continue
                
                try:
                    schema_file = (searchpath / schema_filename).resolve()
                    
                    # Security: Ensure the resolved path is still within the search directory
                    if not str(schema_file).startswith(str(searchpath)):
                        logging.warning(f"Path traversal attempt detected: {schema_file}")
                        continue
                    
                    if schema_file.exists():
                        schema_path = str(schema_file)
                        logging.info(
                            f"Found schema hint '{hint}' pointing to {schema_path}"
                        )
                        return schema_path
                except (OSError, ValueError) as e:
                    logging.error(f"Error resolving schema path: {e}")
                    continue
    except Exception as e:
        logging.error(f"Error processing schema_map.json at {map_path}: {e}")
    
    return None


class Workspace:
    """Represents a single workspace folder."""

    def __init__(self, root_uri, initialization_options):
        self.root_uri = root_uri
        self.options = initialization_options
        self.schemas_for_xsdpath = {}  # schemapath -> schema object
        self.schemapaths_for_uri = {}  # doc uri -> schemapath
        self.default_xmlns_for_schemapath = {}  # schemapath -> default_xmlns

    def get_schema_for_doc(self, uri, content):
        """
        Finds, loads, and caches the schema for a given document.

        Updates the workspace state with the results of the schema search.

        Returns:
            A tuple of (xmlschema.XMLSchema, str) or (None, None).
        """
        parser = ET.XMLParser(recover=True)
        try:
            xml_doc = ET.fromstring(content.encode("utf-8"), parser)
        except ET.XMLSyntaxError as e:
            logging.info(f"could not parse document {e}")
            return None, None  # Invalid XML, can't determine schema

        # Check cache first
        if uri in self.schemapaths_for_uri:
            schema_path = self.schemapaths_for_uri[uri]
            if schema_path in self.schemas_for_xsdpath:
                schema = self.schemas_for_xsdpath[schema_path]
                return schema, schema_path

        locators = self.options.get("schemaLocators", [])
        if not locators:
            logging.warning("No schema locators specified.")

        for locator in locators:
            schema_path = None
            use_default_namespace = None
            if locator.get("rootElement") and locator.get("searchPaths"):
                logging.info("Trying locator rootElement")
                schema_path = _find_schemapath_by_rootelement(
                    xml_doc, locator.get("searchPaths")
                )
            elif locator.get("locationHint"):
                logging.info("Trying locator locationHint")
                schema_path = _find_schemapath_by_location_hint(
                    xml_doc, locator.get("locationHint"), uri
                )
            elif "patterns" in locator:
                logging.info("Trying locator patterns")
                patterns = locator.get("patterns", [])
                doc_filename = os.path.basename(to_fs_path(uri))
                for p in patterns:
                    pattern = p.get("pattern")
                    if pattern and fnmatch.fnmatch(doc_filename, pattern):
                        raw_schema_path = p.get("path")
                        if raw_schema_path:
                            # Security: Validate the schema path
                            schema_path = _validate_schema_path(raw_schema_path)
                            if schema_path:
                                logging.info(
                                    f"Pattern '{pattern}' matched '{doc_filename}',"
                                    f" using schema '{schema_path}'"
                                )
                                use_default_namespace = p.get("useDefaultNamespace")
                                break
                            else:
                                logging.warning(f"Invalid schema path from pattern: {raw_schema_path}")
                                schema_path = None
            else:
                logging.warning(f"Unrecognized locator type {locator}")

            if schema_path:
                try:
                    xsd_root = ET.parse(schema_path).getroot()
                    schema = xmlschema.XMLSchema11(schema_path)
                    logging.info(f"Successfully loaded schema {schema_path}")

                    # Stash it
                    self.schemas_for_xsdpath[schema_path] = schema
                    self.schemapaths_for_uri[uri] = schema_path

                    # If the useDefaultNamespace flag has been set on this
                    # locator, get the targetNamespace for this schema and stash
                    # it. Purpose: to handle cases where people want to ignore
                    # xmlns with documents.  Sounds amateur, but there's a big
                    # example: Microsoft with their MSBuild project files. The
                    # xml uses no namespace, but the schema are in the msbuild
                    # namespace. We CAN use xmlschema to validate such
                    # documents, basically telling it "assume this namespace as
                    # you validate, even though it's not declared in the
                    # document." For that we need to know/retain the target
                    # namespace.
                    #
                    # This useDefaultNamespace works only with the patterns locator.
                    if use_default_namespace:
                        target_namespace = xsd_root.get("targetNamespace")
                        if target_namespace:
                            self.default_xmlns_for_schemapath[schema_path] = (
                                target_namespace
                            )

                    return schema, schema_path
                except Exception as e:
                    logging.error(f"Failed to load schema {schema_path}: {e}")
                    return None, None

        logging.warning(f"No schema located for {uri}")
        return None, None

    def release_document(self, uri):
        """Releases a document and cleans up unused schemas from the cache."""
        logging.info(f"Releasing document: {uri}")
        if uri in self.schemapaths_for_uri:
            schema_path = self.schemapaths_for_uri.pop(uri)
            logging.info(
                f"Document {uri} closed; schemapath {schema_path} no longer used by it."
            )

            # Check if any other open documents use this schema
            if schema_path not in self.schemapaths_for_uri.values():
                logging.info(
                    f"Schema {schema_path} is no longer used by any open document."
                )
                if schema_path in self.schemas_for_xsdpath:
                    self.schemas_for_xsdpath.pop(schema_path)
                    logging.info(f"Removed schema {schema_path} from cache.")
                if schema_path in self.default_xmlns_for_schemapath:
                    self.default_xmlns_for_schemapath.pop(schema_path, None)
