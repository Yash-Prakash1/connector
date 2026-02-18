"""CLI entry point for hardware-connector."""

from __future__ import annotations

import os
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

import hardware_agent

app = typer.Typer(
    name="hardware-connector",
    help="AI-powered lab instrument connection assistant.",
    no_args_is_help=True,
)
console = Console()


def _resolve_model(model: Optional[str]) -> str:
    """Resolve model from CLI flag → env var → config → default."""
    if model:
        return model
    env_model = os.environ.get("HARDWARE_AGENT_MODEL")
    if env_model:
        return env_model
    try:
        from hardware_agent.data.store import DataStore

        store = DataStore()
        cfg_model = store.get_config("model")
        store.close()
        if cfg_model:
            return cfg_model
    except Exception:
        pass
    return "claude-sonnet-4-20250514"


@app.command()
def connect(
    device: Optional[str] = typer.Option(
        None, "--device", "-d", help="Device identifier (e.g. rigol_ds1054z)"
    ),
    env: Optional[str] = typer.Option(
        None, "--env", "-e", help="Python environment path"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Auto-confirm all actions"
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="LLM model to use"
    ),
    max_iterations: int = typer.Option(
        20, "--max-iterations", help="Maximum agent iterations"
    ),
) -> None:
    """Connect to a lab instrument using an AI agent."""
    from hardware_agent.core.providers import detect_provider, get_provider_class

    # Resolve model first so we know which provider (and API key) to check
    resolved_model = _resolve_model(model)
    provider_name = detect_provider(resolved_model)

    try:
        provider_class = get_provider_class(provider_name)
    except ImportError as e:
        console.print(f"[red]Error: {e}[/]")
        raise typer.Exit(1)

    has_key, key_name = provider_class.check_api_key()
    if not has_key:
        console.print(
            f"[red]Error: {key_name} environment variable not set.[/]\n"
            f"Set it with: export {key_name}='your-key-here'",
        )
        raise typer.Exit(1)

    from hardware_agent.core.environment import EnvironmentDetector
    from hardware_agent.core.module_loader import (
        auto_detect_device,
        list_available_modules,
        load_module,
    )
    from hardware_agent.core.orchestrator import Orchestrator

    # Detect environment
    console.print("[dim]Detecting environment...[/]")
    environment = EnvironmentDetector.detect_current()

    # Load device module
    device_module = None
    if device:
        try:
            device_module = load_module(device)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            raise typer.Exit(1)
    else:
        console.print("[dim]Auto-detecting device...[/]")
        device_module = auto_detect_device(environment)
        if device_module is None:
            available = list_available_modules()
            if available:
                console.print(
                    "[yellow]No device auto-detected. "
                    "Available devices:[/]"
                )
                for name in available:
                    console.print(f"  - {name}")
                console.print(
                    "\nSpecify one with: "
                    "[bold]hardware-connector connect --device <name>[/]"
                )
            else:
                console.print("[red]No device modules available.[/]")
            raise typer.Exit(1)

    info = device_module.get_info()
    console.print(f"[green]Using device: {info.name}[/]")

    # Run orchestrator
    orchestrator = Orchestrator(
        environment=environment,
        device_module=device_module,
        auto_confirm=yes,
        console=console,
        max_iterations=max_iterations,
        model=resolved_model,
    )

    result = orchestrator.run()

    # Write output file if successful
    if result.success and result.final_code:
        output_file = f"{info.identifier}_connect.py"
        with open(output_file, "w") as f:
            f.write(result.final_code)
        console.print(f"\n[green]Code saved to: {output_file}[/]")

    raise typer.Exit(0 if result.success else 1)


@app.command("list-devices")
def list_devices() -> None:
    """List all supported device modules."""
    from hardware_agent.core.module_loader import list_available_modules, load_module

    modules = list_available_modules()
    if not modules:
        console.print("[yellow]No device modules found.[/]")
        raise typer.Exit(0)

    table = Table(title="Supported Devices")
    table.add_column("Identifier", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Manufacturer")
    table.add_column("Category")
    table.add_column("Connection")

    for mod_id in modules:
        mod = load_module(mod_id)
        info = mod.get_info()
        table.add_row(
            info.identifier,
            info.name,
            info.manufacturer,
            info.category,
            info.connection_type,
        )

    console.print(table)


@app.command()
def detect() -> None:
    """Show environment info and auto-detect connected devices."""
    from hardware_agent.core.environment import EnvironmentDetector
    from hardware_agent.core.module_loader import auto_detect_device

    console.print("[dim]Detecting environment...[/]\n")
    env = EnvironmentDetector.detect_current()

    table = Table(title="Environment")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("OS", f"{env.os.value} ({env.os_version})")
    table.add_row("Python", f"{env.python_version} ({env.python_path})")
    table.add_row("Environment", f"{env.env_type}" + (
        f" ({env.env_path})" if env.env_path else ""
    ))
    table.add_row("USB Devices", str(len(env.usb_devices)))
    table.add_row("VISA Resources", str(len(env.visa_resources)))

    console.print(table)

    if env.usb_devices:
        console.print("\n[bold]USB Devices:[/]")
        for dev in env.usb_devices[:20]:
            console.print(f"  {dev}")

    if env.visa_resources:
        console.print("\n[bold]VISA Resources:[/]")
        for res in env.visa_resources:
            console.print(f"  {res}")

    console.print("\n[dim]Auto-detecting supported devices...[/]")
    device = auto_detect_device(env)
    if device:
        info = device.get_info()
        console.print(f"[green]Detected: {info.name} ({info.identifier})[/]")
    else:
        console.print("[yellow]No supported device detected.[/]")


@app.command()
def config(
    action: str = typer.Argument(
        "get", help="Action: get or set"
    ),
    key: Optional[str] = typer.Argument(
        None, help="Config key (telemetry, model)"
    ),
    value: Optional[str] = typer.Argument(
        None, help="Value to set"
    ),
) -> None:
    """View or modify configuration."""
    from hardware_agent.data.store import DataStore

    store = DataStore()

    if action == "get":
        if key:
            val = store.get_config(key)
            if val is not None:
                console.print(f"{key} = {val}")
            else:
                console.print(f"[yellow]{key} is not set[/]")
        else:
            # Show all config
            for k in ["telemetry", "model"]:
                val = store.get_config(k)
                console.print(f"{k} = {val or '(not set)'}")
    elif action == "set":
        if not key or value is None:
            console.print("[red]Usage: hardware-connector config set <key> <value>[/]")
            raise typer.Exit(1)
        # Validate
        valid_keys = {"telemetry", "model"}
        if key not in valid_keys:
            console.print(
                f"[red]Unknown config key: {key}. "
                f"Valid keys: {', '.join(valid_keys)}[/]"
            )
            raise typer.Exit(1)
        if key == "telemetry" and value not in ("on", "off", "true", "false"):
            console.print("[red]Telemetry value must be on/off or true/false[/]")
            raise typer.Exit(1)
        store.set_config(key, value)
        console.print(f"[green]Set {key} = {value}[/]")
    else:
        console.print("[red]Unknown action. Use 'get' or 'set'.[/]")
        raise typer.Exit(1)

    store.close()


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"hardware-connector {hardware_agent.__version__}")


if __name__ == "__main__":
    app()
