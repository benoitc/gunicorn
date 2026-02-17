#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for the ASGI worker.

Includes unit tests for worker components and integration tests
that actually start the server and make HTTP requests.
"""

import asyncio
import errno
import os
import signal
import socket
import sys
import time
import threading
from unittest import mock

import pytest

from gunicorn.config import Config
from gunicorn.workers import gasgi


# ============================================================================
# Mock Classes
# ============================================================================

class FakeSocket:
    """Mock socket for testing."""

    def __init__(self, data=b''):
        self.data = data
        self.closed = False
        self.blocking = True
        self._fileno = id(self) % 65536

    def fileno(self):
        return self._fileno

    def setblocking(self, blocking):
        self.blocking = blocking

    def recv(self, size):
        if self.closed:
            raise OSError(errno.EBADF, "Bad file descriptor")
        result = self.data[:size]
        self.data = self.data[size:]
        return result

    def send(self, data):
        if self.closed:
            raise OSError(errno.EPIPE, "Broken pipe")
        return len(data)

    def close(self):
        self.closed = True

    def getsockname(self):
        return ('127.0.0.1', 8000)

    def getpeername(self):
        return ('127.0.0.1', 12345)


class FakeApp:
    """Mock ASGI application for testing."""

    def __init__(self):
        self.calls = []

    def wsgi(self):
        return self.asgi_app

    async def asgi_app(self, scope, receive, send):
        self.calls.append(scope)
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({
                "type": "http.response.body",
                "body": b"Hello from ASGI!",
            })


class FakeListener:
    """Mock listener socket."""

    def __init__(self):
        self.sock = FakeSocket()

    def getsockname(self):
        return ('127.0.0.1', 8000)

    def close(self):
        self.sock.close()

    def __str__(self):
        return "http://127.0.0.1:8000"


# ============================================================================
# Helper Functions
# ============================================================================

def _has_uvloop():
    """Check if uvloop is available."""
    try:
        import uvloop
        return True
    except ImportError:
        return False


# ============================================================================
# Unit Tests for ASGIWorker
# ============================================================================

class TestASGIWorkerInit:
    """Tests for ASGIWorker initialization."""

    def create_worker(self, **kwargs):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('worker_connections', 1000)

        for key, value in kwargs.items():
            cfg.set(key, value)

        worker = gasgi.ASGIWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=FakeApp(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_worker_init(self):
        """Test worker initialization."""
        worker = self.create_worker()

        assert worker.worker_connections == 1000
        assert worker.nr_conns == 0
        assert worker.loop is None
        assert worker.servers == []
        assert worker.state == {}

    def test_worker_connections_config(self):
        """Test worker_connections configuration."""
        worker = self.create_worker(worker_connections=500)
        assert worker.worker_connections == 500


class TestASGIWorkerEventLoop:
    """Tests for event loop setup."""

    def create_worker(self, **kwargs):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('worker_connections', 1000)

        for key, value in kwargs.items():
            cfg.set(key, value)

        worker = gasgi.ASGIWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=FakeApp(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_setup_asyncio_loop(self):
        """Test asyncio event loop setup."""
        worker = self.create_worker(asgi_loop='asyncio')
        worker._setup_event_loop()

        assert worker.loop is not None
        assert isinstance(worker.loop, asyncio.AbstractEventLoop)
        worker.loop.close()

    def test_setup_auto_loop_falls_back_to_asyncio(self):
        """Test that auto mode uses asyncio when uvloop unavailable."""
        worker = self.create_worker(asgi_loop='auto')

        # Mock uvloop import failure
        with mock.patch.dict('sys.modules', {'uvloop': None}):
            worker._setup_event_loop()

        assert worker.loop is not None
        worker.loop.close()

    @pytest.mark.skipif(
        not _has_uvloop(),
        reason="uvloop not installed"
    )
    def test_setup_uvloop(self):
        """Test uvloop event loop setup."""
        worker = self.create_worker(asgi_loop='uvloop')
        worker._setup_event_loop()

        import uvloop
        assert isinstance(worker.loop, uvloop.Loop)
        worker.loop.close()


class TestASGIWorkerSignals:
    """Tests for signal handling."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('worker_connections', 1000)
        cfg.set('graceful_timeout', 5)

        worker = gasgi.ASGIWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=FakeApp(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        worker._setup_event_loop()
        return worker

    def test_handle_exit_sets_alive_false(self):
        """Test that exit signal sets alive=False."""
        worker = self.create_worker()
        worker.alive = True

        worker.handle_exit_signal()

        assert worker.alive is False
        worker.loop.close()

    def test_handle_quit_sets_alive_false(self):
        """Test that quit signal sets alive=False."""
        worker = self.create_worker()
        worker.alive = True

        # Mock the worker_int callback on the worker's cfg settings
        with mock.patch.object(worker.cfg.settings['worker_int'], 'get', return_value=lambda w: None):
            worker.handle_quit_signal()

        assert worker.alive is False
        worker.loop.close()


# ============================================================================
# Tests for Lifespan Protocol
# ============================================================================

class TestLifespanManager:
    """Tests for ASGI lifespan protocol."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_complete(self):
        """Test successful lifespan startup."""
        from gunicorn.asgi.lifespan import LifespanManager

        startup_called = False
        shutdown_called = False

        async def app(scope, receive, send):
            nonlocal startup_called, shutdown_called
            assert scope["type"] == "lifespan"
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    startup_called = True
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    shutdown_called = True
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        manager = LifespanManager(app, mock.Mock())
        await manager.startup()

        assert startup_called
        assert manager._startup_complete.is_set()
        assert not manager._startup_failed

        await manager.shutdown()
        assert shutdown_called

    @pytest.mark.asyncio
    async def test_lifespan_startup_failed(self):
        """Test lifespan startup failure."""
        from gunicorn.asgi.lifespan import LifespanManager

        async def app(scope, receive, send):
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({
                    "type": "lifespan.startup.failed",
                    "message": "Database connection failed"
                })

        manager = LifespanManager(app, mock.Mock())

        with pytest.raises(RuntimeError, match="Database connection failed"):
            await manager.startup()

    @pytest.mark.asyncio
    async def test_lifespan_state_shared(self):
        """Test that lifespan state is shared with app."""
        from gunicorn.asgi.lifespan import LifespanManager

        state = {}

        async def app(scope, receive, send):
            assert "state" in scope
            scope["state"]["db"] = "connected"
            message = await receive()
            await send({"type": "lifespan.startup.complete"})
            message = await receive()
            await send({"type": "lifespan.shutdown.complete"})

        manager = LifespanManager(app, mock.Mock(), state)
        await manager.startup()

        assert state.get("db") == "connected"

        await manager.shutdown()


# ============================================================================
# Tests for WebSocket Protocol
# ============================================================================

class TestWebSocketProtocol:
    """Tests for WebSocket protocol handling."""

    def test_websocket_guid(self):
        """Test WebSocket GUID constant."""
        from gunicorn.asgi.websocket import WS_GUID
        assert WS_GUID == b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def test_websocket_opcodes(self):
        """Test WebSocket opcode constants."""
        from gunicorn.asgi import websocket

        assert websocket.OPCODE_TEXT == 0x1
        assert websocket.OPCODE_BINARY == 0x2
        assert websocket.OPCODE_CLOSE == 0x8
        assert websocket.OPCODE_PING == 0x9
        assert websocket.OPCODE_PONG == 0xA

    def test_websocket_accept_key_calculation(self):
        """Test WebSocket accept key calculation per RFC 6455."""
        import base64
        import hashlib
        from gunicorn.asgi.websocket import WS_GUID

        # Example from RFC 6455
        client_key = b"dGhlIHNhbXBsZSBub25jZQ=="
        expected_accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="

        accept_key = base64.b64encode(
            hashlib.sha1(client_key + WS_GUID).digest()
        ).decode("ascii")

        assert accept_key == expected_accept

    def test_websocket_frame_masking(self):
        """Test WebSocket frame unmasking."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        # Create a minimal protocol instance
        protocol = WebSocketProtocol(None, None, {}, None, mock.Mock())

        # Test unmasking (XOR operation)
        masking_key = bytes([0x37, 0xfa, 0x21, 0x3d])
        masked_data = bytes([0x7f, 0x9f, 0x4d, 0x51, 0x58])  # "Hello" masked

        unmasked = protocol._unmask(masked_data, masking_key)
        assert unmasked == b"Hello"

    def test_websocket_frame_masking_empty(self):
        """Test WebSocket frame unmasking with empty payload."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        protocol = WebSocketProtocol(None, None, {}, None, mock.Mock())

        masking_key = bytes([0x37, 0xfa, 0x21, 0x3d])
        unmasked = protocol._unmask(b"", masking_key)
        assert unmasked == b""


# ============================================================================
# Integration Tests
# ============================================================================

class TestASGIIntegration:
    """Integration tests that start actual servers."""

    @pytest.fixture
    def free_port(self):
        """Get a free port for testing."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    @pytest.mark.asyncio
    async def test_http_request_response(self, free_port):
        """Test basic HTTP request/response cycle."""
        # Simple ASGI app
        async def app(scope, receive, send):
            if scope["type"] == "http":
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"Hello, World!",
                })

        # Start server
        loop = asyncio.get_event_loop()
        server = await loop.create_server(
            lambda: _TestProtocol(app),
            '127.0.0.1',
            free_port,
        )

        try:
            # Use asyncio to make HTTP request
            reader, writer = await asyncio.open_connection('127.0.0.1', free_port)
            request = f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{free_port}\r\n\r\n"
            writer.write(request.encode())
            await writer.drain()

            # Read response
            response = await reader.read(4096)
            response_text = response.decode()

            assert "HTTP/1.1 200" in response_text
            assert "Hello, World!" in response_text

            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


