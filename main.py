import argparse
import copy
import json
import logging
import os
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

LOGGER = logging.getLogger(__file__.split("/")[-1])
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)


def find_files_with_extension(folder_path: str, extension: str) -> List[str]:
    """
    Find all full paths to files with a specific file extension in the folder_path and its subfolders.

    :param folder_path: The path to the folder to search in.
    :param extension: The file extension to search for (e.g., '.txt', '.py').

    :returns: A list of full paths to files with the specified file extension.

    :raises: ValueError: If the folder_path does not exist or is not a directory.

    ELI5:
        This function takes a folder path and a file extension as input.
        It finds all the files in the specified folder (including subfolders) that have the given extension.
        Then, it returns a list of the full paths to those files.
    """
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        raise ValueError("The folder_path must be an existing directory.")

    files_with_extension = []

    def search_files(current_folder: str):
        """
        Help function that recursively searches for files with the given extension.

        :param current_folder: The current folder being searched.
        :returns: None. The function populates the files_with_extension list.

        ELI5:
            This helper function searches for files with the given extension in a folder.
            It looks at all the files and folders within the current folder.
            If it finds a file with the desired extension, it adds its full path to
            the files_with_extension list.
            If it finds a subfolder, it calls itself recursively to search within that subfolder.
        """
        for item in os.listdir(current_folder):
            item_path = os.path.join(current_folder, item)
            if os.path.isfile(item_path) and item_path.endswith(extension):
                files_with_extension.append(item_path)
            elif os.path.isdir(item_path):
                search_files(item_path)

    search_files(folder_path)
    if not files_with_extension:
        LOGGER.warning(f"No {extension} files found at path: {folder_path}")
    return files_with_extension


class SchemaRefType(Enum):
    """
    Define the type of link found in the schema file.

    :prop INTERNAL: The sub schema exists inside its own OAS file
    :prop EXTERNAL: The sub schema exists in an external OAS file and is the only
    schema under the default internal OAS file path: [components][schemas][schema_name]
    :prop EXTERNAL_INTERNAL: The sub schema exists in an external file
    at a specific location NOT the default internal OAS file
    path: [components][schemas][schema_name]
    """

    INTERNAL = 1
    EXTERNAL = 2
    EXTERNAL_INTERNAL = 3


def evaluate_ref(ref_value: str) -> SchemaRefType:
    """
    Evaluate if the $ref points internally or to external JSON schema.

    :param ref_value: $ref value from an openapi json schema
    """
    if not isinstance(ref_value, str):
        raise TypeError(f"{ref_value} is not a string.")

    if ref_value[0] == "." and "#" in ref_value:
        return SchemaRefType.EXTERNAL_INTERNAL
    elif ref_value[0] == ".":
        return SchemaRefType.EXTERNAL
    elif ref_value[0] == "#":
        return SchemaRefType.INTERNAL
    else:
        raise ValueError(f"{ref_value} cannot be evaluated")


def walk_dictionary(dictionary: Dict[str, Any], target_key: str) -> Tuple[str, Any]:
    """
    Walk through every key in a dictionary.

    Including nested levels of nesting, and compares the lowercase key with a provided target key.
    If a matching key (key == target key) is found it is returned along with its value.

    :param dictionary (dict): The dictionary to be traversed.
    :param target_key (str): The target key to compare the lowercase keys with.

    :returns tuple: The matching key (internal path) and its corresponding value if found.
    :raises KeyError: If a matching key is not found in the dictionary
    :rasies TypeError: If input dictionary is not of type dict
    """

    def walk_dict_helper(
        dictionary: Dict[str, Any], path: str
    ) -> Union[Tuple[str, Any], None]:
        """
        Recurse helper function to walk through the dictionary.

        :param dictionary (dict): The dictionary to be traversed.

        :returns:tuple or None: The matching key and its corresponding value if found, None otherwise.

        """
        for key, value in dictionary.items():
            # Construct the current key path
            current_path = f"{path}.{key}" if path else key
            # Lowercase the current key and compare it with the initial value
            if key.lower() == target_key.lower():
                return current_path, value

            if isinstance(value, dict):
                # If the value is a nested dictionary, recursively call the helper function
                match = walk_dict_helper(value, current_path)
                if match:
                    return match

        return None

    # Check if the input is a dictionary
    if not isinstance(dictionary, dict):
        raise TypeError("Input must be a dictionary.")

    # Start walking through the dictionary
    output = walk_dict_helper(dictionary, "")

    if not output:
        raise KeyError(f"The key '{target_key}' not found in dictionary")

    return output


