#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
gunicornc - Gunicorn control interface CLI

Interactive and single-command modes for controlling Gunicorn instances.
"""

import argparse
import json
import os
import sys

from gunicorn.ctl.client import ControlClient, ControlClientError, parse_command


def format_workers(data: dict) -> str:
    """Format workers output for display."""
    workers = data.get("workers", [])
    if not workers:
        return "No workers running"

    lines = []
    lines.append(f"{'PID':<10} {'AGE':<6} {'BOOTED':<8} {'LAST_BEAT'}")
    lines.append("-" * 40)

    for w in workers:
        pid = w.get("pid", "?")
        age = w.get("age", "?")
        booted = "yes" if w.get("booted") else "no"
        hb = w.get("last_heartbeat")
        hb_str = f"{hb}s ago" if hb is not None else "n/a"

        lines.append(f"{pid:<10} {age:<6} {booted:<8} {hb_str}")

    lines.append("")
    lines.append(f"Total: {data.get('count', len(workers))} workers")

    return "\n".join(lines)


def format_dirty(data: dict) -> str:
    """Format dirty workers output for display."""
    if not data.get("enabled"):
        return "Dirty arbiter not running"

    lines = []
    lines.append(f"Dirty arbiter PID: {data.get('pid')}")
    lines.append("")

    workers = data.get("workers", [])
    if workers:
        lines.append("DIRTY WORKERS:")
        lines.append(f"{'PID':<10} {'AGE':<6} {'APPS':<30} {'LAST_BEAT'}")
        lines.append("-" * 60)

        for w in workers:
            pid = w.get("pid", "?")
            age = w.get("age", "?")
            apps = ", ".join(w.get("apps", []))[:30]
            hb = w.get("last_heartbeat")
            hb_str = f"{hb}s ago" if hb is not None else "n/a"

            lines.append(f"{pid:<10} {age:<6} {apps:<30} {hb_str}")
        lines.append("")

    apps = data.get("apps", [])
    if apps:
        lines.append("DIRTY APPS:")
        lines.append(f"{'APP':<30} {'WORKERS':<10} {'LIMIT'}")
        lines.append("-" * 50)

        for app in apps:
            path = app.get("import_path", "?")[:30]
            current = app.get("current_workers", 0)
            limit = app.get("worker_count")
            limit_str = str(limit) if limit is not None else "none"

            lines.append(f"{path:<30} {current:<10} {limit_str}")

    return "\n".join(lines)


def format_stats(data: dict) -> str:
    """Format stats output for display."""
    lines = []

    uptime = data.get("uptime")
    if uptime:
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        if hours:
            uptime_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes:
            uptime_str = f"{minutes}m {seconds}s"
        else:
            uptime_str = f"{seconds}s"
    else:
        uptime_str = "unknown"

    lines.append(f"Uptime:           {uptime_str}")
    lines.append(f"PID:              {data.get('pid', 'unknown')}")
    lines.append(f"Workers current:  {data.get('workers_current', 0)}")
    lines.append(f"Workers target:   {data.get('workers_target', 0)}")
    lines.append(f"Workers spawned:  {data.get('workers_spawned', 0)}")
    lines.append(f"Workers killed:   {data.get('workers_killed', 0)}")
    lines.append(f"Reloads:          {data.get('reloads', 0)}")

    dirty_pid = data.get("dirty_arbiter_pid")
    if dirty_pid:
        lines.append(f"Dirty arbiter:    {dirty_pid}")

    return "\n".join(lines)


def format_listeners(data: dict) -> str:
    """Format listeners output for display."""
    listeners = data.get("listeners", [])
    if not listeners:
        return "No listeners bound"

    lines = []
    lines.append(f"{'ADDRESS':<40} {'TYPE':<8} {'FD'}")
    lines.append("-" * 55)

    for lnr in listeners:
        addr = lnr.get("address", "?")
        ltype = lnr.get("type", "?")
        fd = lnr.get("fd", "?")
        lines.append(f"{addr:<40} {ltype:<8} {fd}")

    lines.append("")
    lines.append(f"Total: {data.get('count', len(listeners))} listeners")

    return "\n".join(lines)


def format_config(data: dict) -> str:
    """Format config output for display."""
    lines = []

    # Sort keys for consistent output
    for key in sorted(data.keys()):
        value = data[key]
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{key}: {value}")

    return "\n".join(lines)


def format_help(data: dict) -> str:
    """Format help output for display."""
    commands = data.get("commands", {})
    lines = []
    lines.append("Available commands:")
    lines.append("")

    # Find max command length for alignment
    max_len = max(len(cmd) for cmd in commands.keys()) if commands else 0

    for cmd, desc in sorted(commands.items()):
        lines.append(f"  {cmd:<{max_len + 2}} {desc}")

    return "\n".join(lines)


def format_all(data: dict) -> str:
    """Format show all output for display."""
    lines = []

    # Arbiter
    arbiter = data.get("arbiter", {})
    lines.append("ARBITER (master)")
    lines.append(f"  PID: {arbiter.get('pid', '?')}")
    lines.append("")

    # Web workers
    web_workers = data.get("web_workers", [])
    lines.append(f"WEB WORKERS ({data.get('web_worker_count', 0)})")
    if web_workers:
        lines.append(f"  {'PID':<10} {'AGE':<6} {'BOOTED':<8} {'LAST_BEAT'}")
        lines.append(f"  {'-' * 38}")
        for w in web_workers:
            pid = w.get("pid", "?")
            age = w.get("age", "?")
            booted = "yes" if w.get("booted") else "no"
            hb = w.get("last_heartbeat")
            hb_str = f"{hb}s ago" if hb is not None else "n/a"
            lines.append(f"  {pid:<10} {age:<6} {booted:<8} {hb_str}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Dirty arbiter
    dirty_arbiter = data.get("dirty_arbiter")
    if dirty_arbiter:
        lines.append("DIRTY ARBITER")
        lines.append(f"  PID: {dirty_arbiter.get('pid', '?')}")
        lines.append("")

        # Dirty workers
        dirty_workers = data.get("dirty_workers", [])
        lines.append(f"DIRTY WORKERS ({data.get('dirty_worker_count', 0)})")
        if dirty_workers:
            lines.append(f"  {'PID':<10} {'AGE':<6} {'APPS'}")
            lines.append(f"  {'-' * 50}")
            for w in dirty_workers:
                pid = w.get("pid", "?")
                age = w.get("age", "?")
                apps = w.get("apps", [])
                # Show each app on its own line if multiple
                if apps:
                    first_app = apps[0].split(":")[-1]  # Just the class name
                    lines.append(f"  {pid:<10} {age:<6} {first_app}")
                    for app in apps[1:]:
                        app_name = app.split(":")[-1]
                        lines.append(f"  {'':<10} {'':<6} {app_name}")
                else:
                    lines.append(f"  {pid:<10} {age:<6} (no apps)")
        else:
            lines.append("  (none)")
    else:
        lines.append("DIRTY ARBITER")
        lines.append("  (not running)")

    return "\n".join(lines)


def format_response(command: str, data: dict) -> str:  # pylint: disable=too-many-return-statements
    """
    Format response data based on command.

    Args:
        command: Original command string
        data: Response data dictionary

    Returns:
        Formatted string for display
    """
    cmd_lower = command.lower().strip()

    # Route to specific formatters
    if cmd_lower == "show all":
        return format_all(data)
    elif cmd_lower == "show workers":
        return format_workers(data)
    elif cmd_lower == "show dirty":
        return format_dirty(data)
    elif cmd_lower == "show stats":
        return format_stats(data)
    elif cmd_lower == "show listeners":
        return format_listeners(data)
    elif cmd_lower == "show config":
        return format_config(data)
    elif cmd_lower == "help":
        return format_help(data)
    else:
        # Generic JSON output for other commands
        if data:
            return json.dumps(data, indent=2)
        return "OK"


def run_command(socket_path: str, command: str, json_output: bool = False) -> int:
    """
    Execute single command and exit.

    Args:
        socket_path: Path to control socket
        command: Command to execute
        json_output: If True, output raw JSON

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        with ControlClient(socket_path) as client:
            cmd, args = parse_command(command)
            full_command = f"{cmd} {' '.join(args)}".strip() if args else cmd
            result = client.send_command(full_command)

            if json_output:
                print(json.dumps(result, indent=2))
            else:
                output = format_response(cmd, result)
                print(output)

            return 0

    except ControlClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def run_interactive(socket_path: str, json_output: bool = False) -> int:
    """
    Run interactive CLI with readline support.

    Args:
        socket_path: Path to control socket
        json_output: If True, output raw JSON

    Returns:
        Exit code
    """
    try:
        import readline  # noqa: F401 - imported for side effects
        has_readline = True
    except ImportError:
        has_readline = False

    try:
        client = ControlClient(socket_path)
        client.connect()
    except ControlClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Connected to {socket_path}")
    print("Type 'help' for available commands, 'quit' to exit.")
    print()

    # Set up readline history
    history_file = os.path.expanduser("~/.gunicornc_history")
    if has_readline:
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass

    exit_code = 0

    try:
        while True:
            try:
                line = input("gunicorn> ").strip()
            except EOFError:
                print()
                break

            if not line:
                continue

            if line.lower() in ('quit', 'exit', 'q'):
                break

            try:
                cmd, args = parse_command(line)
                full_command = f"{cmd} {' '.join(args)}".strip() if args else cmd
                result = client.send_command(full_command)

                if json_output:
                    print(json.dumps(result, indent=2))
                else:
                    output = format_response(cmd, result)
                    print(output)

            except ControlClientError as e:
                print(f"Error: {e}")
                # Try to reconnect
                try:
                    client.close()
                    client.connect()
                except ControlClientError:
                    print("Connection lost. Exiting.")
                    exit_code = 1
                    break

            print()

    except KeyboardInterrupt:
        print()
        exit_code = 130
    finally:
        client.close()
        if has_readline:
            try:
                readline.write_history_file(history_file)
            except Exception:
                pass

    return exit_code