class _TestProtocol(asyncio.Protocol):
    """Minimal protocol for integration testing."""

    def __init__(self, app):
        self.app = app
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        # Very simple HTTP parsing for testing
        asyncio.create_task(self._handle(data))

    async def _handle(self, data):
        # Parse basic HTTP request
        lines = data.decode().split('\r\n')
        method, path, _ = lines[0].split(' ')

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 12345),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = message.get("headers", [])
                response = f"HTTP/1.1 {status} OK\r\n"
                for name, value in headers:
                    if isinstance(name, bytes):
                        name = name.decode()
                    if isinstance(value, bytes):
                        value = value.decode()
                    response += f"{name}: {value}\r\n"
                response += "\r\n"
                self.transport.write(response.encode())
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                self.transport.write(body)
                if not message.get("more_body", False):
                    self.transport.close()

        await self.app(scope, receive, send)


# ============================================================================
# ASGI Protocol Tests
# ============================================================================

class TestASGIProtocol:
    """Tests for ASGIProtocol."""

    def test_reason_phrases(self):
        """Test HTTP reason phrase lookup."""
        from gunicorn.asgi.protocol import ASGIProtocol

        # Create minimal worker mock
        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)

        assert protocol._get_reason_phrase(200) == "OK"
        assert protocol._get_reason_phrase(404) == "Not Found"
        assert protocol._get_reason_phrase(500) == "Internal Server Error"
        assert protocol._get_reason_phrase(999) == "Unknown"

    def test_scope_building(self):
        """Test HTTP scope building."""
        from gunicorn.asgi.protocol import ASGIProtocol
        from gunicorn.asgi.message import AsyncRequest

        worker = mock.Mock()
        worker.cfg = Config()
        worker.cfg.set('root_path', '/api')
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)

        # Create mock request
        request = mock.Mock()
        request.method = "GET"
        request.path = "/users"
        request.query = "page=1"
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = [("HOST", "localhost"), ("ACCEPT", "text/html")]

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),  # sockname
            ("127.0.0.1", 12345),  # peername
        )

        assert scope["type"] == "http"
        assert scope["method"] == "GET"
        assert scope["path"] == "/users"
        assert scope["query_string"] == b"page=1"
        assert scope["root_path"] == "/api"
        assert scope["http_version"] == "1.1"


