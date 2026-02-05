"""JSON output mode utilities."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from rich.console import Console


class CLIJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles CLI types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return super().default(obj)


def json_output(console: Console, data: Any) -> None:
    """Output data as formatted JSON."""
    console.print_json(json.dumps(data, cls=CLIJSONEncoder))
