"""Keep a bounded full history for Day 4; do not silently drop evidence."""

import json
from typing import Any


def context_size(messages: list[dict[str, Any]]) -> int:
    return len(json.dumps(messages, ensure_ascii=False))
