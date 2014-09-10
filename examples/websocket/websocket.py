
import collections
import errno
import re
from hashlib import md5, sha1
import base64
from base64 import b64encode, b64decode
import socket
import struct
import logging
from socket import error as SocketError

import eventlet
from gunicorn.workers.async import ALREADY_HANDLED
from eventlet import pools

logger = logging.getLogger(__name__)

WS_KEY = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

class WebSocketWSGI(object):
    def __init__(self, handler):
        self.handler = handler

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
        if not (environ.get('HTTP_CONNECTION').find('Upgrade') != -1 and
            environ['HTTP_UPGRADE'].lower() == 'websocket'):
            # need to check a few more things here for true compliance
            start_response('400 Bad Request', [('Connection','close')])
            return []

        sock = environ['gunicorn.socket']

        version = environ.get('HTTP_SEC_WEBSOCKET_VERSION')

        ws = WebSocket(sock, environ, version)

        handshake_reply = ("HTTP/1.1 101 Switching Protocols\r\n"
                   "Upgrade: websocket\r\n"
                   "Connection: Upgrade\r\n")

        key = environ.get('HTTP_SEC_WEBSOCKET_KEY')
        if key:
            ws_key = base64.b64decode(key)
            if len(ws_key) != 16:
                start_response('400 Bad Request', [('Connection','close')])
                return []

            protocols = []
            subprotocols = environ.get('HTTP_SEC_WEBSOCKET_PROTOCOL')
            ws_protocols = []
            if subprotocols:
                for s in subprotocols.split(','):
                    s = s.strip()
                    if s in protocols:
                        ws_protocols.append(s)
            if ws_protocols:
                handshake_reply += 'Sec-WebSocket-Protocol: %s\r\n' % ', '.join(ws_protocols)

            exts = []
            extensions = environ.get('HTTP_SEC_WEBSOCKET_EXTENSIONS')
            ws_extensions = []
            if extensions:
                for ext in extensions.split(','):
                    ext = ext.strip()
                    if ext in exts:
                        ws_extensions.append(ext)
            if ws_extensions:
                handshake_reply += 'Sec-WebSocket-Extensions: %s\r\n' % ', '.join(ws_extensions)

            handshake_reply +=  (
                "Sec-WebSocket-Origin: %s\r\n"
                "Sec-WebSocket-Location: ws://%s%s\r\n"
                "Sec-WebSocket-Version: %s\r\n"
                "Sec-WebSocket-Accept: %s\r\n\r\n"
                 % (
                    environ.get('HTTP_ORIGIN'),
                    environ.get('HTTP_HOST'),
                    ws.path,
                    version,
                    base64.b64encode(sha1(key + WS_KEY).digest())
                ))

        else:

            handshake_reply += (
                       "WebSocket-Origin: %s\r\n"
                       "WebSocket-Location: ws://%s%s\r\n\r\n" % (
                            environ.get('HTTP_ORIGIN'),
                            environ.get('HTTP_HOST'),
                            ws.path))

        sock.sendall(handshake_reply)

        try:
            self.handler(ws)
        except socket.error, e:
            if e[0] != errno.EPIPE:
                raise
        # use this undocumented feature of grainbows to ensure that it
        # doesn't barf on the fact that we didn't call start_response
        return ALREADY_HANDLED

