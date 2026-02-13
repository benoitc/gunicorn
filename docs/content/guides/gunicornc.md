---
title: Control Interface (gunicornc)
menu:
    guides:
        weight: 15
---

# Control Interface (gunicornc)

Gunicorn provides a control interface similar to [birdc](https://bird.network.cz/?get_doc&v=20&f=bird-3.html) for the BIRD routing daemon. This allows you to inspect and manage a running Gunicorn instance via a Unix socket.

## Overview

The control interface consists of two parts:

1. **Control Socket Server** - Runs in the arbiter process, accepts commands via Unix socket
2. **gunicornc CLI** - Interactive client that connects to the control socket

## Quick Start

### Start Gunicorn with Control Socket

By default, Gunicorn creates a control socket at `gunicorn.ctl` in the current directory:

```bash
gunicorn -w 4 myapp:app
```

Or specify a custom path:

```bash
gunicorn --control-socket /tmp/myapp.ctl -w 4 myapp:app
```

### Connect with gunicornc

```bash
# Connect to default socket (./gunicorn.ctl)
gunicornc

# Connect to custom socket
gunicornc -s /tmp/myapp.ctl

# Run a single command
gunicornc -c "show workers"

# Output as JSON (for scripting)
gunicornc -c "show stats" -j
```

## Interactive Mode

When run without the `-c` flag, gunicornc enters interactive mode with readline support:

```
$ gunicornc
Connected to gunicorn.ctl
Type 'help' for available commands, 'quit' to exit.

gunicorn> show workers
PID        AGE    BOOTED   LAST_BEAT
----------------------------------------
12345      1      yes      0.2s ago
12346      2      yes      0.1s ago
12347      3      yes      0.3s ago

Total: 3 workers

gunicorn> worker add 2
{
  "added": 2,
  "previous": 3,
  "total": 5
}

gunicorn> quit
```

## Commands

### Show Commands

| Command | Description |
|---------|-------------|
| `show all` | Overview of all processes (arbiter, web workers, dirty workers) |
| `show workers` | List HTTP workers with status |
| `show dirty` | List dirty workers and apps |
| `show config` | Show current effective configuration |
| `show stats` | Show server statistics |
| `show listeners` | Show bound sockets |
| `help` | Show available commands |

### Worker Management

| Command | Description |
|---------|-------------|
| `worker add [N]` | Spawn N workers (default 1) |
| `worker remove [N]` | Remove N workers (default 1) |
| `worker kill <PID>` | Gracefully terminate specific worker |

### Dirty Worker Management

| Command | Description |
|---------|-------------|
| `dirty add [N]` | Spawn N dirty workers (default 1) |
| `dirty remove [N]` | Remove N dirty workers (default 1) |

!!! note "Per-App Worker Limits"
    When using `dirty add`, workers only load apps that haven't reached their
    worker limits. If all apps are at their limits, no new workers will be spawned.
    The response will include a `reason` field explaining this.

### Server Control

| Command | Description |
|---------|-------------|
| `reload` | Graceful reload (equivalent to SIGHUP) |
| `reopen` | Reopen log files (equivalent to SIGUSR1) |
| `shutdown [graceful\|quick]` | Shutdown server (SIGTERM or SIGINT) |

## Example Session

```
$ gunicornc
Connected to gunicorn.ctl
Type 'help' for available commands, 'quit' to exit.

gunicorn> show all
ARBITER (master)
  PID: 12345

WEB WORKERS (4)
  PID        AGE    BOOTED   LAST_BEAT
  --------------------------------------
  12346      1      yes      0.05s ago
  12347      2      yes      0.04s ago
  12348      3      yes      0.03s ago
  12349      4      yes      0.02s ago

DIRTY ARBITER
  PID: 12350

DIRTY WORKERS (2)
  PID        AGE    APPS
  --------------------------------------------------
  12351      1      MLModel
                    ImageProcessor
  12352      2      MLModel

gunicorn> show stats
Uptime:           2h 15m 30s
PID:              12345
Workers current:  4
Workers target:   4
Workers spawned:  6
Workers killed:   2
Reloads:          1

gunicorn> worker add
{
  "added": 1,
  "previous": 4,
  "total": 5
}

gunicorn> dirty add 1
{
  "success": true,
  "operation": "add",
  "requested": 1,
  "spawned": 1,
  "total_workers": 3,
  "target_workers": 3
}

gunicorn> quit
```

## Configuration

### Settings

| Setting | CLI Flag | Default | Description |
|---------|----------|---------|-------------|
| `control_socket` | `--control-socket` | `gunicorn.ctl` | Unix socket path |
| `control_socket_mode` | `--control-socket-mode` | `0o600` | Socket file permissions |
| `control_socket_disable` | `--no-control-socket` | `False` | Disable control socket |

### Example Configuration

```python
# gunicorn.conf.py
bind = "0.0.0.0:8000"
workers = 4

# Control socket settings
control_socket = "/var/run/gunicorn/myapp.ctl"
control_socket_mode = 0o660  # Allow group access
```

## Scripting

Use the `-j` flag for JSON output when scripting:

```bash
#!/bin/bash

# Get current worker count
workers=$(gunicornc -c "show stats" -j | jq -r '.workers_current')
echo "Current workers: $workers"

# Scale up if needed
if [ "$workers" -lt 8 ]; then
    gunicornc -c "worker add $((8 - workers))"
fi
```

## Security

The control socket uses filesystem permissions for access control:

- **Default mode**: `0o600` (owner only)
- **No authentication**: Relies on filesystem permissions
- **Unix socket only**: No TCP/remote access

To allow group access:

```python
control_socket_mode = 0o660
```

To disable the control socket entirely:

```bash
gunicorn --no-control-socket myapp:app
```

## Protocol

The control interface uses a JSON-based protocol with length-prefixed framing:

```
+----------------+------------------+
| Length (4B BE) |  JSON Payload    |
+----------------+------------------+
```

### Request Format

```json
{
  "id": 1,
  "command": "show workers"
}
```

### Response Format

```json
{
  "id": 1,
  "status": "ok",
  "data": { ... }
}
```

### Error Response

```json
{
  "id": 1,
  "status": "error",
  "error": "Unknown command: foo"
}
```

## Troubleshooting

### Cannot connect to socket

```
Error: Connection refused
```

- Check that Gunicorn is running
- Verify the socket path is correct
- Check socket file permissions

### Permission denied

```
Error: Permission denied
```

- Check that you have read/write access to the socket file
- The socket is created with mode `0o600` by default (owner only)

### Socket not found

```
Error: No such file or directory
```

- Gunicorn creates the socket relative to the working directory by default
- Use an absolute path with `--control-socket /path/to/socket.ctl`
- Check if `--no-control-socket` was specified
