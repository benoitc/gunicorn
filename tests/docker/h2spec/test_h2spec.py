# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""RFC 7540 and HPACK conformance via h2spec, per HTTP/2 capable worker.

h2spec (https://github.com/summerwind/h2spec) drives 146 cases against
a live server. Every case must pass except the ones listed per worker
below, which are known gaps tracked for a fix; a case that starts
failing outside that list fails the test, and a listed case that starts
passing is reported so the list can shrink.
"""

import warnings

import pytest

from .conftest import WORKERS, run_h2spec

# Known gaps, keyed by the case description h2spec prints. Observed with
# the official image on Linux; a local macOS binary shows a few more
# timing-sensitive ones on the sync workers.
WINDOW_OVERFLOW_ON_STREAM = (
    "3: Sends multiple WINDOW_UPDATE frames increasing the flow control "
    "window to above 2^31-1 on a stream")
KNOWN_FAILURES = {
    # The sync path answers a stream window overflow with a connection
    # error instead of RST_STREAM(FLOW_CONTROL_ERROR).
    "gthread": {WINDOW_OVERFLOW_ON_STREAM},
    "gevent": {
        WINDOW_OVERFLOW_ON_STREAM,
        # The socket is closed with unread bytes pending, so the client
        # sees a reset instead of a clean close; flaps run to run.
        "1: Sends a GOAWAY frame",
        "1: Sends an invalid PING frame for connection close",
        "1: Sends a GOAWAY frame with unknown error code",
    },
    "asgi": set(),
}


@pytest.mark.parametrize("worker", WORKERS)
def test_h2spec(worker, h2spec_services):
    passed, failed, failures, output = run_h2spec(worker)
    known = KNOWN_FAILURES[worker]
    unexpected = [f for f in failures if f not in known]
    fixed = [f for f in known if f not in failures]

    assert not unexpected, (
        f"{worker}: {failed} failed ({passed} passed); new failures:\n  "
        + "\n  ".join(unexpected) + f"\n\n{output}")
    assert passed + failed >= 140, f"{worker}: only {passed + failed} cases ran\n{output}"
    if fixed:
        # Some listed cases flap; say so without failing the run.
        warnings.warn(f"{worker}: listed h2spec cases passed this time: {fixed}")
