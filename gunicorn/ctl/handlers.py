#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Control Interface Command Handlers

Provides handlers for all control commands with access to arbiter state.
"""

import os
import signal
import socket
import time


class CommandHandlers:
    """
    Command handlers with access to arbiter state.

    All handler methods return dictionaries that will be sent
    as the response data.
    """

    def __init__(self, arbiter):
        """
        Initialize handlers with arbiter reference.

        Args:
            arbiter: The Gunicorn arbiter instance
        """
        self.arbiter = arbiter

    def show_workers(self) -> dict:
        """
        Return list of HTTP workers.

        Returns:
            Dictionary with workers list containing:
            - pid: Worker process ID
            - age: Worker age (spawn order)
            - requests: Number of requests handled (if available)
            - booted: Whether worker has finished booting
            - last_heartbeat: Seconds since last heartbeat
        """
        workers = []
        now = time.monotonic()

        for pid, worker in self.arbiter.WORKERS.items():
            try:
                last_update = worker.tmp.last_update()
                last_heartbeat = round(now - last_update, 2)
            except (OSError, ValueError):
                last_heartbeat = None

            workers.append({
                "pid": pid,
                "age": worker.age,
                "booted": worker.booted,
                "aborted": worker.aborted,
                "last_heartbeat": last_heartbeat,
            })

        # Sort by age (oldest first)
        workers.sort(key=lambda w: w["age"])

        return {"workers": workers, "count": len(workers)}

    def show_dirty(self) -> dict:
        """
        Return dirty workers and apps information.

        Returns:
            Dictionary with:
            - enabled: Whether dirty arbiter is running
            - pid: Dirty arbiter PID
            - workers: List of dirty worker info
            - apps: List of dirty app specs
        """
        if not self.arbiter.dirty_arbiter_pid:
            return {
                "enabled": False,
                "pid": None,
                "workers": [],
                "apps": [],
            }

        # Get dirty arbiter reference if available
        dirty_arbiter = getattr(self.arbiter, 'dirty_arbiter', None)

        workers = []
        apps = []

        if dirty_arbiter and hasattr(dirty_arbiter, 'workers'):
            now = time.monotonic()
            for pid, worker in dirty_arbiter.workers.items():
                try:
                    last_update = worker.tmp.last_update()
                    last_heartbeat = round(now - last_update, 2)
                except (OSError, ValueError, AttributeError):
                    last_heartbeat = None

                workers.append({
                    "pid": pid,
                    "age": worker.age,
                    "apps": getattr(worker, 'app_paths', []),
                    "booted": getattr(worker, 'booted', False),
                    "last_heartbeat": last_heartbeat,
                })

            # Get app specs
            if hasattr(dirty_arbiter, 'app_specs'):
                for path, spec in dirty_arbiter.app_specs.items():
                    worker_pids = list(dirty_arbiter.app_worker_map.get(path, []))
                    apps.append({
                        "import_path": path,
                        "worker_count": spec.get('worker_count'),
                        "current_workers": len(worker_pids),
                        "worker_pids": worker_pids,
                    })

        return {
            "enabled": True,
            "pid": self.arbiter.dirty_arbiter_pid,
            "workers": workers,
            "apps": apps,
        }

    def show_config(self) -> dict:
        """
        Return current effective configuration.

        Returns:
            Dictionary of configuration values
        """
        cfg = self.arbiter.cfg
        config = {}

        # Get commonly needed config values
        config_keys = [
            'bind', 'workers', 'worker_class', 'threads', 'timeout',
            'graceful_timeout', 'keepalive', 'max_requests',
            'max_requests_jitter', 'worker_connections', 'preload_app',
            'daemon', 'pidfile', 'proc_name', 'reload',
            'dirty_workers', 'dirty_apps', 'dirty_timeout',
            'control_socket', 'control_socket_disable',
        ]

        for key in config_keys:
            try:
                value = getattr(cfg, key)
                # Convert non-serializable types
                if callable(value):
                    value = str(value)
                elif hasattr(value, '__class__') and not isinstance(
                        value, (str, int, float, bool, list, dict, type(None))):
                    value = str(value)
                config[key] = value
            except AttributeError:
                pass

        return config

    def show_stats(self) -> dict:
        """
        Return server statistics.

        Returns:
            Dictionary with:
            - uptime: Seconds since arbiter started
            - pid: Arbiter PID
            - workers_current: Current number of workers
            - workers_spawned: Total workers spawned
            - workers_killed: Total workers killed (if tracked)
            - reloads: Number of reloads (if tracked)
        """
        stats = getattr(self.arbiter, '_stats', {})
        start_time = stats.get('start_time')

        uptime = None
        if start_time:
            uptime = round(time.time() - start_time, 2)

        return {
            "uptime": uptime,
            "pid": self.arbiter.pid,
            "workers_current": len(self.arbiter.WORKERS),
            "workers_target": self.arbiter.num_workers,
            "workers_spawned": stats.get('workers_spawned', 0),
            "workers_killed": stats.get('workers_killed', 0),
            "reloads": stats.get('reloads', 0),
            "dirty_arbiter_pid": self.arbiter.dirty_arbiter_pid or None,
        }

    def show_listeners(self) -> dict:
        """
        Return bound socket information.

        Returns:
            Dictionary with listeners list
        """
        listeners = []

        for lnr in self.arbiter.LISTENERS:
            addr = str(lnr)
            listener_info = {
                "address": addr,
                "fd": lnr.fileno(),
            }

            # Try to get socket family
            try:
                sock = lnr.sock
                if sock.family == socket.AF_UNIX:
                    listener_info["type"] = "unix"
                elif sock.family == socket.AF_INET:
                    listener_info["type"] = "tcp"
                elif sock.family == socket.AF_INET6:
                    listener_info["type"] = "tcp6"
            except Exception:
                listener_info["type"] = "unknown"

            listeners.append(listener_info)

        return {"listeners": listeners, "count": len(listeners)}

    def worker_add(self, count: int = 1) -> dict:
        """
        Increase worker count.

        Args:
            count: Number of workers to add (default 1)

        Returns:
            Dictionary with added count and new total
        """
        count = max(1, int(count))
        old_count = self.arbiter.num_workers
        self.arbiter.num_workers += count

        # Wake up the arbiter to spawn workers
        self.arbiter.wakeup()

        return {
            "added": count,
            "previous": old_count,
            "total": self.arbiter.num_workers,
        }

    def worker_remove(self, count: int = 1) -> dict:
        """
        Decrease worker count.

        Args:
            count: Number of workers to remove (default 1)

        Returns:
            Dictionary with removed count and new total
        """
        count = max(1, int(count))
        old_count = self.arbiter.num_workers

        # Don't go below 1 worker
        new_count = max(1, old_count - count)
        actual_removed = old_count - new_count

        self.arbiter.num_workers = new_count

        # Wake up the arbiter to kill excess workers
        self.arbiter.wakeup()

        return {
            "removed": actual_removed,
            "previous": old_count,
            "total": new_count,
        }

    def worker_kill(self, pid: int) -> dict:
        """
        Gracefully terminate a specific worker.

        Args:
            pid: Worker process ID

        Returns:
            Dictionary with killed PID or error
        """
        pid = int(pid)

        if pid not in self.arbiter.WORKERS:
            return {
                "success": False,
                "error": f"Worker {pid} not found",
            }

        try:
            os.kill(pid, signal.SIGTERM)
            return {
                "success": True,
                "killed": pid,
            }
        except OSError as e:
            return {
                "success": False,
                "error": str(e),
            }

    def dirty_add(self, count: int = 1) -> dict:
        """
        Spawn additional dirty workers.

        Sends a MANAGE message to the dirty arbiter to spawn workers.

        Args:
            count: Number of dirty workers to add (default 1)

        Returns:
            Dictionary with added count or error
        """
        if not self.arbiter.dirty_arbiter_pid:
            return {
                "success": False,
                "error": "Dirty arbiter not running",
            }

        count = max(1, int(count))
        return self._send_manage_message("add", count)

    def dirty_remove(self, count: int = 1) -> dict:
        """
        Remove dirty workers.

        Sends a MANAGE message to the dirty arbiter to remove workers.

        Args:
            count: Number of dirty workers to remove (default 1)

        Returns:
            Dictionary with removed count or error
        """
        if not self.arbiter.dirty_arbiter_pid:
            return {
                "success": False,
                "error": "Dirty arbiter not running",
            }

        count = max(1, int(count))
        return self._send_manage_message("remove", count)

    def _send_manage_message(self, operation: str, count: int) -> dict:
        """
        Send a worker management message to the dirty arbiter.

        Args:
            operation: "add" or "remove"
            count: Number of workers to add/remove

        Returns:
            Dictionary with result or error
        """
        # Get socket path from arbiter object or environment
        dirty_socket_path = None
        if hasattr(self.arbiter, 'dirty_arbiter') and self.arbiter.dirty_arbiter:
            dirty_socket_path = getattr(
                self.arbiter.dirty_arbiter, 'socket_path', None
            )
        if not dirty_socket_path:
            dirty_socket_path = os.environ.get('GUNICORN_DIRTY_SOCKET')
        if not dirty_socket_path:
            return {
                "success": False,
                "error": "Cannot find dirty arbiter socket path",
            }

        try:
            from gunicorn.dirty.protocol import (
                DirtyProtocol, MANAGE_OP_ADD, MANAGE_OP_REMOVE
            )

            op = MANAGE_OP_ADD if operation == "add" else MANAGE_OP_REMOVE

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect(dirty_socket_path)

            # Send manage request
            request = {
                "type": DirtyProtocol.MSG_TYPE_MANAGE,
                "id": 1,
                "op": op,
                "count": count,
            }
            DirtyProtocol.write_message(sock, request)

            # Read response
            response = DirtyProtocol.read_message(sock)
            sock.close()

            if response.get("type") == DirtyProtocol.MSG_TYPE_RESPONSE:
                return response.get("result", {"success": True})
            elif response.get("type") == DirtyProtocol.MSG_TYPE_ERROR:
                error = response.get("error", {})
                return {
                    "success": False,
                    "error": error.get("message", str(error)),
                }
            else:
                return {
                    "success": False,
                    "error": f"Unexpected response type: {response.get('type')}",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def reload(self) -> dict:
        """
        Trigger graceful reload (equivalent to SIGHUP).

        Returns:
            Dictionary with status
        """
        # Send HUP to self to trigger reload
        os.kill(self.arbiter.pid, signal.SIGHUP)
        return {"status": "reloading"}

    def reopen(self) -> dict:
        """
        Reopen log files (equivalent to SIGUSR1).

        Returns:
            Dictionary with status
        """
        os.kill(self.arbiter.pid, signal.SIGUSR1)
        return {"status": "reopening"}

    def shutdown(self, mode: str = "graceful") -> dict:
        """
        Initiate shutdown.

        Args:
            mode: "graceful" (SIGTERM) or "quick" (SIGINT)

        Returns:
            Dictionary with status
        """
        if mode == "quick":
            os.kill(self.arbiter.pid, signal.SIGINT)
        else:
            os.kill(self.arbiter.pid, signal.SIGTERM)

        return {"status": "shutting_down", "mode": mode}

    def show_all(self) -> dict:
        """
        Return overview of all processes (arbiter, web workers, dirty arbiter, dirty workers).

        Returns:
            Dictionary with complete process hierarchy
        """
        now = time.monotonic()

        # Arbiter info
        arbiter_info = {
            "pid": self.arbiter.pid,
            "type": "arbiter",
            "role": "master",
        }

        # Web workers (HTTP workers)
        web_workers = []
        for pid, worker in self.arbiter.WORKERS.items():
            try:
                last_update = worker.tmp.last_update()
                last_heartbeat = round(now - last_update, 2)
            except (OSError, ValueError):
                last_heartbeat = None

            web_workers.append({
                "pid": pid,
                "type": "web",
                "age": worker.age,
                "booted": worker.booted,
                "last_heartbeat": last_heartbeat,
            })

        # Sort by age
        web_workers.sort(key=lambda w: w["age"])

        # Dirty arbiter info (runs in separate process)
        dirty_arbiter_info = None
        dirty_workers = []

        if self.arbiter.dirty_arbiter_pid:
            dirty_arbiter_info = {
                "pid": self.arbiter.dirty_arbiter_pid,
                "type": "dirty_arbiter",
                "role": "dirty master",
            }

            # Query dirty arbiter for worker info via its socket
            dirty_workers = self._query_dirty_workers()

        return {
            "arbiter": arbiter_info,
            "web_workers": web_workers,
            "web_worker_count": len(web_workers),
            "dirty_arbiter": dirty_arbiter_info,
            "dirty_workers": dirty_workers,
            "dirty_worker_count": len(dirty_workers),
        }

    def _query_dirty_workers(self) -> list:
        """
        Query the dirty arbiter for worker information.

        Connects to the dirty arbiter socket and sends a status request.

        Returns:
            List of dirty worker info dicts, or empty list on error
        """
        # Get socket path from arbiter object or environment
        dirty_socket_path = None
        if hasattr(self.arbiter, 'dirty_arbiter') and self.arbiter.dirty_arbiter:
            dirty_socket_path = getattr(self.arbiter.dirty_arbiter, 'socket_path', None)
        if not dirty_socket_path:
            dirty_socket_path = os.environ.get('GUNICORN_DIRTY_SOCKET')
        if not dirty_socket_path:
            return []

        try:
            from gunicorn.dirty.protocol import DirtyProtocol

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(dirty_socket_path)

            # Send status request
            request = {
                "type": DirtyProtocol.MSG_TYPE_STATUS,
                "id": "ctl-status-1",
            }
            DirtyProtocol.write_message(sock, request)

            # Read response
            response = DirtyProtocol.read_message(sock)
            sock.close()

            if response.get("type") == DirtyProtocol.MSG_TYPE_RESPONSE:
                result = response.get("result", {})
                return result.get("workers", [])

        except Exception:
            pass

        return []

    def help(self) -> dict:
        """
        Return list of available commands.

        Returns:
            Dictionary with commands and descriptions
        """
        commands = {
            "show all": "Show all processes (arbiter, web workers, dirty workers)",
            "show workers": "List HTTP workers with their status",
            "show dirty": "List dirty workers and apps",
            "show config": "Show current effective configuration",
            "show stats": "Show server statistics",
            "show listeners": "Show bound sockets",
            "worker add [N]": "Spawn N workers (default 1)",
            "worker remove [N]": "Remove N workers (default 1)",
            "worker kill <PID>": "Gracefully terminate specific worker",
            "dirty add [N]": "Spawn N dirty workers (default 1)",
            "dirty remove [N]": "Remove N dirty workers (default 1)",
            "reload": "Graceful reload (HUP)",
            "reopen": "Reopen log files (USR1)",
            "shutdown [graceful|quick]": "Shutdown server (TERM/INT)",
            "help": "Show this help message",
        }
        return {"commands": commands}
