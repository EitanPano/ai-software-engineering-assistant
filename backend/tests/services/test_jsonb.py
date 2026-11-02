import math

import pytest

from app.services.utils.jsonb import jsonb_safe


class TestJsonbSafe:
    @pytest.mark.parametrize(
        "value",
        [
            "x\x00",
            {"a": ["x\x00"]},
            {"a\x00": 1},
            {"a": {"b": [{"c": "\x00"}]}},
            math.nan,
            math.inf,
            -math.inf,
            {"a": [1, {"b": math.inf}]},
            1e400,
        ],
    )
    def test_refuses_what_jsonb_refuses_at_any_depth_and_in_keys(self, value: object) -> None:
        assert not jsonb_safe(value)

    @pytest.mark.parametrize(
        "value",
        [
            {"a": ["x", {"b": "ü\n\t"}], "c": None, "d": 1, "e": 1.5, "f": True, "g": -0.0},
            [],
            "",
            0,
        ],
    )
    def test_accepts_everything_else(self, value: object) -> None:
        assert jsonb_safe(value)
