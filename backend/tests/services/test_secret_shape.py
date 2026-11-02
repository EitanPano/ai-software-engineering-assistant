import pytest

from app.services.utils.secret_shape import looks_like_secret


class TestLooksLikeSecret:
    @pytest.mark.parametrize(
        "text",
        [
            "The key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789.",
            "Token ghp_abcdefghijklmnopqrstuvwxyz0123 works.",
            "github_pat_11ABCDEFG0abcdefghijklmnop_qrstuvwxyz",
            "AWS key AKIAIOSFODNN7EXAMPLE",
            "The database is postgresql://app:hunter2secret@db.internal:5432/app",
            "The registry is https://bob:s3cr3t@registry.example.com/simple",
            "The GitLab token is " + "glpat-" + "AbCdEf1234567890xYzW",
            "-----BEGIN RSA PRIVATE KEY-----",
            "Voyage key pa-abcdefghijklmnopqrstuvwxyz0123",
            "It is 3f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b9c8d7e",
        ],
    )
    def test_a_key_shaped_text_is_a_secret(self, text: str) -> None:
        assert looks_like_secret(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "The person keeps deploy notes in ops/RUNBOOK.md.",
            "The person prefers uv over pip for Python projects.",
            "The service is named internationalization-configuration-management-service.",
            "The docs live at https://example.com/guide and need no login.",
            "",
        ],
    )
    def test_an_ordinary_fact_is_not(self, text: str) -> None:
        assert looks_like_secret(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "The person keeps migrations in backend/src/app/infra/migrations/v2/postgres.",
            "The release commit is 3f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a.",
            "The request id was 123e4567-e89b-12d3-a456-426614174000.",
        ],
    )
    def test_a_long_path_a_commit_and_a_uuid_are_dropped_on_purpose(self, text: str) -> None:
        """The decision: a lost fact can be restated, a stored key goes to Voyage."""
        assert looks_like_secret(text) is True