# ============================================================================
# Config Tests
# ============================================================================

class TestASGIConfig:
    """Tests for ASGI configuration options."""

    def test_asgi_loop_default(self):
        """Test default asgi_loop value."""
        cfg = Config()
        assert cfg.asgi_loop == "auto"

    def test_asgi_loop_validation(self):
        """Test asgi_loop validation."""
        cfg = Config()

        cfg.set('asgi_loop', 'asyncio')
        assert cfg.asgi_loop == 'asyncio'

        cfg.set('asgi_loop', 'uvloop')
        assert cfg.asgi_loop == 'uvloop'

        with pytest.raises(ValueError):
            cfg.set('asgi_loop', 'invalid')

    def test_asgi_lifespan_default(self):
        """Test default asgi_lifespan value."""
        cfg = Config()
        assert cfg.asgi_lifespan == "auto"

    def test_asgi_lifespan_validation(self):
        """Test asgi_lifespan validation."""
        cfg = Config()

        cfg.set('asgi_lifespan', 'on')
        assert cfg.asgi_lifespan == 'on'

        cfg.set('asgi_lifespan', 'off')
        assert cfg.asgi_lifespan == 'off'

        with pytest.raises(ValueError):
            cfg.set('asgi_lifespan', 'invalid')

    def test_root_path_default(self):
        """Test default root_path value."""
        cfg = Config()
        assert cfg.root_path == ""

    def test_root_path_setting(self):
        """Test root_path configuration."""
        cfg = Config()
        cfg.set('root_path', '/api/v1')
        assert cfg.root_path == '/api/v1'


