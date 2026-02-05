"""Rich terminal output formatters."""

from typing import Any, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def format_success(console: Console, message: str) -> None:
    """Display success message in green."""
    console.print(f"[green]{message}[/green]")


def format_error(console: Console, message: str, hint: str | None = None) -> None:
    """Display error message in red with optional hint."""
    console.print(f"[red]Error:[/red] {message}")
    if hint:
        console.print(f"[yellow]Hint:[/yellow] {hint}")


def format_warning(console: Console, message: str) -> None:
    """Display warning message in yellow."""
    console.print(f"[yellow]Warning:[/yellow] {message}")


def format_table(
    console: Console,
    title: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    """Display data as a formatted table."""
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def format_panel(console: Console, title: str, content: str) -> None:
    """Display content in a panel."""
    console.print(Panel(content, title=title))


def format_key_value(console: Console, data: dict[str, Any]) -> None:
    """Display key-value pairs."""
    max_key_len = max(len(k) for k in data.keys()) if data else 0
    for key, value in data.items():
        console.print(f"[cyan]{key.ljust(max_key_len)}[/cyan]: {value}")
