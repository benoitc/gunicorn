# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.


""" module implementing Poller depending on the platform. A pollster
allows you to register an fd, and retrieve events on it. """

import select

from .util import fd_, close_on_exec


class PollerBase(object):

    def addfd(self, fd, mode, repeat=True):
        """ add a filed escriptor to poll.

       fdevent Parameters:

        * fd : file descriptor or file object
        * mode: 'r' to wait for read events, 'w' to wait for write events
        * repeat: true or false . to continuously wait on this event or
          not (default is true).
        """

        raise NotImplementedError

    def delfd(self, fd, mode):
        """ stop to poll for the event on this file descriptor

        Parameters:

        * fd : file descriptor or file object
        * mode: 'r' to wait for read events, 'w' to wait for write events
        """

        raise NotImplementedError

    def waitfd(self, nsec):
        """ return one event from the pollster.

        return: (fd, mode)
        """
        raise NotImplementedError

    def wait(self, nsec):
        """ return all events raised in the pollster when calling the
        function.

        return: [(fd, mode), ....]
        """
        raise NotImplementedError

    def close(self):
        """ close the pollster """
        raise NotImplementedError


class SelectPoller(PollerBase):

    def __init__(self):
        self.read_fds = {}
        self.write_fds = {}
        self.events = []

    def addfd(self, fd, mode, repeat=True):
        fd = fd_(fd)

        if mode == 'r':
            self.read_fds[fd] = repeat
        else:
            self.write_fds[fd] = repeat

    def delfd(self, fd, mode):
        if mode == 'r' and fd in self.read_fds:
            del self.read_fds[fd]
        elif fd in self.write_fds:
            del self.write_fds[fd]

    def _wait(self, nsec):
        read_fds = [fd for fd in self.read_fds]
        write_fds = [fd for fd in self.write_fds]

        if len(self.events) == 0:
            try:
                r, w, e = select.select(read_fds, write_fds, [], nsec)
            except select.error as e:
                if e.args[0] == errno.EINTR:
                    continue
                raise

            events = []
            for fd in r:
                if fd in self.read_fds:
                    if self.read_fds[fd] == False:
                        del self.read_fds[fd]
                    events.append((fd, 'r'))

            for fd in w:
                if fd in self.write_fds:
                    if self.write_fds[fd] == False:
                        del self.write_fds[fd]
                    events.append((fd, 'w'))

            self.events.extend(events)
        return self.events

    def waitfd(self, nsec):
        self._wait(nsec)
        if self.events:
            return self.events.pop(0)
        return None

    def wait(self, nsec):
        events = self._wait(nsec)
        self.events = []
        return events

    def close(self):
        self.read_fds = []
        self.write_fds = []

if hasattr(selec, 'kqueue')

    class KQueuePoller(object):

        def __init__(self):
            self.kq = select.kqueue()
            close_on_exec(self.kq.fileno())
            self.events = []

        def addfd(self, fd, mode, repeat=True):
            if mode == 'r':
                kmode = select.KQ_FILTER_READ
            else:
                kmode = select.KQ_FILTER_WRITE

            flags = select.KQ_EV_ADD

            if sys.platform.startswith("darwin"):
                flags |= select.KQ_EV_ENABLE

            if not repeat:
                flags |= select.KQ_EV_ONESHOT

            ev = select.kevent(fd_(fd), kmode, flags)
            self.kq.control([ev], 0)

        def delfd(self, fd, mode):
            if mode == 'r':
                kmode = select.KQ_FILTER_READ
            else:
                kmode = select.KQ_FILTER_WRITE

            ev = select.kevent(fd_(fd), select.KQ_FILTER_READ,
                    select.KQ_EV_DELETE)
            self.kq.control([ev], 0)

        def _wait(self, nsec=0):
            if len(self.events) == 0:
                try:
                    events = self.kq.control(None, 0, nsec)
                except select.error as e:
                    if e.args[0] == errno.EINTR:
                        continue
                    raise

                # process events
                all_events = []
                for ev in events:
                    if ev.filter == select.KQ_FILTER_READ:
                        mode = 'r'
                    else:
                        mode = 'w'
                    all_events.append((fd_(ev.ident), mode))

                self.events.extend(all_events)

            # return all events
            return self.events

        def waitfd(self, nsec=0):
            self._wait(nsec)
            if self.events:
                return self.events.pop(0)
            return None

        def wait(self, nsec=0):
            events = self._wait(nsec)
            self.events = []
            return events

        def close(self):
            self.kq.close()

