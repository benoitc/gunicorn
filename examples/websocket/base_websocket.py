# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Example code from Eventlet sources

import collections
import errno
import re
try:
    from hashlib import md5, sha1
except ImportError:
    from md5 import md5
    from sha1 import sha1
import socket
import struct

from gunicorn.workers.async import ALREADY_HANDLED

# Parts adapted from http://code.google.com/p/pywebsocket/
# mod_pywebsocket/handshake/handshake.py

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xa


class BaseLock(object):
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc_value, tb):
        pass

class BaseWebSocketWSGI(object):
    def __init__(self, handler, lock=BaseLock):
        self.handler = handler
        self.lock = BaseLock()

    def verify_client(self, ws):
        pass

    def _get_key_value(self, key_value):
        if not key_value:
            return
        key_number = int(re.sub("\\D", "", key_value))
        spaces = re.subn(" ", "", key_value)[1]
        if key_number % spaces != 0:
            return
        part = key_number / spaces
        return part

    def __call__(self, environ, start_response):
        protocol_version = None
        if not ('upgrade' in environ.get('HTTP_CONNECTION', '').lower()  and
                environ.get('HTTP_UPGRADE', '').lower() == 'websocket'):
            # need to check a few more things here for true compliance
            start_response('400 Bad Request', [('Connection','close')])
            return[]

        # See if they sent the new-format headers
        if 'HTTP_SEC_WEBSOCKET_KEY' in environ:
            protocol_version = 7
        elif 'HTTP_SEC_WEBSOCKET_KEY1' in environ:
            protocol_version = 76
            if 'HTTP_SEC_WEBSOCKET_KEY2' not in environ:
                # That's bad.
                start_response('400 Bad Request', [('Connection','close')])
                return[]

        sock = environ['gunicorn.socket']

        ws = WebSocket(sock,
            environ.get('HTTP_ORIGIN'),
            environ.get('HTTP_WEBSOCKET_PROTOCOL'),
            environ.get('PATH_INFO'),
            protocol_version,
            self.lock)

        key1 = self._get_key_value(environ.get('HTTP_SEC_WEBSOCKET_KEY1'))
        key2 = self._get_key_value(environ.get('HTTP_SEC_WEBSOCKET_KEY2'))

        handshake_reply = ("HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
                   "Upgrade: WebSocket\r\n"
                   "Connection: Upgrade\r\n")

        if protocol_version == 76 and key1 and key2:
            challenge = ""
            challenge += struct.pack("!I", key1)  # network byteorder int
            challenge += struct.pack("!I", key2)  # network byteorder int
            challenge += environ['wsgi.input'].read()
            handshake_reply +=  (
                       "Sec-WebSocket-Origin: %s\r\n"
                       "Sec-WebSocket-Location: ws://%s%s\r\n"
                       "Sec-WebSocket-Protocol: %s\r\n"
                       "\r\n%s" % (
                            environ.get('HTTP_ORIGIN'),
                            environ.get('HTTP_HOST'),
                            ws.path,
                            environ.get('HTTP_SEC_WEBSOCKET_PROTOCOL'),
                            md5(challenge).digest()))

        elif protocol_version == 75:
            handshake_reply += (
                       "WebSocket-Origin: %s\r\n"
                       "WebSocket-Location: ws://%s%s\r\n\r\n" % (
                            environ.get('HTTP_ORIGIN'),
                            environ.get('HTTP_HOST'),
                            ws.path))

        elif protocol_version == 7:
            key = environ['HTTP_SEC_WEBSOCKET_KEY']
            response = sha1(key+GUID).digest().encode('base64')[:-1]
            handshake_reply = ("HTTP/1.1 101 Switching Protocols\r\n"
                               "Upgrade: WebSocket\r\n"
                               "Connection: Upgrade\r\n"
                               "Sec-WebSocket-Accept: %s\r\n\r\n" % response)
        else:
            # Unsuported protocol version
            start_response('400 Bad Request', [('Connection','close')])
            return[]

        with self.lock:
            sock.sendall(handshake_reply)

        try:
            self.handler(ws)
        except socket.error, e:
            if e[0] != errno.EPIPE:
                raise
        # use this undocumented feature of grainbows to ensure that it
        # doesn't barf on the fact that we didn't call start_response
        return ALREADY_HANDLED

def bitewise_xor(mask, data):
    """ bitwwise xor data using mask """
    size = len(mask)
    mask = map(ord, mask)

    result = array.array('B')
    result.fromstring(data)

    count = 0
    for i in xrange(len(result)):
        result[i] ^= mask[count]
        count = (count + 1) % size
    return result.tostring()

def encode_hybi(opcode, buf):
    """ Returns a hybi encoded frame """

    if isinstance(buf, unicode):
        buf = buf.encode('utf-8')
    elif not isinstance(buf, str):
        buf = str(buf)
    blen = len(buf)

    byte1 = 0x80 | (opcode & 0x0f) # FIN + opcode
    if blen < 126:
        header = struct.pack('>BB', byte1, blen)
    elif blen > 125 and blen <= 65536:
        header = struct.pack('>BBH', byte1, 126, blen)
    elif blen >= 65536:
        header = struct.pack('>BBQ', byte1, 127,  blen)
    return header + buf, len(header)

