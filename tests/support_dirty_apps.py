#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Support module for multi-app dirty tests.

Provides test applications with distinct behaviors for verifying
that requests are correctly routed to the appropriate app.
"""

from gunicorn.dirty.app import DirtyApp


class CounterApp(DirtyApp):
    """App that maintains a counter.

    This app demonstrates stateful behavior where instance variables
    persist across requests.
    """

    def __init__(self):
        self.counter = 0
        self.initialized = False
        self.closed = False

    def init(self):
        """Initialize the counter app."""
        self.counter = 0
        self.initialized = True

    def increment(self, amount=1):
        """Increment the counter by the given amount.

        Args:
            amount: Amount to increment by (default: 1)

        Returns:
            The new counter value
        """
        self.counter += amount
        return self.counter

    def decrement(self, amount=1):
        """Decrement the counter by the given amount.

        Args:
            amount: Amount to decrement by (default: 1)

        Returns:
            The new counter value
        """
        self.counter -= amount
        return self.counter

    def get_value(self):
        """Get the current counter value.

        Returns:
            The current counter value
        """
        return self.counter

    def reset(self):
        """Reset the counter to zero.

        Returns:
            The counter value (0)
        """
        self.counter = 0
        return self.counter

    def close(self):
        """Clean up the counter app."""
        self.closed = True
        self.counter = 0


class EchoApp(DirtyApp):
    """App that echoes input with a configurable prefix.

    This app demonstrates a different behavior pattern from CounterApp
    for verifying app routing.
    """

    def __init__(self):
        self.prefix = "ECHO:"
        self.initialized = False
        self.closed = False
        self.echo_count = 0

    def init(self):
        """Initialize the echo app."""
        self.prefix = "ECHO:"
        self.echo_count = 0
        self.initialized = True

    def echo(self, message):
        """Echo a message with the current prefix.

        Args:
            message: The message to echo

        Returns:
            The prefixed message
        """
        self.echo_count += 1
        return f"{self.prefix} {message}"

    def set_prefix(self, prefix):
        """Set a new prefix for echo messages.

        Args:
            prefix: The new prefix to use

        Returns:
            The new prefix
        """
        self.prefix = prefix
        return prefix

    def get_prefix(self):
        """Get the current prefix.

        Returns:
            The current prefix
        """
        return self.prefix

    def get_echo_count(self):
        """Get the number of echo calls made.

        Returns:
            The echo count
        """
        return self.echo_count

    def close(self):
        """Clean up the echo app."""
        self.closed = True
        self.echo_count = 0