def load_openapi_spec(
    spec_path: Union[Path, str], schema_location: Union[None, str] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Extract JSON Schema from OAS JSON file.

    :param schema_location: Which property within the OAS JSON file holds the
    JSON schema of the MongoDB collection.

    :returns: Extracted JSON Schema (dict) or None, OAS Spec (dict)
    """
    open_api_spec_file = open(spec_path)
    open_api_spec = json.load(open_api_spec_file)
    if schema_location:
        # Search for matching sub schema location key
        while True:
            """
            Continuously prompts the user for an alternative key if a KeyError is raised.

            This loop allows the user to provide an alternative key to retry the dictionary search
            in case a KeyError is raised. The user is prompted to enter an alternative key,
            and the search is performed again with the updated schema_location. The loop continues
            until a valid key is provided or the user chooses to exit by not entering any key.
            """
            try:
                path_found, json_schema = walk_dictionary(
                    dictionary=open_api_spec, target_key=schema_location
                )
                return json_schema, open_api_spec
            except KeyError as e:
                LOGGER.error(f"{e} at path: {spec_path}")
                LOGGER.debug(open_api_spec)
                alternative_key = input("Please enter an alternative key: ")
                if alternative_key:
                    schema_location = alternative_key
                else:
                    break
    else:
        LOGGER.debug("Schema location not defined, returning entire OAS Spec.")
        return None, open_api_spec


def walk_references(schema: Dict[str, Any]) -> List[str]:
    # ! todo we should test that this works with OPEN API Specs at the end of the day
    """
    Recurse through a JSON schema & extract $ref values.

    We mainly use this simply to check if references still exist
    not to manage the resolving of them as some exist within
    lists.
    """
    output = []
    for key, value in schema.items():
        if key == "$ref":
            output.append(value)
        elif isinstance(value, dict):
            output += walk_references(value)
        elif isinstance(value, list):
            if all(isinstance(each, dict) for each in value):
                for each in value:
                    output += walk_references(each)
    return output


def get_path_relative_to(pointing_to: Path, current_location: Path) -> Path:
    """
    Resolve the relative path to arbitrary one.

    :param relative: Relative path to target
    :param target: Path to resolve to
    """
    return (current_location / pointing_to).resolve(strict=False)


def find_sub_schema_by_ref_value(
    ref_schemas: List[Dict[str, Any]], ref_value: str
) -> Union[Dict[str, Any], None]:
    """
    Return sub_schema value where $ref == ref_value.

    This is used mainly for extracting sub_schemas that are going
    to be merged into the main schema.

    Given ref_schemas:

    ```
    [
        {
            "$ref": "some_ref_string",
            "sub_schema: { "name": "John Doe" },
        }
    ]
    ```

    >>> find_sub_schema_by_ref_value(ref_schemas, "some_ref_string")
    >>> { "name": "John Doe" } #Output
    """
    for each in ref_schemas:
        if each["$ref"] == ref_value:
            return each["sub_schema"]
    return None


def cache_json_properties(arb_object):
    """
    Extract properties we want to keep.

    When merging dicts we want to make sure we hold on
    to previous properties .e.g nullable, title etc
    """
    # TODO "x-virtual" means the value might not exist until run time from the source MongoDB
    fields_to_keep = ["nullable", "title", "description", "x-virtual", "format"]
    cached = {}
    for field in fields_to_keep:
        value_found = None
        try:
            _, value_found = walk_dictionary(arb_object, field)
        except KeyError:
            continue
        if value_found:
            cached.update({field: value_found})
    if cached:
        return cached
    return None


def walk_and_merge_references(
    arb_object: Dict[str, Any],
    ref_schemas: List[Dict[str, Any]],
    file_path,
    keys_to_keep: Optional[List[str]] = None,
) -> Any:
    """
    Replace $refs with provided sub schemas.

    ref_schemas should contain a list of dicts with a $ref and sub_schema key
    tbe `$ref` is used to match against a `$ref` in the target schema, if a match
    is found then the value in the target schema is replaced with the value of sub_schema
    coming from the reference schema dict.
    """
    if "fee.interface" in file_path:
        LOGGER.setLevel(level=logging.WARNING)
    if isinstance(arb_object, dict):
        """
        So if its an objects such as:
            {
                "$ref": "../enums/unit-of-measure-code.enum.json#/components/schemas/VolumeUnit"
            }
        """
        # logging.warning(arb_object)
        for key, value in arb_object.copy().items():
            if key == "$ref":
                ref_schema = find_sub_schema_by_ref_value(
                    ref_schemas=ref_schemas, ref_value=value
                )
                if ref_schema and type(ref_schema) == dict:
                    cached_fields = cache_json_properties(
                        arb_object=copy.deepcopy(arb_object)
                    )

                    kept_keys = {}
                    if keys_to_keep:
                        for key_to_keep in keys_to_keep:
                            try:
                                kept_keys.update(copy.deepcopy(arb_object[key_to_keep]))
                            except KeyError:
                                LOGGER.error(f"Cannot keep key: {key_to_keep}")
                                pass
                    arb_object.clear()
                    arb_object.update(ref_schema)
                    if len(kept_keys.keys()) > 0:
                        arb_object.update(kept_keys)

                    if cached_fields:
                        arb_object.update(cached_fields)
            elif isinstance(value, dict):
                walk_and_merge_references(
                    value, ref_schemas, file_path, ["i6RefCollectionName"]
                )
            elif isinstance(value, list):
                for each in value:
                    walk_and_merge_references(
                        each, ref_schemas, file_path, ["i6RefCollectionName"]
                    )
    return arb_object


def extract_json_schema_from_oas(arb_object: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract the actual schema.

    Sometimes the sub schema will have its fields
    nested in a sub-field 'properties' other times
    it does not. This function accounts for this by first
    checking if the properties sub field exists.

    This extracts JUST the JSON schema portion of an Open
    API Spec. Assuming it sits in the 'properties' field.
    """
    top_level_keys = arb_object.keys()
    if len(top_level_keys) and "properties" in top_level_keys:
        return arb_object["properties"]
    else:
        return arb_object


def save_dict_to_json(dictionary: Dict[str, Any], file_path: str) -> None:
    with open(file_path, "w") as file:
        json.dump(dictionary, file, indent=2)


def _is_targeting_list_item(keys_from_ref_string: List[str]) -> Union[int, None]:
    """
    Check if targeting a list item.

    The parent function takes a reference string ref_string and a dictionary
    data_dict as inputs.

    The reference string is expected to be in the format inspired by JSON $ref syntax and
    specifies the path to the desired value in the dictionary.

    It starts with # and uses / to separate the keys. If targeting an index within a list,
    the last character of the reference string is expected to be an integer.

    In order to handle the scenario where the reference string points to a list element,
    the code checks if the last part of the reference string (i.e., keys[-1]) is an integer.

    If keys[-1] can be successfully converted to an integer, it means that the reference is targeting a
    specific element within a list, and the index specified by the integer is used to retrieve the value
    from the list in the data dictionary.
    """
    list_index = None
    try:
        list_index = int(keys_from_ref_string[-1])
        LOGGER.debug("Searching for a list item")
        # If the last element of the keys list is an integer
        # we need to remove this element from the keys list to access the correct path-
        # -for the dictionary traversal.
        keys_from_ref_string.pop(-1)
        return list_index
    except (IndexError, ValueError):
        LOGGER.debug("No references to list index found assuming not searching a list.")
        return None


def fetch_value_from_ref(ref_string: str, data_dict: dict):
    """
    Fetch the value from a dictionary based on a reference string inspired by JSON $ref syntax.


    :param `ref_string`:
        The reference string specifying the path to the desired value in the dictionary.
        It should start with `#` and use `/` to separate the keys.
        If targeting an index within a list the last character is expected to be an `int`

    :param `data_dict`:
        The dictionary to search.

    :returns `Arbitrary object`:
        The value corresponding to the reference string, or None if not found.

    :raises: ValueError
        If the reference string does not start with '#' or if it cannot be parsed.

    ELI5:
    ----
    This function takes a reference string and a dictionary as input.
    The reference string is in the format inspired by JSON $ref syntax.
    It specifies the path to a desired value within the dictionary.
    The function searches for the value based on the reference string and returns it.

    Example:
    -------
    >>> my_dict = {"name": "chachi", "traits": {"humour": "lots"}}
    >>> ref_string = "#/traits/humour"
    >>> value = fetch_value_from_ref(ref_string, my_dict)
    >>> print(value)
    >>> lots

    """
    pattern = r"[^a-zA-Z0-9\s]"  # Regular expression pattern to match non-alphanumeric characters
    if type(ref_string) == str and not ref_string.startswith("#"):
        raise ValueError("Invalid reference string. It should start with '#'.")
    elif type(ref_string) == int:
        raise ValueError("Invalid reference it should be a String not and Int")
    elif type(ref_string) == str and bool(re.search(pattern, ref_string[-1])):
        raise ValueError(
            f"Invalid reference last character {ref_string[-1]} is special."
        )

    # Extract the keys from the reference string
    keys = ref_string[2:].split("/")
    current_output = data_dict

    list_index = _is_targeting_list_item(keys_from_ref_string=keys)

    # Traverse the dictionary using the keys
    for key in keys:
        if type(current_output) == list and list_index:
            pass
        else:
            current_output = current_output[key]

    # Return the value corresponding to the reference string
    if "/enum/" in ref_string.lower() and list_index is not None:
        LOGGER.debug("Searching for a specific enum value")
        LOGGER.debug(current_output)  # Should be a list at this point
        if not type(current_output) == list:
            raise TypeError(f"Expected enum to be a list but got: {current_output}")
        enum_type = "string"  # Default to string
        if all(type(x) == int for x in current_output):
            enum_type = "number"
        return {"enum": [current_output[list_index]], "type": enum_type}
    elif list_index is not None:
        return current_output[list_index]
    return current_output


def resolve_references(target_path: str) -> None:
    """
    We only process top level files at the target path.

    :param target_path: Path to OpenAPI specs containing JSON schemas
    :param prefix: Absolute path to output location
    """
    # Get all .json file names in target path
    json_file_paths = find_files_with_extension(
        folder_path=target_path, extension=".json"
    )
    # Defer until the schema being referenced has itself been resolved
    deferred_files = [each for each in json_file_paths]

    # Handle each at a time
    while deferred_files:
        for file_path in deferred_files:
            LOGGER.info(f"Analysing {file_path}")

            source_oas_spec_file = open(file_path)
            source_oas_spec = json.load(source_oas_spec_file)

            # Find out if this has $refs that need to be resolved
            refs_found: List[str] = walk_references(source_oas_spec)
            # If zero refs were found then there's no need to process it
            # it can now be removed from the 'deferred_files' array
            if not refs_found:
                index = deferred_files.index(file_path)
                deferred_files.pop(index)
            else:
                # If refs were found we first try to solve them
                sub_schemas = (
                    []
                )  # Container for sub schemas that we fetch for merging in
                # For each reference find out if its internal or external
                for ref_link in refs_found:
                    if evaluate_ref(ref_value=ref_link) == SchemaRefType.INTERNAL:
                        LOGGER.debug(ref_link)
                        sub_schema = fetch_value_from_ref(
                            ref_string=ref_link, data_dict=source_oas_spec
                        )
                        LOGGER.debug(sub_schema)
                        sub_schemas.append(
                            {
                                "$ref": ref_link,
                                "sub_schema": sub_schema,
                            }
                        )
                    elif (
                        evaluate_ref(ref_value=ref_link)
                        == SchemaRefType.EXTERNAL_INTERNAL
                    ):
                        # Grab just the file path portion of the external ref link
                        # we can use it to find out the absolute path of the file being referenced...
                        referenced_oas_relative_path = ref_link.split("#")[0]
                        # From where the current file we are analysing to where the ref file is...
                        referenced_oas_absolute_path = str(
                            get_path_relative_to(
                                pointing_to=Path(referenced_oas_relative_path),
                                current_location=Path(file_path).resolve().parent,
                            )
                        )

                        # Now we can dig out the referenced schema from external file
                        sub_schema_location_in_oas = f'#{ref_link.split("#")[-1]}'
                        LOGGER.debug(referenced_oas_relative_path)
                        LOGGER.debug(sub_schema_location_in_oas)

                        oas_spec_file = open(referenced_oas_absolute_path)
                        oas_spec = json.load(oas_spec_file)

                        sub_schema = fetch_value_from_ref(
                            ref_string=sub_schema_location_in_oas,
                            data_dict=oas_spec,
                        )
                        LOGGER.debug(sub_schema)
                        sub_schema = extract_json_schema_from_oas(arb_object=oas_spec)
                        # check if subschema has unresolved refs
                        has_refs = walk_references(schema=sub_schema)
                        if has_refs:
                            LOGGER.debug(f"{file_path} has been deferred")
                            break
                        else:
                            sub_schemas.append(
                                {
                                    "$ref": ref_link,
                                    "sub_schema": fetch_value_from_ref(
                                        ref_string=sub_schema_location_in_oas,
                                        data_dict=sub_schema,
                                    ),
                                }
                            )
                if sub_schemas:
                    LOGGER.debug(sub_schemas)
                    resolved = walk_and_merge_references(
                        arb_object=source_oas_spec,
                        ref_schemas=sub_schemas,
                        file_path=file_path,
                        keys_to_keep=["i6RefCollectionName"],
                    )

                    # Replace original file with resolved version
                    save_dict_to_json(
                        dictionary=resolved,
                        file_path=f"{file_path}",
                    )

                    # check if there are still unresolved refs
                    still_refs_found: List[str] = walk_references(oas_spec)
                    if not still_refs_found:
                        index = deferred_files.index(file_path)
                        deferred_files.pop(index)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLI Tool")
    parser.add_argument(
        "-t",
        "--target_path",
        help="Path containing the Open Api Spec files/JSON Schemas",
        required=True,
    )
    parser.add_argument(
        "-ll",
        "--logging_level",
        help="One of [info, warning, debug or error]",
        required=False,
    )
    # !TODO add option to open and save all JSON first so it orders it the same way as the script
    # TODO ... this makes it easier to see the diff when the schemas has been updated.
    parser.add_argument(
        "-rst",
        "--reset_jsons",
        help="Open all and save in the Python JSON ordering.",
        required=False,
    )

    # Re save all to enable better diff checking
    # TODO add in docs that you should commit after this so diff checking actually works

    args = parser.parse_args()

    # Set logging level
    if args.logging_level.lower() == "debug":
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    if args.logging_level.lower() == "info":
        logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    if args.logging_level.lower() == "warning":
        logging.basicConfig(stream=sys.stdout, level=logging.WARN)
    if args.logging_level.lower() == "error":
        logging.basicConfig(stream=sys.stdout, level=logging.ERROR)

    if args.reset_jsons:
        # Get all .json file names in target path
        json_file_paths = find_files_with_extension(
            folder_path=args.target_path, extension=".json"
        )
        for file_path in json_file_paths:
            data_file = open(file_path)
            data = json.load(data_file)
            save_dict_to_json(dictionary=data, file_path=file_path)
    else:
        resolve_references(args.target_path)