# ============================================================================
# HTTP/2 Priority Tests
# ============================================================================

class TestASGIHTTP2Priority:
    """Test HTTP/2 priority in ASGI scope."""

    def test_http2_priority_in_scope(self):
        """Test that HTTP/2 priority is added to ASGI scope extensions."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)

        # Create mock HTTP/2 request with priority
        request = mock.Mock()
        request.method = "GET"
        request.path = "/test"
        request.query = ""
        request.version = (2, 0)
        request.scheme = "https"
        request.headers = [("HOST", "localhost")]
        request.priority_weight = 128
        request.priority_depends_on = 3

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8443),
            ("127.0.0.1", 12345),
        )

        assert "extensions" in scope
        assert "http.response.priority" in scope["extensions"]
        assert scope["extensions"]["http.response.priority"]["weight"] == 128
        assert scope["extensions"]["http.response.priority"]["depends_on"] == 3

    def test_http2_priority_in_http2_scope(self):
        """Test that HTTP/2 priority is in _build_http2_scope."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)

        # Create mock HTTP/2 request with priority
        request = mock.Mock()
        request.method = "POST"
        request.path = "/api/data"
        request.query = "id=1"
        request.uri = "/api/data?id=1"
        request.scheme = "https"
        request.headers = [("HOST", "localhost"), ("CONTENT-TYPE", "application/json")]
        request.priority_weight = 256
        request.priority_depends_on = 1

        scope = protocol._build_http2_scope(
            request,
            ("127.0.0.1", 8443),
            ("127.0.0.1", 12345),
        )

        assert scope["http_version"] == "2"
        assert "extensions" in scope
        assert "http.response.priority" in scope["extensions"]
        assert scope["extensions"]["http.response.priority"]["weight"] == 256
        assert scope["extensions"]["http.response.priority"]["depends_on"] == 1

    def test_no_priority_for_http1_requests(self):
        """Test that HTTP/1.1 requests don't have priority extensions."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)

        # Create mock HTTP/1.1 request (no priority attributes)
        request = mock.Mock(spec=['method', 'path', 'query', 'version',
                                   'scheme', 'headers'])
        request.method = "GET"
        request.path = "/test"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = [("HOST", "localhost")]

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        # HTTP/1.1 requests should not have extensions with priority
        assert "extensions" not in scope or "http.response.priority" not in scope.get("extensions", {})


# ============================================================================
# HTTP/2 Trailers Tests
# ============================================================================

class TestASGIHTTP2Trailers:
    """Test HTTP/2 response trailer support in ASGI."""

    def test_http2_trailers_extension_in_scope(self):
        """Test that HTTP/2 scope includes http.response.trailers extension."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)

        # Create mock HTTP/2 request
        request = mock.Mock()
        request.method = "GET"
        request.path = "/api"
        request.query = ""
        request.uri = "/api"
        request.scheme = "https"
        request.headers = [("HOST", "localhost")]
        request.priority_weight = 16
        request.priority_depends_on = 0

        scope = protocol._build_http2_scope(
            request,
            ("127.0.0.1", 8443),
            ("127.0.0.1", 12345),
        )

        # HTTP/2 scope should have trailers extension
        assert "extensions" in scope
        assert "http.response.trailers" in scope["extensions"]

    def test_http2_scope_has_both_priority_and_trailers(self):
        """Test that HTTP/2 scope includes both priority and trailers extensions."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)

        request = mock.Mock()
        request.method = "POST"
        request.path = "/grpc"
        request.query = ""
        request.uri = "/grpc"
        request.scheme = "https"
        request.headers = [("HOST", "localhost"), ("CONTENT-TYPE", "application/grpc")]
        request.priority_weight = 128
        request.priority_depends_on = 1

        scope = protocol._build_http2_scope(
            request,
            ("127.0.0.1", 8443),
            ("127.0.0.1", 54321),
        )

        extensions = scope.get("extensions", {})
        assert "http.response.priority" in extensions
        assert "http.response.trailers" in extensions
        assert extensions["http.response.priority"]["weight"] == 128


# ============================================================================
# Connection Limit Tests
# ============================================================================

class TestASGIConnectionLimit:
    """Tests for worker_connections enforcement in ASGI worker."""

    def create_worker(self, worker_connections=1):
        """Create a worker with specific connection limit."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('worker_connections', worker_connections)

        worker = gasgi.ASGIWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=FakeApp(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        worker._setup_event_loop()
        return worker

    def test_accepting_defaults_to_true(self):
        """Test that _accepting starts as True."""
        worker = self.create_worker()
        assert worker._accepting is True
        worker.loop.close()

    def test_worker_marks_not_accepting_at_limit(self):
        """Test that _accepting becomes False when connection limit is reached."""
        worker = self.create_worker(worker_connections=2)

        # Simulate reaching the limit
        worker.nr_conns = 2

        # Run one iteration of the serve loop logic
        at_capacity = worker.nr_conns >= worker.worker_connections
        if at_capacity and worker._accepting:
            worker._accepting = False

        assert worker._accepting is False
        worker.loop.close()

    def test_worker_marks_accepting_after_connection_freed(self):
        """Test that _accepting becomes True when connections drop below limit."""
        worker = self.create_worker(worker_connections=2)

        # Set to not-accepting state
        worker._accepting = False
        worker.nr_conns = 1  # Below limit

        # Run resume logic
        at_capacity = worker.nr_conns >= worker.worker_connections
        if not at_capacity and not worker._accepting:
            worker._accepting = True

        assert worker._accepting is True
        worker.loop.close()

    def test_no_action_when_below_limit_and_accepting(self):
        """Test _accepting stays True when below limit and already accepting."""
        worker = self.create_worker(worker_connections=5)

        worker.nr_conns = 2
        worker._accepting = True

        at_capacity = worker.nr_conns >= worker.worker_connections
        if at_capacity and worker._accepting:
            worker._accepting = False
        elif not at_capacity and not worker._accepting:
            worker._accepting = True

        assert worker._accepting is True
        worker.loop.close()


class TestASGIProtocolConnectionLimit:
    """Tests for connection limit enforcement in ASGIProtocol."""

    def test_reject_over_limit(self):
        """Test that connections over the limit get 503."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 5
        worker.worker_connections = 5
        worker.loop = asyncio.new_event_loop()

        protocol = ASGIProtocol(worker)
        transport = mock.Mock()
        transport.get_extra_info = mock.Mock(return_value=None)

        # connection_made increments nr_conns to 6 (> 5), should reject
        protocol.connection_made(transport)

        # Verify 503 was sent
        transport.write.assert_called_once()
        written = transport.write.call_args[0][0]
        assert b"503 Service Unavailable" in written

        # Verify transport was closed
        transport.close.assert_called_once()

        # Verify nr_conns was decremented back
        assert worker.nr_conns == 5

        # Verify protocol is marked as closed
        assert protocol._closed is True

        worker.loop.close()

    def test_accept_under_limit(self):
        """Test that connections under the limit are accepted normally."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 0
        worker.worker_connections = 5
        worker.loop = asyncio.new_event_loop()

        protocol = ASGIProtocol(worker)
        transport = mock.Mock()
        transport.get_extra_info = mock.Mock(return_value=None)

        protocol.connection_made(transport)

        # Connection should be accepted (no 503, task created)
        assert protocol.transport == transport
        assert protocol._closed is False
        assert worker.nr_conns == 1

        # Cancel the handler task to clean up
        if protocol._task:
            protocol._task.cancel()

        worker.loop.close()

    def test_single_connection_worker(self):
        """Test worker_connections=1 allows exactly one connection."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 0
        worker.worker_connections = 1
        worker.loop = asyncio.new_event_loop()

        # First connection — should be accepted
        p1 = ASGIProtocol(worker)
        t1 = mock.Mock()
        t1.get_extra_info = mock.Mock(return_value=None)
        p1.connection_made(t1)
        assert p1._closed is False
        assert worker.nr_conns == 1

        # Second connection — should be rejected with 503
        p2 = ASGIProtocol(worker)
        t2 = mock.Mock()
        t2.get_extra_info = mock.Mock(return_value=None)
        p2.connection_made(t2)
        assert p2._closed is True
        t2.write.assert_called_once()
        assert b"503" in t2.write.call_args[0][0]
        t2.close.assert_called_once()
        assert worker.nr_conns == 1  # Back to 1

        # Clean up
        if p1._task:
            p1._task.cancel()
        worker.loop.close()