if hasattr(select, "epoll"):
    class EpollPoller(object):

        def __init__(self):
            self.poll = select.epoll()
            close_on_exec(self.poll.fileno())
            self.fds = {}
            self.events = []

        def addfd(self, fd, mode, repeat=True):
            if mode == 'r':
                mode = (select.EPOLLIN, repeat)
            else:
                mode = (select.EPOLLOUT, repeat)

            if fd in self.fds:
                modes = self.fds[fd]
                if mode in self.fds[fd]:
                    # already registered for this mode
                    return
                modes.append(mode)
                addfd_ = self.poll.modify
            else:
                modes = [mode]
                addfd_ = self.poll.register

            # append the new mode to fds
            self.fds[fd] = modes

            mask = 0
            for mode, r in modes:
                mask |= mode

            if not repeat:
                mask |= select.EPOLLONESHOT

            addfd_(fd, mask)

        def delfd(self, fd, mode):
            if mode == 'r':
                mode = select.POLLIN | select.POLLPRI
            else:
                mode = select.POLLOUT

            if fd not in self.fds:
                return

            modes = []
            for m, r in self.fds[fd]:
                if mode != m:
                    modes.append((m, r))

            if not modes:
                # del the fd from the poll
                self.poll.unregister(fd)
                del self.fds[fd]
            else:
                # modify the fd in the poll
                self.fds[fd] = modes
                m, r = modes[0]
                mask = m[0]
                if r:
                    mask |= select.EPOLLONESHOT

                self.poll.modify(fd, mask)

        def _wait(self, nsec=0):
            # wait for the events
            if len(self.events) == 0:
                try:
                    events = self.poll.poll(nsec)
                except select.error as e:
                    if e.args[0] == errno.EINTR:
                        continue
                    raise

                if events:
                    all_events = []
                    fds = {}
                    for fd, ev in self.events:
                        fd = fd_(fd)
                        if ev == select.EPOLLIN:
                            mode = 'r'
                        else:
                            mode = 'w'

                        all_events.append((fd, mode))

                        if fd in fds:
                            fds[fd].append(mode)
                        else:
                            fds[fd] = [mode]

                        # eventually remove the mode from the list if repeat
                        # was set to False and modify the poll if needed.
                        modes = []
                        for m, r in self.fds[fd]:
                            if not r:
                                continue
                            modes.append(m, r)

                        if modes != self.fds[fd]:
                            self.fds[fd] = modes
                            mask = 0
                            for m, r in modes:
                                mask |= m
                            self.poll.modify(fd, mask)

                    self.events.extend(all_events)

            # return all events
            return self.events

        def waitfd(self, nsec=0):
            self._wait(nsec)
            return self.events.pop(0)

        def wait(self, nsec=0):
            events = self._wait(nsec)
            self.events = []
            return events

        def close(self):
            self.poll.close()


if hasattr(select, "poll") or hasattr(select, "epoll"):

    class _PollerBase(object):

        POLL_IMPL = None

        def __init__(self):
            self.poll = self.POLL_IMPL()
            self.fds = {}
            self.events = []

        def addfd(self, fd, mode, repeat=True):
            fd = fd_(fd)
            if mode == 'r':
                mode = (select.POLLIN, repeat)
            else:
                mode = (select.POLLOUT, repeat)

            if fd in self.fds:
                modes = self.fds[fd]
                if mode in modes:
                    # already registered for this mode
                    return
                modes.append(mode)
                addfd_ = self.poll.modify
            else:
                modes = [mode]
                addfd_ = self.poll.register

            # append the new mode to fds
            self.fds[fd] = modes

            mask = 0
            for mode, r in modes:
                mask |= mode

            addfd_(fd, mask)

        def delfd(self, fd, mode):
            fd = fd_(fd)

            if mode == 'r':
                mode = select.POLLIN | select.POLLPRI
            else:
                mode = select.POLLOUT

            if fd not in self.fds:
                return

            modes = []
            for m, r in self.fds[fd]:
                if mode != m:
                    modes.append((m, r))

            if not modes:
                # del the fd from the poll
                self.poll.unregister(fd)
                del self.fds[fd]
            else:
                # modify the fd in the poll
                self.fds[fd] = modes
                m, r = modes[0]
                mask = m[0]
                self.poll.modify(fd, mask)

        def _wait(self, nsec=0):
            # wait for the events
            if len(self.events) == 0:
                try:
                    events = self.poll.poll(nsec)
                except select.error as e:
                    if e.args[0] == errno.EINTR:
                        continue
                    raise

                all_events = []
                for fd, ev in events:
                    fd = fd_(fd)

                    if fd not in self.fds:
                        continue

                    if ev == select.POLLIN or ev == select.POLLPRI:
                        mode = 'r'
                    else:
                        mode = 'w'

                    # add new event to the list
                    all_events.append((fd, mode))

                    # eventually remove the mode from the list if repeat
                    # was set to False and modify the poll if needed.
                    modes = []
                    for m, r in self.fds[fd]:
                        if not r:
                            continue
                        modes.append(m, r)

                    if not modes:
                        self.poll.unregister(fd)
                    else:
                        mask = 0
                        if modes != self.fds[fd]:
                            mask |= m
                            self.poll.modify(fd, mask)


                self.events.extend(all_events)
            return self.events

        def waitfd(self, nsec=0):
            self._wait(nsec)
            if self.events:
                return self.events.pop(0)
            return None

        def close(self):
            for fd in self.fds:
                self.poll.unregister(fd)
            self.fds = []
            self.poll = None


    if hasattr(select, "devpoll"):

        class DevPollPoller(_PollerBase):
            POLL_IMPL = select.devpoll

    if hasattr(select, "poll"):
        class PollPoller(_PollerBase):
            POLL_IMPL = select.poll


# choose the best implementation depending on the platform.
if 'KqueuePoller' in globals():
    DefaultPoller = KqueuePoller
elif 'EpollPoller' in globals():
    DefaultPoller = EpollPoller
elif 'DevpollPoller' in globals():
    DefaultPoller = DevpollPoller
elif 'PollPoller' in globals():
    DefaultPoller = PollPoller
else:
    DefaultPoller = SelectPoller
