import pytest

from loki_jsonschema_resolver.ref_resolver import (
    SchemaRefType,
    evaluate_ref,
    fetch_value_from_ref,
    walk_dictionary,
)


def test_evaluate_ref() -> None:
    # doesn't start with . or /
    # starts with . & includes #
    # starts with . only
    # starts with # only
    # its not a string
    refs = [
        "nota$reflink",
        "../enums/contract-customer-type.enum.json#/components/schemas/ContractCustomerType",
        "../enums/contract-customer-type.enum.json",
        "#/components/schemas/ContractCustomerType",
        420,
        "#/components/schemas/ContractCustomerType/0",  # Referencing a list
    ]

    with pytest.raises(ValueError):
        evaluate_ref(refs[0])
    assert evaluate_ref(refs[1]) == SchemaRefType.EXTERNAL_INTERNAL
    assert evaluate_ref(refs[2]) == SchemaRefType.EXTERNAL
    assert evaluate_ref(refs[3]) == SchemaRefType.INTERNAL
    with pytest.raises(TypeError):
        evaluate_ref(refs[4])
    assert evaluate_ref(refs[5]) == SchemaRefType.INTERNAL


def test_walk_dictionary():
    # Test with a simple dictionary and a matching key
    dictionary = {"key1": "value1", "key2": "value2"}
    initial_value = "KEY1"
    expected_output = ("key1", "value1")
    assert walk_dictionary(dictionary, initial_value) == expected_output

    # Test with a nested dictionary and a matching key with a valid JSON value
    nested_dict = {
        "key1": "value1",
        "key2": {
            "subkey1": "subvalue1",
            "subkey2": {"nested_key": "nested_value"},
        },
    }
    initial_value = "NESTED_KEY"
    expected_output = ("key2.subkey2.nested_key", "nested_value")
    assert walk_dictionary(nested_dict, initial_value) == expected_output

    # Test with a nested dictionary and a matching key with a non-JSON value
    nested_dict = {
        "key1": "value1",
        "key2": {"subkey1": "subvalue1", "subkey2": "non-json-value"},
    }
    initial_value = "SUBKEY2"
    expected_output = ("key2.subkey2", "non-json-value")
    assert walk_dictionary(nested_dict, initial_value) == expected_output

    # Test with a non-matching key
    dictionary = {"key1": "value1", "key2": "value2"}
    initial_value = "nonexistent"
    with pytest.raises(KeyError):
        walk_dictionary(dictionary, initial_value)

    # Test with an empty dictionary
    empty_dict = {}
    initial_value = "key"
    with pytest.raises(KeyError):
        walk_dictionary(empty_dict, initial_value)

    # Test with a non-dictionary input
    with pytest.raises(TypeError):
        walk_dictionary("not a dictionary", "key")

    # Test with nested dictionaries and numeric values
    numeric_dict = {"key1": 1, "key2": {"subkey1": 2, "subkey2": {"nested_key": 3}}}
    initial_value = "NESTED_KEY"
    expected_output = ("key2.subkey2.nested_key", 3)
    assert walk_dictionary(numeric_dict, initial_value) == expected_output


def test_fetch_value_from_ref() -> None:
    nested_dict = {
        "key1": {
            "nested_key1": {"deep_key1": {"inner_key1": "value1"}},
            "nested_key2": {"deep_key2": {"inner_key2": "value2"}},
        },
        "key2": {
            "nested_key3": {"deep_key3": {"inner_key3": ["a", "b"]}},
            "nested_key4": {
                "enum": ["KG", "MT", "LB"],
                "type": "string",
            },
        },
    }
    # ! TODO what if we are referencing a list but there are no lists in the target?
    refs = [
        "nota$reflink",
        "#/key1/nested_key2/deep_key2/inner_key2",
        "#/key1/nested_key2/deep_key2/inner_key2/&",
        "#/key2/nested_key3/deep_key3/inner_key3/0",
        "#/key2/nested_key3/deep_key3/inner_key3/7",  # index out of bounds
        420,
        "#/key2/nested_key4/enum/0",
    ]
    with pytest.raises(ValueError):
        fetch_value_from_ref(ref_string=refs[0], data_dict=nested_dict)

    assert fetch_value_from_ref(ref_string=refs[1], data_dict=nested_dict) == "value2"

    with pytest.raises(ValueError):
        fetch_value_from_ref(ref_string=refs[2], data_dict=nested_dict)

    assert fetch_value_from_ref(ref_string=refs[3], data_dict=nested_dict) == "a"

    with pytest.raises(IndexError):
        fetch_value_from_ref(ref_string=refs[4], data_dict=nested_dict)

    with pytest.raises(ValueError):
        fetch_value_from_ref(ref_string=refs[5], data_dict=nested_dict)

    assert fetch_value_from_ref(ref_string=refs[6], data_dict=nested_dict) == {
        "enum": ["KG"],
        "type": "string",
    }
