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

import lxml.etree as ET
import xmlschema
from pygls.uris import to_fs_path


def _find_schemapath_by_rootelement(xml_doc, searchpaths):
    """Finds schema file path based on root element name."""
    root_element_name = xml_doc.tag
    for searchpath in searchpaths:
        schema_path = os.path.join(searchpath, f"{root_element_name}.xsd")
        if os.path.exists(schema_path):
            logging.info(f"Found schema for {root_element_name} at {schema_path}")
            return schema_path
    return None


def _find_schemapath_by_location_hint(xml_doc, map_path):
    """Finds schema file path based on xsi:schemaLocation hint."""
    XSI = "http://www.w3.org/2001/XMLSchema-instance"
    schemaLocation_attr = f"{{{XSI}}}schemaLocation"
    attr_value = xml_doc.attrib.get(schemaLocation_attr)
    if not attr_value:
        return None

    hints = attr_value.split()
    if os.path.exists(map_path):
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                schema_map = json.load(f)

            searchpath = os.path.dirname(map_path)

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
                    xml_doc, locator.get("locationHint")
                )
            elif "patterns" in locator:
                logging.info("Trying locator patterns")
                patterns = locator.get("patterns", [])
                doc_filename = os.path.basename(to_fs_path(uri))
                for p in patterns:
                    pattern = p.get("pattern")
                    if pattern and fnmatch.fnmatch(doc_filename, pattern):
                        schema_path = p.get("path")
                        if schema_path:
                            logging.info(
                                f"Pattern '{pattern}' matched '{doc_filename}',"
                                f" using schema '{schema_path}'"
                            )
                            use_default_namespace = p.get("useDefaultNamespace")
                            break
            else:
                logging.warning(f"Unrecognized locator type {locator}")

            if schema_path:
                try:
                    xsd_root = ET.parse(schema_path).getroot()
                    target_namespace = xsd_root.get("targetNamespace")
                    schema = xmlschema.XMLSchema11(schema_path)
                    logging.info(f"Successfully loaded schema {schema_path}")

                    # Stash it
                    self.schemas_for_xsdpath[schema_path] = schema
                    self.schemapaths_for_uri[uri] = schema_path

                    if target_namespace and use_default_namespace:
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