def decode_hybi(buf):
    """ Decode hybi frame """
    blen = len(buf)
    hlen = 2
    if blen < hlen:
        # incomplete frame
        return {}

    byte1, byte2 = struct.unpack_from('>BB', buf)

    fin = (byte1 >> 7) & 1
    rsv1 = (byte1 >> 6) & 1
    rsv2 = (byte1 >> 5) & 1
    rsv3 = (byte1 >> 4) & 1
    opcode = byte1 & 0xf

    mask = (byte2 >> 7) & 1
    payload_length = byte2 & 0x7f

    # check extended payload
    if payload_length == 127:
        hlen = 10
        if blen < hlen:
            # incomplete frame
            return {}

        payload_length = struct.unpack_from('>xxQ', buf)[0]
    elif payload_length == 126:
        hlen = 4
        if blen < hlen:
            # incomplete frame
            return {}

        payload_length = struct.unpack_from('>xxH', buf)[0]
    frame_length = hlen + mask*4 + payload_length

    if payload_length > blen:
        # incomplete frame
        return {}

    data = buf[hlen + mask*4:hlen+mask*4+payload_length]

    if mask == 1:
        mask_nonce = buf[hlen:hlen+4]
        data = bitewise_xor(mask_nonce, data)

    return dict(opcode=opcode, payload=data, fin=fin, rsv1=rsv1,
            rsv2=rsv2, rsv3=rsv3, frame_length=frame_length)


def parse_messages(buf):
    """ Parses for messages in the buffer *buf*.  It is assumed that
    the buffer contains the start character for a message, but that it
    may contain only part of the rest of the message. NOTE: only understands
    lengthless messages for now.

    Returns an array of messages, and the buffer remainder that didn't contain
    any full messages."""
    msgs = []
    end_idx = 0
    while buf:
        assert ord(buf[0]) == 0, "Don't understand how to parse this type of message: %r" % buf
        end_idx = buf.find("\xFF")
        if end_idx == -1:
            break
        msgs.append(buf[1:end_idx].decode('utf-8', 'replace'))
        buf = buf[end_idx+1:]
    return msgs, buf

def format_message(message):
    # TODO support iterable messages
    if isinstance(message, unicode):
        message = message.encode('utf-8')
    elif not isinstance(message, str):
        message = str(message)
    packed = "\x00%s\xFF" % message
    return packed


class WebSocket(object):
    def __init__(self, sock, origin, protocol, path, version, lock):
        self.sock = sock
        self.origin = origin
        self.protocol = protocol
        self.version = version
        self.path = path
        self._buf = ""
        self._msgs = collections.deque()
        self._fragments = []
        self.lock = lock

    def send(self, message, opcode=OPCODE_TEXT):
        if self.version == 7:
            message, hlen = encode_hybi(opcode, message)
        else:
            message = format_message(message)
        with self.lock:
            return self.sock.sendall(message)

    def _wait_hexi(self):
        while not self._msgs:
            # no parsed messages, must mean buf needs more data
            delta = self.sock.recv(1024)
            if delta == '':
                return None
            self._buf += delta
            msgs, self._buf = parse_messages(self._buf)
            self._msgs.extend(msgs)
        return self._msgs.popleft()

    def _wait_hybi(self):
        while not self._msgs:
            # no parsed messages, must mean buf needs more data
            delta = self.sock.recv(1024)
            if delta == '':
                return None
            self._buf += delta

            frame = decode_hybi(self._buf)
            if not frame:
                # an incomplete frame wait until buffer fill
                print 'Incomplete Frame.. wait for data'
                continue

            opcode = frame['opcode']
            if frame['opcode'] == OPCODE_CONTINUATION:
                if not self._fragments:
                    raise Exception, 'Invalid intermediate fragment'

                if frame['fin']:
                    self._fragments.append(frame)
                    message = ''.join([f['payload'] \
                            for f in self._fragments])
                    # use the first frame optcode
                    opcode = self._fragments[0]['opcode']
                    self._fragments = []
                else:
                    self._fragments.append(frame)
            else:
                if self._fragments:
                    raise Exception, 'Should not receive an unfragmented'\
                                     'frame without closing fragmented one'
                if frame['fin']:
                    message = frame['payload']
                else:
                    self._fragments.append(frame)

            if not self._fragments:
                if opcode == OPCODE_TEXT:
                    message = message.decode('utf-8')

                elif opcode == OPCODE_CLOSE:
                    # TODO: implement send closing frame for hybi
                    self._send_closing_frame()
                    self.websocket_closed = True

                elif opcode == OPCODE_PING:
                    #TODO PING
                    pass
                elif opcode == OPCODE_PONG:
                    #TODO PONG
                    pass

                self._msgs.append(message)

            self._buf = self._buf[frame['frame_length']:]

    def wait(self):
        if self.protocol_version == 7:
            return self._wait_hybi()
        else:
            return self._wait_hexi()
