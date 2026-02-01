# Per-App Worker Allocation E2E Tests

End-to-end Docker-based tests for the per-app worker allocation feature.

## Overview

These tests verify that:
- Apps with worker limits are only loaded on the specified number of workers
- Requests are routed only to workers that have the target app loaded
- Round-robin distribution works correctly within limited worker sets
- Worker crash scenarios maintain correct app allocation
- Class attribute `workers=N` is respected
- Config-based `:N` overrides class attributes

## Configuration

The tests use 4 dirty workers with 3 apps:
- **LightweightApp**: No limit (loads on all 4 workers)
- **HeavyApp**: `workers=2` class attribute (loads on 2 workers)
- **ConfigLimitedApp**: `:1` config (loads on 1 worker)

## Running Tests

```bash
# From this directory
cd tests/docker/per_app_allocation

# Build the Docker image
docker compose build

# Run all tests
pytest test_per_app_e2e.py -v

# Run specific test
pytest test_per_app_e2e.py::TestPerAppAllocation::test_config_limited_app_uses_one_worker -v
```

## Test Categories

### TestPerAppAllocation
- Tests basic functionality of per-app worker allocation
- Verifies round-robin distribution
- Tests app accessibility

### TestPerAppWorkerCrash
- Tests behavior when workers crash
- Verifies app recovery after worker respawn

### TestPerAppLogs
- Verifies logging output contains expected information

## Requirements

- Docker and Docker Compose
- Python 3.8+
- pytest
- requests

## Notes

- Tests run on port 8001 to avoid conflicts with the existing dirty_arbiter tests on 8000
- The container uses a keep-alive wrapper to allow testing worker crash scenarios
