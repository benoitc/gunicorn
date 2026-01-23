#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import signal
from unittest import mock

import pytest

import gunicorn.app.base
import gunicorn.arbiter
import gunicorn.errors
from gunicorn.config import ReusePort


class DummyApplication(gunicorn.app.base.BaseApplication):
    """
    Dummy application that has a default configuration.
    """

    def init(self, parser, opts, args):
        """No-op"""

    def load(self):
        """No-op"""

    def load_config(self):
        """No-op"""


@mock.patch('gunicorn.sock.close_sockets')
def test_arbiter_stop_closes_listeners(close_sockets):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    listener1 = mock.Mock()
    listener2 = mock.Mock()
    listeners = [listener1, listener2]
    arbiter.LISTENERS = listeners
    arbiter.stop()
    close_sockets.assert_called_with(listeners, True)


@mock.patch('gunicorn.sock.close_sockets')
def test_arbiter_stop_child_does_not_unlink_listeners(close_sockets):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.reexec_pid = os.getpid()
    arbiter.stop()
    close_sockets.assert_called_with([], False)


@mock.patch('gunicorn.sock.close_sockets')
def test_arbiter_stop_parent_does_not_unlink_listeners(close_sockets):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.master_pid = os.getppid()
    arbiter.stop()
    close_sockets.assert_called_with([], False)


@mock.patch('gunicorn.sock.close_sockets')
def test_arbiter_stop_does_not_unlink_systemd_listeners(close_sockets):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.systemd = True
    arbiter.stop()
    close_sockets.assert_called_with([], False)


@mock.patch('gunicorn.sock.close_sockets')
def test_arbiter_stop_does_not_unlink_when_using_reuse_port(close_sockets):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.cfg.settings['reuse_port'] = ReusePort()
    arbiter.cfg.settings['reuse_port'].set(True)
    arbiter.stop()
    close_sockets.assert_called_with([], False)


@mock.patch('os.getpid')
@mock.patch('os.fork')
@mock.patch('os.execvpe')
def test_arbiter_reexec_passing_systemd_sockets(execvpe, fork, getpid):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.LISTENERS = [mock.Mock(), mock.Mock()]
    arbiter.systemd = True
    fork.return_value = 0
    getpid.side_effect = [2, 3]
    arbiter.reexec()
    environ = execvpe.call_args[0][2]
    assert environ['GUNICORN_PID'] == '2'
    assert environ['LISTEN_FDS'] == '2'
    assert environ['LISTEN_PID'] == '3'


@mock.patch('os.getpid')
@mock.patch('os.fork')
@mock.patch('os.execvpe')
def test_arbiter_reexec_passing_gunicorn_sockets(execvpe, fork, getpid):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    listener1 = mock.Mock()
    listener2 = mock.Mock()
    listener1.fileno.return_value = 4
    listener2.fileno.return_value = 5
    arbiter.LISTENERS = [listener1, listener2]
    fork.return_value = 0
    getpid.side_effect = [2, 3]
    arbiter.reexec()
    environ = execvpe.call_args[0][2]
    assert environ['GUNICORN_FD'] == '4,5'
    assert environ['GUNICORN_PID'] == '2'


@mock.patch('os.fork')
def test_arbiter_reexec_limit_parent(fork):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.reexec_pid = ~os.getpid()
    arbiter.reexec()
    assert fork.called is False, "should not fork when there is already a child"


@mock.patch('os.fork')
def test_arbiter_reexec_limit_child(fork):
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.master_pid = ~os.getpid()
    arbiter.reexec()
    assert fork.called is False, "should not fork when arbiter is a child"


@mock.patch('os.fork')
def test_arbiter_calls_worker_exit(mock_os_fork):
    mock_os_fork.return_value = 0

    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.cfg.settings['worker_exit'] = mock.Mock()
    arbiter.pid = None
    mock_worker = mock.Mock()
    arbiter.worker_class = mock.Mock(return_value=mock_worker)
    try:
        arbiter.spawn_worker()
    except SystemExit:
        pass
    arbiter.cfg.worker_exit.assert_called_with(arbiter, mock_worker)


@mock.patch('os.waitpid')
def test_arbiter_reap_workers(mock_os_waitpid):
    mock_os_waitpid.side_effect = [(42, 0), (0, 0)]
    arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
    arbiter.cfg.settings['child_exit'] = mock.Mock()
    mock_worker = mock.Mock()
    arbiter.WORKERS = {42: mock_worker}
    arbiter.reap_workers()
    mock_worker.tmp.close.assert_called_with()
    arbiter.cfg.child_exit.assert_called_with(arbiter, mock_worker)


