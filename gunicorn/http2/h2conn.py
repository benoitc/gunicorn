# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The h2 connection class shared by the sync and asyncio HTTP/2 paths."""

from .errors import HTTP2NotAvailable

_cls = None


def server_connection_class():
    """Return the H2Connection subclass gunicorn uses on the server side.

    h2 answers a peer GOAWAY by closing its own connection state, which
    would refuse every later send. RFC 9113 section 6.8 says a graceful
    GOAWAY (NO_ERROR) only forbids new streams and the established ones
    finish, so for that case the subclass reports the event and leaves
    the state machine alone. Frames that follow the GOAWAY in the same
    read are then still processed.
    """
    global _cls  # pylint: disable=global-statement
    if _cls is not None:
        return _cls
    try:
        import h2.connection
        import h2.errors
        import h2.events
    except ImportError:
        raise HTTP2NotAvailable()

    class ServerH2Connection(h2.connection.H2Connection):
        #: last_stream_id from a graceful peer GOAWAY that left the
        #: connection open, None otherwise.
        peer_goaway_last_stream_id = None

        def _receive_goaway_frame(self, frame):
            if (not self.config.client_side and frame.error_code == 0
                    and self.open_inbound_streams):
                self.peer_goaway_last_stream_id = frame.last_stream_id
                event = h2.events.ConnectionTerminated()
                event.error_code = h2.errors.ErrorCodes.NO_ERROR
                event.last_stream_id = frame.last_stream_id
                event.additional_data = frame.additional_data or None
                return [], [event]
            return super()._receive_goaway_frame(frame)

    _cls = ServerH2Connection
    return _cls
