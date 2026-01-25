# Docker-Based Dirty Arbiter Integration Tests

This directory contains Docker-based integration tests that verify the dirty
arbiter process lifecycle under realistic conditions.

## Overview

These tests verify:

1. **Parent Death Detection**: Dirty arbiter self-terminates when main arbiter
   dies unexpectedly (SIGKILL)
2. **Orphan Cleanup**: Old dirty arbiter processes are cleaned up on restart
3. **Respawning**: Main arbiter respawns dirty arbiter when it crashes
4. **Graceful Shutdown**: Both arbiters exit cleanly on SIGTERM

## Prerequisites

- Docker
- Python 3.10+
- pytest

## Quick Start

```bash
# Build the Docker image
docker compose build

# Run all tests
pytest test_parent_death.py -v

# Run specific test
pytest test_parent_death.py::TestParentDeath::test_dirty_arbiter_exits_on_parent_sigkill -v
```

## Manual Verification

You can manually verify the behavior:

```bash
# Start the container
docker compose up -d

# Check running processes
docker exec dirty_arbiter-gunicorn-1 ps aux | grep gunicorn

# SIGKILL the master and watch dirty arbiter exit
MASTER_PID=$(docker exec dirty_arbiter-gunicorn-1 pgrep -f "gunicorn: master")
docker exec dirty_arbiter-gunicorn-1 kill -9 $MASTER_PID

# After ~2 seconds, check that all gunicorn processes exited
docker exec dirty_arbiter-gunicorn-1 ps aux | grep gunicorn

# View logs
docker logs dirty_arbiter-gunicorn-1

# Cleanup
docker compose down
```

## Test Scenarios

### Scenario 1: Parent SIGKILL

Tests that the dirty arbiter detects parent death via ppid check:

1. Start gunicorn with dirty workers
2. SIGKILL the main arbiter (bypasses graceful shutdown)
3. Verify dirty arbiter detects ppid change within ~2 seconds
4. Verify no orphan processes remain

### Scenario 2: Orphan Cleanup

Tests the `_cleanup_orphaned_dirty_arbiter()` mechanism:

1. Start gunicorn, note dirty arbiter PID
2. SIGKILL main arbiter (dirty arbiter becomes orphan)
3. Restart gunicorn
4. Verify old dirty arbiter was cleaned up
5. Verify new dirty arbiter spawned

### Scenario 3: Dirty Arbiter Respawn

Tests that main arbiter respawns a dead dirty arbiter:

1. Start gunicorn
2. SIGKILL the dirty arbiter
3. Wait for respawn (~1-2 seconds)
4. Verify new dirty arbiter is running

### Scenario 4: Graceful Shutdown

Tests clean shutdown via SIGTERM:

1. Start gunicorn with dirty workers
2. SIGTERM the main arbiter
3. Verify both arbiters exit cleanly within graceful_timeout
4. Verify clean exit logs

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Container build configuration |
| `docker-compose.yml` | Container orchestration |
| `app.py` | Simple WSGI app with TestDirtyApp |
| `gunicorn_conf.py` | Gunicorn configuration |
| `test_parent_death.py` | pytest integration tests |
| `README.md` | This file |

## Configuration

The `gunicorn_conf.py` uses:
- 1 sync worker
- 1 dirty worker
- 5 second graceful timeout (for faster tests)
- Debug logging

## Expected Log Messages

When verifying behavior, look for these log messages:

| Message | Meaning |
|---------|---------|
| `Parent changed, shutting down dirty arbiter` | ppid detection triggered |
| `Killing orphaned dirty arbiter` | Orphan cleanup activated |
| `Spawning dirty arbiter` | New dirty arbiter being created |
| `Dirty arbiter exiting` | Clean shutdown |

## Troubleshooting

**Tests time out waiting for container**:
- Check Docker is running
- Check no port conflicts on 8000
- Try `docker compose down` and rebuild

**Dirty arbiter doesn't exit after parent death**:
- Check ppid detection is working (logs should show check)
- The check runs every 1 second, so allow 2-3 seconds

**Container logs not showing expected messages**:
- Verify loglevel is set to "debug" in gunicorn_conf.py
- Check `docker logs <container>` for full output
