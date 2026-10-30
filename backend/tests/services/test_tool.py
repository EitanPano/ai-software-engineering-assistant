from collections.abc import Iterator

import pytest

from app.services import tool
from app.services.tool import InvalidToolInput, Tool, ToolInput


class EchoInput(ToolInput):
    text: str


async def echo(arguments: dict[str, object]) -> str:
    return str(arguments["text"])


def make(name: str) -> Tool:
    return Tool(name=name, description=f"{name} tool", input_model=EchoInput, run=echo)


@pytest.fixture(autouse=True)
def empty_registry() -> Iterator[None]:
    tool.clear_tools()
    yield
    tool.clear_tools()


class TestDecide:
    def test_denies_a_tool_that_was_never_registered(self) -> None:
        assert tool.decide("anything") == "deny"

    def test_allows_a_registered_tool_and_only_that_one(self) -> None:
        tool.register_tool(make("echo"))

        assert tool.decide("echo") == "allow"
        assert tool.decide("other") == "deny"

    def test_is_empty_by_default(self) -> None:
        assert tool.definitions() == []


class TestDefinitions:
    def test_are_sorted_by_name_and_strict(self) -> None:
        tool.register_tool(make("zeta"))
        tool.register_tool(make("alpha"))

        definitions = tool.definitions()

        assert [definition["name"] for definition in definitions] == ["alpha", "zeta"]
        assert definitions[0]["strict"] is True
        assert definitions[0]["eager_input_streaming"] is True
        schema = definitions[0]["input_schema"]
        assert isinstance(schema, dict)
        assert schema["additionalProperties"] is False

    def test_are_byte_stable(self) -> None:
        tool.register_tool(make("echo"))

        assert str(tool.definitions()) == str(tool.definitions())


class TestValidateInput:
    def test_returns_the_parsed_input(self) -> None:
        assert tool.validate_input(make("echo"), {"text": "hi"}) == {"text": "hi"}

    def test_names_the_failing_field_and_never_the_value(self) -> None:
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(make("echo"), {"text": 5, "extra": "secret-value"})

        assert "text" in str(failure.value)
        assert "secret-value" not in str(failure.value)

    def test_refuses_an_input_with_unknown_fields(self) -> None:
        with pytest.raises(InvalidToolInput):
            tool.validate_input(make("echo"), {"text": "hi", "extra": 1})