def main():
    """Main entry point for gunicornc CLI."""
    parser = argparse.ArgumentParser(
        description='Gunicorn control interface',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gunicornc                      # Interactive mode (default socket)
  gunicornc -s /tmp/myapp.ctl    # Interactive mode with custom socket
  gunicornc -c "show workers"    # Single command mode
  gunicornc -c "worker add 2"    # Add 2 workers
  gunicornc -c "show stats" -j   # Output stats as JSON
        """
    )

    parser.add_argument(
        '-s', '--socket',
        default='gunicorn.ctl',
        help='Control socket path (default: gunicorn.ctl in current directory)'
    )

    parser.add_argument(
        '-c', '--command',
        help='Execute single command and exit'
    )

    parser.add_argument(
        '-j', '--json',
        action='store_true',
        help='Output raw JSON (for scripting)'
    )

    parser.add_argument(
        '-v', '--version',
        action='store_true',
        help='Show version and exit'
    )

    args = parser.parse_args()

    if args.version:
        from gunicorn import __version__
        print(f"gunicornc (gunicorn {__version__})")
        return 0

    socket_path = args.socket

    # Make relative paths absolute from cwd
    if not os.path.isabs(socket_path):
        socket_path = os.path.join(os.getcwd(), socket_path)

    if args.command:
        return run_command(socket_path, args.command, args.json)
    else:
        return run_interactive(socket_path, args.json)


if __name__ == '__main__':
    sys.exit(main())