class PreloadedAppWithEnvSettings(DummyApplication):
    """
    Simple application that makes use of the 'preload' feature to
    start the application before spawning worker processes and sets
    environmental variable configuration settings.
    """

    def load_config(self):
        """Set the 'preload_app' and 'raw_env' settings in order to verify their
        interaction below.
        """
        self.cfg.set('raw_env', [
            'SOME_PATH=/tmp/something', 'OTHER_PATH=/tmp/something/else'])
        self.cfg.set('preload_app', True)

    def wsgi(self):
        """Assert that the expected environmental variables are set when
        the main entry point of this application is called as part of a
        'preloaded' application.
        """
        verify_env_vars()
        return super().wsgi()


def verify_env_vars():
    assert os.getenv('SOME_PATH') == '/tmp/something'
    assert os.getenv('OTHER_PATH') == '/tmp/something/else'


def test_env_vars_available_during_preload():
    """Ensure that configured environmental variables are set during the
    initial set up of the application (called from the .setup() method of
    the Arbiter) such that they are available during the initial loading
    of the WSGI application.
    """
    # Note that we aren't making any assertions here, they are made in the
    # dummy application object being loaded here instead.
    gunicorn.arbiter.Arbiter(PreloadedAppWithEnvSettings())


# ============================================================================
# Signal Handler Registration Tests
# ============================================================================

class TestSignalHandlerRegistration:
    """Tests for signal handler registration during arbiter initialization."""

    def test_init_signals_registers_all_signals(self):
        """Verify that init_signals registers handlers for all expected signals."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        with mock.patch('signal.signal') as mock_signal:
            arbiter.init_signals()

            # Verify all expected signals are registered
            registered_signals = {call[0][0] for call in mock_signal.call_args_list}
            expected_signals = set(arbiter.SIGNALS)
            expected_signals.add(signal.SIGCHLD)

            assert expected_signals.issubset(registered_signals), \
                f"Missing signals: {expected_signals - registered_signals}"

    def test_init_signals_creates_queue(self):
        """Verify that arbiter has a SimpleQueue for signals."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        # Verify SimpleQueue was created
        import queue
        assert isinstance(arbiter.SIG_QUEUE, queue.SimpleQueue)

    def test_sigchld_has_separate_handler(self):
        """Verify that SIGCHLD uses a separate signal handler from other signals."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        with mock.patch('signal.signal') as mock_signal:
            arbiter.init_signals()

            # Find the handler for SIGCHLD - uses signal_chld for async-signal-safety
            sigchld_calls = [c for c in mock_signal.call_args_list
                            if c[0][0] == signal.SIGCHLD]
            assert len(sigchld_calls) == 1
            assert sigchld_calls[0][0][1] == arbiter.signal_chld

            # Find handlers for other signals
            other_calls = [c for c in mock_signal.call_args_list
                          if c[0][0] in arbiter.SIGNALS]
            for call in other_calls:
                assert call[0][1] == arbiter.signal

    def test_signals_list_contains_expected(self):
        """Verify that SIGNALS list contains all expected signal types."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        expected = ['HUP', 'QUIT', 'INT', 'TERM', 'TTIN', 'TTOU',
                    'USR1', 'USR2', 'WINCH']
        for name in expected:
            sig = getattr(signal, f'SIG{name}')
            assert sig in arbiter.SIGNALS, f"SIG{name} not in SIGNALS list"


# ============================================================================
# Signal Queue Tests
# ============================================================================

