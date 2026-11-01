"""The dependency ranges state what the code imports."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _dependencies() -> list[str]:
    return [
        str(dep) for dep in tomllib.loads(PYPROJECT.read_text("utf-8"))["project"]["dependencies"]
    ]


class TestMcpDependencies:
    def test_the_sdk_range_starts_at_the_major_the_code_is_written_for(self) -> None:
        assert "mcp>=2.3,<3" in _dependencies()

    def test_the_types_package_the_seam_imports_is_declared(self) -> None:
        assert "mcp-types>=2.3,<3" in _dependencies()

    def test_the_schema_registry_the_validator_imports_is_declared(self) -> None:
        assert any(dep.startswith("referencing") for dep in _dependencies())