class WebSocket(object):
    """A websocket object that handles the details of
    serialization/deserialization to the socket.

    The primary way to interact with a :class:`WebSocket` object is to
    call :meth:`send` and :meth:`wait` in order to pass messages back
    and forth with the browser.  Also available are the following
    properties:

    path
        The path value of the request.  This is the same as the WSGI PATH_INFO variable, but more convenient.
    protocol
        The value of the Websocket-Protocol header.
    origin
        The value of the 'Origin' header.
    environ
        The full WSGI environment for this request.

    """
    def __init__(self, sock, environ, version=76):
        """
        :param socket: The eventlet socket
        :type socket: :class:`eventlet.greenio.GreenSocket`
        :param environ: The wsgi environment
        :param version: The WebSocket spec version to follow (default is 76)
        """
        self.socket = sock
        self.origin = environ.get('HTTP_ORIGIN')
        self.protocol = environ.get('HTTP_WEBSOCKET_PROTOCOL')
        self.path = environ.get('PATH_INFO')
        self.environ = environ
        self.version = version
        self.websocket_closed = False
        self._buf = ""
        self._msgs = collections.deque()
        self._sendlock = pools.TokenPool(1)

    @staticmethod
    def encode_hybi(buf, opcode, base64=False):
        """ Encode a HyBi style WebSocket frame.
        Optional opcode:
            0x0 - continuation
            0x1 - text frame (base64 encode buf)
            0x2 - binary frame (use raw buf)
            0x8 - connection close
            0x9 - ping
            0xA - pong
        """
        if base64:
            buf = b64encode(buf)

        b1 = 0x80 | (opcode & 0x0f) # FIN + opcode
        payload_len = len(buf)
        if payload_len <= 125:
            header = struct.pack('>BB', b1, payload_len)
        elif payload_len > 125 and payload_len < 65536:
            header = struct.pack('>BBH', b1, 126, payload_len)
        elif payload_len >= 65536:
            header = struct.pack('>BBQ', b1, 127, payload_len)

        #print("Encoded: %s" % repr(header + buf))

        return header + buf, len(header), 0

    @staticmethod
    def decode_hybi(buf, base64=False):
        """ Decode HyBi style WebSocket packets.
        Returns:
            {'fin'          : 0_or_1,
             'opcode'       : number,
             'mask'         : 32_bit_number,
             'hlen'         : header_bytes_number,
             'length'       : payload_bytes_number,
             'payload'      : decoded_buffer,
             'left'         : bytes_left_number,
             'close_code'   : number,
             'close_reason' : string}
        """

        f = {'fin'          : 0,
             'opcode'       : 0,
             'mask'         : 0,
             'hlen'         : 2,
             'length'       : 0,
             'payload'      : None,
             'left'         : 0,
             'close_code'   : None,
             'close_reason' : None}

        blen = len(buf)
        f['left'] = blen

        if blen < f['hlen']:
            return f # Incomplete frame header

        b1, b2 = struct.unpack_from(">BB", buf)
        f['opcode'] = b1 & 0x0f
        f['fin'] = (b1 & 0x80) >> 7
        has_mask = (b2 & 0x80) >> 7

        f['length'] = b2 & 0x7f

        if f['length'] == 126:
            f['hlen'] = 4
            if blen < f['hlen']:
                return f # Incomplete frame header
            (f['length'],) = struct.unpack_from('>xxH', buf)
        elif f['length'] == 127:
            f['hlen'] = 10
            if blen < f['hlen']:
                return f # Incomplete frame header
            (f['length'],) = struct.unpack_from('>xxQ', buf)

        full_len = f['hlen'] + has_mask * 4 + f['length']

        if blen < full_len: # Incomplete frame
            return f # Incomplete frame header

        # Number of bytes that are part of the next frame(s)
        f['left'] = blen - full_len

        # Process 1 frame
        if has_mask:
            # unmask payload
            f['mask'] = buf[f['hlen']:f['hlen']+4]
            b = c = ''
            if f['length'] >= 4:
                data = struct.unpack('<I', buf[f['hlen']:f['hlen']+4])[0]
                of1 = f['hlen']+4
                b = ''
                for i in xrange(0, int(f['length']/4)):
                    mask = struct.unpack('<I', buf[of1+4*i:of1+4*(i+1)])[0]
                    b += struct.pack('I', data ^ mask)

            if f['length'] % 4:
                l = f['length'] % 4
                of1 = f['hlen']
                of2 = full_len - l
                c = ''
                for i in range(0, l):
                    mask = struct.unpack('B', buf[of1 + i])[0]
                    data = struct.unpack('B', buf[of2 + i])[0]
                    c += chr(data ^ mask)

            f['payload'] = b + c
        else:
            print("Unmasked frame: %s" % repr(buf))
            f['payload'] = buf[(f['hlen'] + has_mask * 4):full_len]

        if base64 and f['opcode'] in [1, 2]:
            try:
                f['payload'] = b64decode(f['payload'])
            except:
                print("Exception while b64decoding buffer: %s" %
                        repr(buf))
                raise

        if f['opcode'] == 0x08:
            if f['length'] >= 2:
                f['close_code'] = struct.unpack_from(">H", f['payload'])
            if f['length'] > 3:
                f['close_reason'] = f['payload'][2:]

        return f


    @staticmethod
    def _pack_message(message):
        """Pack the message inside ``00`` and ``FF``

        As per the dataframing section (5.3) for the websocket spec
        """
        if isinstance(message, unicode):
            message = message.encode('utf-8')
        elif not isinstance(message, str):
            message = str(message)
        packed = "\x00%s\xFF" % message
        return packed

    def _parse_messages(self):
        """ Parses for messages in the buffer *buf*.  It is assumed that
        the buffer contains the start character for a message, but that it
        may contain only part of the rest of the message.

        Returns an array of messages, and the buffer remainder that
        didn't contain any full messages."""
        msgs = []
        end_idx = 0
        buf = self._buf
        while buf:
            if self.version in ['7', '8', '13']:
                frame = self.decode_hybi(buf, base64=False)
                #print("Received buf: %s, frame: %s" % (repr(buf), frame))

                if frame['payload'] == None:
                    break
                else:
                    if frame['opcode'] == 0x8: # connection close
                        self.websocket_closed = True
                        break
                    #elif frame['opcode'] == 0x1:
                    else:
                        msgs.append(frame['payload']);
                        #msgs.append(frame['payload'].decode('utf-8', 'replace'));
                        #buf = buf[-frame['left']:]
                        if frame['left']:
                            buf = buf[-frame['left']:]
                        else:
                            buf = ''


            else:
                frame_type = ord(buf[0])
                if frame_type == 0:
                    # Normal message.
                    end_idx = buf.find("\xFF")
                    if end_idx == -1: #pragma NO COVER
                        break
                    msgs.append(buf[1:end_idx].decode('utf-8', 'replace'))
                    buf = buf[end_idx+1:]
                elif frame_type == 255:
                    # Closing handshake.
                    assert ord(buf[1]) == 0, "Unexpected closing handshake: %r" % buf
                    self.websocket_closed = True
                    break
                else:
                    raise ValueError("Don't understand how to parse this type of message: %r" % buf)
        self._buf = buf
        return msgs

    def send(self, message):
        """Send a message to the browser.

        *message* should be convertable to a string; unicode objects should be
        encodable as utf-8.  Raises socket.error with errno of 32
        (broken pipe) if the socket has already been closed by the client."""
        if self.version in ['7', '8', '13']:
            packed, lenhead, lentail = self.encode_hybi(message, opcode=0x01, base64=False)
        else:
            packed = self._pack_message(message)
        # if two greenthreads are trying to send at the same time
        # on the same socket, sendlock prevents interleaving and corruption
        #self._sendlock.acquire()
        t = self._sendlock.get()
        try:
            self.socket.sendall(packed)
        finally:
            self._sendlock.put(t)

    def wait(self):
        """Waits for and deserializes messages.

        Returns a single message; the oldest not yet processed. If the client
        has already closed the connection, returns None.  This is different
        from normal socket behavior because the empty string is a valid
        websocket message."""
        while not self._msgs:
            # Websocket might be closed already.
            if self.websocket_closed:
                return None
            # no parsed messages, must mean buf needs more data
            delta = self.socket.recv(8096)
            if delta == '':
                return None
            self._buf += delta
            msgs = self._parse_messages()
            self._msgs.extend(msgs)
        return self._msgs.popleft()

    def _send_closing_frame(self, ignore_send_errors=False):
        """Sends the closing frame to the client, if required."""
        if self.version in ['7', '8', '13'] and not self.websocket_closed:
            msg = ''
            #if code != None:
            #    msg = struct.pack(">H%ds" % (len(reason)), code)

            buf, h, t = self.encode_hybi(msg, opcode=0x08, base64=False)
            self.socket.sendall(buf)
            self.websocket_closed = True

        elif self.version == 76 and not self.websocket_closed:
            try:
                self.socket.sendall("\xff\x00")
            except SocketError:
                # Sometimes, like when the remote side cuts off the connection,
                # we don't care about this.
                if not ignore_send_errors: #pragma NO COVER
                    raise
            self.websocket_closed = True

    def close(self):
        """Forcibly close the websocket; generally it is preferable to
        return from the handler method."""
        self._send_closing_frame()
        self.socket.shutdown(True)
        self.socket.close()

# demo app
import os
import random
def handle(ws):
    """  This is the websocket handler function.  Note that we
    can dispatch based on path in here, too."""
    if ws.path == '/echo':
        while True:
            m = ws.wait()
            if m is None:
                break
            ws.send(m)

    elif ws.path == '/data':
        for i in xrange(10000):
            ws.send("0 %s %s\n" % (i, random.random()))
            eventlet.sleep(0.1)

wsapp = WebSocketWSGI(handle)
def app(environ, start_response):
    """ This resolves to the web page or the websocket depending on
    the path."""
    if environ['PATH_INFO'] == '/' or environ['PATH_INFO'] == "":
        data = open(os.path.join(
                     os.path.dirname(__file__),
                     'websocket.html')).read()
        data = data % environ
        start_response('200 OK', [('Content-Type', 'text/html'),
                                 ('Content-Length', len(data))])
        return [data]
    else:
        return wsapp(environ, start_response)