class TestSignalQueue:
    """Tests for signal queueing and wakeup mechanism using SimpleQueue."""

    def test_signal_queued_on_receipt(self):
        """Verify that signals are queued when the signal handler is called."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        arbiter.signal(signal.SIGHUP, None)

        # Get the signal from the queue
        sig = arbiter.SIG_QUEUE.get_nowait()
        assert sig == signal.SIGHUP

    def test_multiple_signals_queued(self):
        """Verify that multiple signals can be queued."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        # Queue multiple signals
        arbiter.signal(signal.SIGHUP, None)
        arbiter.signal(signal.SIGTERM, None)
        arbiter.signal_chld(signal.SIGCHLD, None)

        signals = []
        while True:
            try:
                signals.append(arbiter.SIG_QUEUE.get_nowait())
            except Exception:
                break

        assert signal.SIGHUP in signals
        assert signal.SIGTERM in signals
        assert signal.SIGCHLD in signals

    def test_wakeup_puts_sentinel(self):
        """Verify that wakeup puts the WAKEUP_REQUEST sentinel to the queue."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        arbiter.wakeup()

        sig = arbiter.SIG_QUEUE.get_nowait()
        assert sig == arbiter.WAKEUP_REQUEST

    def test_wait_for_signals_returns_signals(self):
        """Verify that wait_for_signals returns queued signals."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        # Queue some signals
        arbiter.SIG_QUEUE.put_nowait(signal.SIGHUP)
        arbiter.SIG_QUEUE.put_nowait(signal.SIGTERM)

        signals = arbiter.wait_for_signals(timeout=0.1)

        assert signal.SIGHUP in signals
        assert signal.SIGTERM in signals

    def test_wait_for_signals_filters_wakeup_request(self):
        """Verify that WAKEUP_REQUEST sentinel is filtered from results."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())

        # Queue a wakeup request and a real signal
        arbiter.SIG_QUEUE.put_nowait(arbiter.WAKEUP_REQUEST)
        arbiter.SIG_QUEUE.put_nowait(signal.SIGHUP)

        signals = arbiter.wait_for_signals(timeout=0.1)

        assert arbiter.WAKEUP_REQUEST not in signals
        assert signal.SIGHUP in signals


# ============================================================================
# Reap Workers Tests
# ============================================================================

class TestReapWorkers:
    """Tests for worker reaping and exit status handling."""

    @mock.patch('os.waitpid')
    def test_reap_normal_exit(self, mock_waitpid):
        """Verify that a worker with normal exit (code 0) is properly reaped."""
        mock_waitpid.side_effect = [(42, 0), (0, 0)]

        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.settings['child_exit'] = mock.Mock()
        mock_worker = mock.Mock()
        arbiter.WORKERS = {42: mock_worker}

        arbiter.reap_workers()

        mock_worker.tmp.close.assert_called_once()
        arbiter.cfg.child_exit.assert_called_once_with(arbiter, mock_worker)
        assert 42 not in arbiter.WORKERS

    @mock.patch('os.waitpid')
    def test_reap_exit_with_error_code(self, mock_waitpid):
        """Verify that a worker exiting with non-zero code is logged."""
        # Exit code 1 (status = 1 << 8 = 256)
        mock_waitpid.side_effect = [(42, 256), (0, 0)]

        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.settings['child_exit'] = mock.Mock()
        mock_worker = mock.Mock()
        arbiter.WORKERS = {42: mock_worker}

        with mock.patch.object(arbiter.log, 'error') as mock_log:
            arbiter.reap_workers()

        # Should log the error exit
        assert any('exited with code' in str(call) for call in mock_log.call_args_list)

    @mock.patch('os.waitpid')
    def test_reap_worker_boot_error(self, mock_waitpid):
        """Verify that WORKER_BOOT_ERROR causes HaltServer."""
        # Exit code 3 (WORKER_BOOT_ERROR) = status 3 << 8 = 768
        mock_waitpid.side_effect = [(42, 768), (0, 0)]

        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.settings['child_exit'] = mock.Mock()
        mock_worker = mock.Mock()
        arbiter.WORKERS = {42: mock_worker}

        with pytest.raises(gunicorn.errors.HaltServer) as exc_info:
            arbiter.reap_workers()

        assert exc_info.value.exit_status == gunicorn.arbiter.Arbiter.WORKER_BOOT_ERROR

    @mock.patch('os.waitpid')
    def test_reap_app_load_error(self, mock_waitpid):
        """Verify that APP_LOAD_ERROR causes HaltServer."""
        # Exit code 4 (APP_LOAD_ERROR) = status 4 << 8 = 1024
        mock_waitpid.side_effect = [(42, 1024), (0, 0)]

        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.settings['child_exit'] = mock.Mock()
        mock_worker = mock.Mock()
        arbiter.WORKERS = {42: mock_worker}

        with pytest.raises(gunicorn.errors.HaltServer) as exc_info:
            arbiter.reap_workers()

        assert exc_info.value.exit_status == gunicorn.arbiter.Arbiter.APP_LOAD_ERROR

    @mock.patch('os.waitpid')
    def test_reap_killed_by_signal(self, mock_waitpid):
        """Verify that a worker killed by signal is properly identified."""
        # Status for SIGTERM (15) killed process
        mock_waitpid.side_effect = [(42, signal.SIGTERM), (0, 0)]

        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.settings['child_exit'] = mock.Mock()
        mock_worker = mock.Mock()
        arbiter.WORKERS = {42: mock_worker}

        # SIGTERM should be logged as info (expected during graceful shutdown)
        with mock.patch.object(arbiter.log, 'info') as mock_log:
            arbiter.reap_workers()

        # Should log the signal
        assert any('SIGTERM' in str(call) for call in mock_log.call_args_list)

    @mock.patch('os.waitpid')
    def test_reap_killed_by_sigkill_oom_hint(self, mock_waitpid):
        """Verify that SIGKILL adds OOM hint to log message."""
        # Status for SIGKILL (9) killed process
        mock_waitpid.side_effect = [(42, signal.SIGKILL), (0, 0)]

        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.settings['child_exit'] = mock.Mock()
        mock_worker = mock.Mock()
        arbiter.WORKERS = {42: mock_worker}

        with mock.patch.object(arbiter.log, 'error') as mock_log:
            arbiter.reap_workers()

        # Should include OOM hint
        log_messages = ' '.join(str(call) for call in mock_log.call_args_list)
        assert 'out of memory' in log_messages.lower()


# ============================================================================
# SIGHUP Reload Tests
# ============================================================================

class TestSighupReload:
    """Tests for SIGHUP (reload) handling."""

    @mock.patch('gunicorn.arbiter.Arbiter.spawn_worker')
    @mock.patch('gunicorn.arbiter.Arbiter.manage_workers')
    def test_reload_spawns_new_workers(self, mock_manage, mock_spawn):
        """Verify that reload spawns the configured number of workers."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.set('workers', 3)
        arbiter.LISTENERS = [mock.Mock()]
        arbiter.pidfile = None
        # Mock app.reload to prevent it from resetting config
        arbiter.app.reload = mock.Mock()
        # Mock setup to prevent it from resetting num_workers
        arbiter.setup = mock.Mock()

        arbiter.reload()

        assert mock_spawn.call_count == 3

    @mock.patch('gunicorn.arbiter.Arbiter.spawn_worker')
    @mock.patch('gunicorn.arbiter.Arbiter.manage_workers')
    def test_reload_calls_manage_workers(self, mock_manage, mock_spawn):
        """Verify that reload calls manage_workers after spawning."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.cfg.set('workers', 1)
        arbiter.LISTENERS = [mock.Mock()]
        arbiter.pidfile = None

        arbiter.reload()

        mock_manage.assert_called_once()

    @mock.patch('gunicorn.arbiter.Arbiter.spawn_worker')
    @mock.patch('gunicorn.arbiter.Arbiter.manage_workers')
    def test_reload_logs_hang_up(self, mock_manage, mock_spawn):
        """Verify that handle_hup logs the hang up message."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.LISTENERS = [mock.Mock()]
        arbiter.pidfile = None

        with mock.patch.object(arbiter.log, 'info') as mock_log:
            arbiter.handle_hup()

        # Check that "Hang up" was logged
        assert any('Hang up' in str(call) for call in mock_log.call_args_list)


