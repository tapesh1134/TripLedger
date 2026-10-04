"""Provider function declarations are discovered from MCP, not duplicated by hand."""

import copy
from typing import Any


def function_schema(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs", {})

    def expand(value: Any) -> Any:
        if isinstance(value, list):
            return [expand(x) for x in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            name = value["$ref"].split("/")[-1]
            return expand(copy.deepcopy(definitions[name]))
        return {k: expand(v) for k, v in value.items() if k not in {"$defs", "title", "default"}}

    result: dict[str, Any] = expand(schema)
    return result
