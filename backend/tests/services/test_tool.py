import json

import pytest

from app.models.mcp_server.type import ListedTool
from app.models.tool_policy.enums import PolicyEffect
from app.services import tool
from app.services.tool import InvalidToolInput

ECHO_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def listed(name: str, schema: dict[str, object] | None = None) -> ListedTool:
    return ListedTool(name=name, description=f"{name} tool", input_schema=schema or ECHO_SCHEMA)


class TestDecide:
    def test_denies_a_tool_that_was_never_registered(self) -> None:
        """No policy row is `None`: the call is denied."""
        assert tool.decide(None) == "deny"

    def test_allows_a_registered_tool_and_only_that_one(self) -> None:
        """Only the `allow` effect passes."""
        assert tool.decide(PolicyEffect.allow) == "allow"
        assert tool.decide(PolicyEffect.deny) == "deny"
        # Plan 011: `ask` waits for a person; plan 010 refused it like `deny`.
        assert tool.decide(PolicyEffect.ask) == "ask"


class TestArgumentsDigest:
    def test_is_64_lowercase_hex_characters(self) -> None:
        digest = tool.arguments_digest({"text": "hi"})

        assert len(digest) == 64
        assert digest == digest.lower()
        assert int(digest, 16) >= 0

    def test_does_not_depend_on_key_order(self) -> None:
        assert tool.arguments_digest({"a": 1, "b": [1, {"c": 2, "d": 3}]}) == tool.arguments_digest(
            {"b": [1, {"d": 3, "c": 2}], "a": 1}
        )

    @pytest.mark.parametrize(
        "other", [{"text": "ho"}, {"text": "hi", "x": 1}, {"txt": "hi"}, {"text": "hi "}, {}]
    )
    def test_differs_when_the_arguments_differ(self, other: dict[str, object]) -> None:
        assert tool.arguments_digest(other) != tool.arguments_digest({"text": "hi"})

    def test_reads_non_ascii_text_as_written(self) -> None:
        assert tool.arguments_digest({"text": "é"}) != tool.arguments_digest({"text": "é"})

    def test_is_empty_by_default(self) -> None:
        assert tool.definitions({}) == []
        assert tool.definitions({"lab": []}) == []


class TestNames:
    def test_the_model_sees_server_and_tool_joined_by_two_underscores(self) -> None:
        assert tool.model_name("knowledge", "search") == "knowledge__search"

    def test_splits_at_the_first_separator(self) -> None:
        assert tool.split_name("knowledge__search") == ("knowledge", "search")
        assert tool.split_name("lab__a__b") == ("lab", "a__b")

    @pytest.mark.parametrize("name", ["search", "__search", "knowledge__", "", "__"])
    def test_a_name_without_both_parts_belongs_to_no_server(self, name: str) -> None:
        assert tool.split_name(name) is None


class TestDefinitions:
    def test_are_sorted_by_name_and_strict(self) -> None:
        definitions = tool.definitions(
            {"lab": [listed("zeta"), listed("alpha")], "aaa": [listed("x")]}
        )

        assert [definition["name"] for definition in definitions] == [
            "aaa__x",
            "lab__alpha",
            "lab__zeta",
        ]
        assert definitions[0]["strict"] is True
        assert definitions[0]["eager_input_streaming"] is True
        assert definitions[0]["description"] == "x tool"
        schema = definitions[0]["input_schema"]
        assert isinstance(schema, dict)
        assert schema["additionalProperties"] is False

    def test_are_byte_stable(self) -> None:
        listings = {"lab": [listed("b"), listed("a")]}

        first = json.dumps(tool.definitions(listings))
        second = json.dumps(tool.definitions({"lab": [listed("a"), listed("b")]}))

        assert first == second

    def test_adds_strict_and_streaming_once(self) -> None:
        definition = tool.definitions({"lab": [listed("echo")]})[0]

        assert list(definition) == [
            "name",
            "description",
            "input_schema",
            "strict",
            "eager_input_streaming",
        ]

    def test_leaves_the_servers_schema_untouched(self) -> None:
        schema: dict[str, object] = {"type": "object", "properties": {}}

        definition = tool.definitions({"lab": [listed("echo", schema)]})[0]

        assert definition["input_schema"] == schema
        assert definition["input_schema"] is not schema


class TestValidateInput:
    def test_returns_the_parsed_input(self) -> None:
        assert tool.validate_input(ECHO_SCHEMA, {"text": "hi"}) == {"text": "hi"}

    def test_names_the_failing_field_and_never_the_value(self) -> None:
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(ECHO_SCHEMA, {"text": 5, "extra": "secret-value"})

        assert "text" in str(failure.value)
        assert "secret-value" not in str(failure.value)
        assert str(failure.value).startswith("invalid input")

    def test_refuses_an_input_with_unknown_fields(self) -> None:
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(ECHO_SCHEMA, {"text": "hi", "extra": 1})

        assert "extra" in str(failure.value)

    def test_names_a_missing_required_field(self) -> None:
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(ECHO_SCHEMA, {})

        assert "text" in str(failure.value)

    def test_checks_nested_fields(self) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {"depth": {"type": "integer", "minimum": 1}},
                    "required": ["depth"],
                }
            },
            "required": ["options"],
        }

        assert tool.validate_input(schema, {"options": {"depth": 2}}) == {"options": {"depth": 2}}
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(schema, {"options": {"depth": 0}})

        assert "options.depth" in str(failure.value)

    def test_a_remote_reference_is_refused_and_never_fetched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetched: list[str] = []

        def urlopen(url: str, *args: object, **kwargs: object) -> None:
            fetched.append(url)
            raise OSError("no network in a test")

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        schema: dict[str, object] = {"$ref": "http://169.254.169.254/latest/meta-data/x.json"}

        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(schema, {"text": "hi"})

        assert fetched == []
        assert "169.254" not in str(failure.value)

    def test_a_schema_that_is_itself_invalid_refuses_every_input(self) -> None:
        with pytest.raises(InvalidToolInput):
            tool.validate_input({"type": "no-such-type"}, {"text": "hi"})
