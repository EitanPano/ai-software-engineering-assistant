"""constants.py belongs: what is fixed about the servers the product ships: the `knowledge` server's
name, and the one tool it offers, written out because `strict` tool use needs
`additionalProperties: false` and no length keyword, which a definition derived from a signature
would not give.
It does not belong: policy such as timeouts (`config/constants.py`).
"""

from typing import Final

from app.models.mcp_server.type import ListedTool

KNOWLEDGE_SERVER: Final = "knowledge"

# The description is part of the model's prompt and of the cache prefix; change it with care.
SEARCH_TOOL: Final = ListedTool(
    name="search",
    description=(
        "Searches the connected repositories (code, documentation and tests) and returns the "
        "best matching passages, best first, each with its repository url, ref, file path, "
        "symbol, start and end lines and content. Give a question or the names you expect in the "
        "code. `incomplete` is true when the search was cut short; `omitted` counts passages "
        "left out to fit. An empty `hits` list means nothing matched."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for: a question, a description or code names.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