# ============================================================================
# Worker Lifecycle Tests
# ============================================================================

class TestWorkerLifecycle:
    """Tests for worker spawning, killing, and lifecycle management."""

    @mock.patch('os.fork')
    def test_spawn_worker_adds_to_workers_dict(self, mock_fork):
        """Verify that spawn_worker adds the worker to WORKERS dict."""
        mock_fork.return_value = 12345  # Non-zero = parent process

        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.WORKERS = {}
        arbiter.pid = os.getpid()
        arbiter.LISTENERS = []

        pid = arbiter.spawn_worker()

        assert pid == 12345
        assert 12345 in arbiter.WORKERS
        assert arbiter.WORKERS[12345].age == arbiter.worker_age

    def test_kill_worker_sends_signal(self):
        """Verify that kill_worker sends the specified signal."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        mock_worker = mock.Mock()
        arbiter.WORKERS = {42: mock_worker}

        with mock.patch('os.kill') as mock_kill:
            arbiter.kill_worker(42, signal.SIGTERM)

        mock_kill.assert_called_once_with(42, signal.SIGTERM)

    def test_murder_workers_sends_sigabrt_first(self):
        """Verify that murder_workers sends SIGABRT on first timeout."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.timeout = 30

        mock_worker = mock.Mock()
        mock_worker.aborted = False
        # Simulate timeout by returning a very old update time
        mock_worker.tmp.last_update.return_value = 0
        arbiter.WORKERS = {42: mock_worker}

        with mock.patch('time.monotonic', return_value=100), \
             mock.patch.object(arbiter, 'kill_worker') as mock_kill:
            arbiter.murder_workers()

        mock_kill.assert_called_once_with(42, signal.SIGABRT)
        assert mock_worker.aborted is True

    def test_murder_workers_sends_sigkill_second(self):
        """Verify that murder_workers sends SIGKILL on second timeout."""
        arbiter = gunicorn.arbiter.Arbiter(DummyApplication())
        arbiter.timeout = 30

        mock_worker = mock.Mock()
        mock_worker.aborted = True  # Already aborted once
        mock_worker.tmp.last_update.return_value = 0
        arbiter.WORKERS = {42: mock_worker}

        with mock.patch('time.monotonic', return_value=100), \
             mock.patch.object(arbiter, 'kill_worker') as mock_kill:
            arbiter.murder_workers()

        mock_kill.assert_called_once_with(42, signal.SIGKILL)
