#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from datetime import datetime
import errno
import socket
import ssl
import sys

from gunicorn import http
from gunicorn.http import wsgi
from gunicorn import util
from gunicorn import sock as gunicorn_sock
from gunicorn.http.errors import InvalidH2CPreface
from gunicorn.http2 import negotiation
from gunicorn.http2.response import HTTP2Response
from gunicorn.workers import base

ALREADY_HANDLED = object()


class AsyncWorker(base.Worker):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections

    def timeout_ctx(self):
        raise NotImplementedError()

    def is_already_handled(self, respiter):
        # some workers will need to overload this function to raise a StopIteration
        return respiter == ALREADY_HANDLED

    def handle(self, listener, client, addr):
        req = None
        unread_preface = b""
        try:
            # Complete the handshake to ensure ALPN negotiation is done
            # (needed if do_handshake_on_connect is False)
            if isinstance(client, ssl.SSLSocket) and not self.cfg.do_handshake_on_connect:
                client.do_handshake()

            # Check if HTTP/2 was negotiated (for SSL connections)
            is_http2 = gunicorn_sock.is_http2_negotiated(client)

            if is_http2:
                # Handle HTTP/2 connection
                self.handle_http2(listener, client, addr)
                return

            if negotiation.prior_knowledge_allowed(self.cfg, addr):
                # HTTP/2 cleartext with prior knowledge (RFC 9113 section
                # 3.4). Peers outside forwarded_allow_ips never reach here
                # and are served HTTP/1.x as if the setting were off.
                matched, buf = negotiation.read_preface_blocking(client)
                if matched:
                    self.handle_http2(listener, client, addr, preface=buf)
                    return
                if negotiation.mismatch_is_error(self.cfg):
                    # A trusted peer on a prior-knowledge-only port must
                    # speak HTTP/2; anything else is a misconfiguration.
                    raise InvalidH2CPreface(buf)
                # Upgrade is enabled too, so this may be the HTTP/1 request
                # that carries it; fall through with the bytes preserved.
                unread_preface = buf

            parser = http.get_parser(self.cfg, client, addr)
            if unread_preface:
                parser.unreader.unread(unread_preface)
            try:
                listener_name = listener.getsockname()
                if not self.cfg.keepalive:
                    req = next(parser)
                    if self._try_h2c_upgrade(listener, req, parser, client,
                                             addr):
                        return
                    self.handle_request(listener_name, req, client, addr)
                else:
                    # keepalive loop
                    proxy_protocol_info = {}
                    while True:
                        req = None
                        with self.timeout_ctx():
                            req = next(parser)
                        if not req:
                            break
                        if self._try_h2c_upgrade(listener, req, parser, client,
                                                 addr):
                            return
                        if req.proxy_protocol_info:
                            proxy_protocol_info = req.proxy_protocol_info
                        else:
                            req.proxy_protocol_info = proxy_protocol_info
                        self.handle_request(listener_name, req, client, addr)
            except http.errors.NoMoreData as e:
                self.log.debug("Ignored premature client disconnection. %s", e)
            except StopIteration as e:
                self.log.debug("Closing connection. %s", e)
            except ssl.SSLError:
                # pass to next try-except level
                util.reraise(*sys.exc_info())
            except OSError:
                # pass to next try-except level
                util.reraise(*sys.exc_info())
            except Exception as e:
                self.handle_error(req, client, addr, e)
        except ssl.SSLError as e:
            if e.args[0] == ssl.SSL_ERROR_EOF:
                self.log.debug("ssl connection closed")
                client.close()
            else:
                self.log.debug("Error processing SSL request.")
                self.handle_error(req, client, addr, e)
        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("Socket error processing request.")
            else:
                if e.errno == errno.ECONNRESET:
                    self.log.debug("Ignoring connection reset")
                elif e.errno == errno.ENOTCONN:
                    self.log.debug("Ignoring socket not connected")
                else:
                    self.log.debug("Ignoring EPIPE")
        except BaseException as e:
            self.handle_error(req, client, addr, e)
        finally:
            util.close(client)

    def _try_h2c_upgrade(self, listener, req, parser, client, addr):
        """Switch to HTTP/2 if this request asks to upgrade.

        Returns True when the connection has been taken over. Any HTTP/2
        bytes the client pipelined behind the upgrade request are still in
        the parser's unreader, so they are handed on rather than dropped.

        The request body has to come out first: it shares that buffer, and
        taking the buffer before draining it would feed the payload to the
        HTTP/2 state machine as if it were frames.
        """
        if not negotiation.upgrade_allowed(self.cfg, addr):
            return False
        settings = negotiation.upgrade_settings(req)
        if settings is None:
            return False

        body = b""
        if req.body is not None:
            body = req.body.read() or b""
        pending = parser.unreader.take_buffered()
        util.write(client, negotiation.UPGRADE_101)
        self.handle_http2(listener, client, addr, preface=pending,
                          upgrade=(settings, req, body))
        return True

    def handle_http2(self, listener, client, addr, preface=b"",
                     upgrade=None):
        """Handle an HTTP/2 connection.

        Processes multiplexed HTTP/2 streams until the connection closes.

        ``preface`` carries connection preface bytes already read off the
        socket during cleartext negotiation. They have left the socket, so
        they have to be replayed into the HTTP/2 state machine here.
        """
        listener_name = listener.getsockname()

        try:
            h2_conn = http.get_parser(self.cfg, client, addr, http2_connection=True)
            if upgrade is not None:
                settings, http1_req, body = upgrade
                upgraded = h2_conn.initiate_upgrade(settings, http1_req, body)
            else:
                upgraded = None
                h2_conn.initiate_connection()
            if preface:
                # The preface alone cannot complete a request, so replaying
                # it yields no requests and nothing is dropped.
                h2_conn.receive_data(preface)

            if upgraded is not None:
                # The upgraded request is stream 1; serve it before the loop.
                self.handle_http2_request(listener.getsockname(), upgraded,
                                          client, addr, h2_conn)

            while not h2_conn.is_closed and self.alive:
                try:
                    requests = h2_conn.receive_data()
                except http.errors.NoMoreData:
                    self.log.debug("HTTP/2 connection closed by client")
                    break

                for req in requests:
                    try:
                        self.handle_http2_request(listener_name, req, client, addr, h2_conn)
                    except Exception as e:
                        self.log.exception("Error handling HTTP/2 request")
                        try:
                            h2_conn.send_error(req.stream.stream_id, 500, str(e))
                        except Exception:
                            pass
                    finally:
                        h2_conn.cleanup_stream(req.stream.stream_id)

        except ssl.SSLError as e:
            if e.args[0] == ssl.SSL_ERROR_EOF:
                self.log.debug("HTTP/2 SSL connection closed")
            else:
                self.log.debug("HTTP/2 SSL error: %s", e)
        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("HTTP/2 socket error")
        except Exception as e:
            self.log.exception("HTTP/2 connection error: %s", e)

    def handle_http2_request(self, listener_name, req, sock, addr, h2_conn):
        """Handle a single HTTP/2 request."""
        stream_id = req.stream.stream_id
        request_start = datetime.now()
        environ = {}
        resp = None

        try:
            self.cfg.pre_request(self, req)
            # The response frames itself as HTTP/2, so the body streams out
            # instead of being collected first, and the no-body and sendfile
            # rules come from Response unchanged.
            resp, environ = wsgi.create(req, sock, addr, listener_name,
                                        self.cfg,
                                        response_class=HTTP2Response,
                                        response_args=(h2_conn, stream_id))
            environ["wsgi.multithread"] = True
            environ["HTTP_VERSION"] = "2"

            self.nr += 1
            if self.nr >= self.max_requests:
                if self.alive:
                    self.log.info("Autorestarting worker after current request.")
                    self.alive = False

            # Run WSGI app
            respiter = self.wsgi(environ, resp.start_response)
            if self.is_already_handled(respiter):
                return

            # Stream each chunk as the application produces it
            try:
                for item in respiter:
                    resp.write(item)
                resp.close()
            finally:
                if hasattr(respiter, "close"):
                    respiter.close()

            request_time = datetime.now() - request_start
            self.log.access(resp, req, environ, request_time)

        except Exception:
            self.log.exception("Error handling HTTP/2 request")
            raise
        finally:
            try:
                self.cfg.post_request(self, req, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")

    def handle_request(self, listener_name, req, sock, addr):
        request_start = datetime.now()
        environ = {}
        resp = None
        try:
            self.cfg.pre_request(self, req)
            resp, environ = wsgi.create(req, sock, addr,
                                        listener_name, self.cfg)
            environ["wsgi.multithread"] = True
            self.nr += 1
            if self.nr >= self.max_requests:
                if self.alive:
                    self.log.info("Autorestarting worker after current request.")
                    self.alive = False

            if not self.alive or not self.cfg.keepalive:
                resp.force_close()

            respiter = self.wsgi(environ, resp.start_response)
            if self.is_already_handled(respiter):
                return False
            try:
                if isinstance(respiter, environ['wsgi.file_wrapper']):
                    resp.write_file(respiter)
                else:
                    for item in respiter:
                        resp.write(item)
                resp.close()
            finally:
                request_time = datetime.now() - request_start
                self.log.access(resp, req, environ, request_time)
                if hasattr(respiter, "close"):
                    respiter.close()
            if resp.should_close():
                raise StopIteration()
        except StopIteration:
            raise
        except OSError:
            # If the original exception was a socket.error we delegate
            # handling it to the caller (where handle() might ignore it)
            util.reraise(*sys.exc_info())
        except Exception:
            if resp and resp.headers_sent:
                # If the requests have already been sent, we should close the
                # connection to indicate the error.
                self.log.exception("Error handling request")
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                    sock.close()
                except OSError:
                    pass
                raise StopIteration()
            raise
        finally:
            try:
                self.cfg.post_request(self, req, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")
        return True
