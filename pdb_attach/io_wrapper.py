import sys


class _PdbStr(str):
    def __new__(cls, value, prompt=False):
        self = str.__new__(cls, value)
        self.is_prompt = prompt
        return self

class PdbIOWrapper(io.TextIOBase):
    """Wrapper for socket IO.

    Allows for smoother IPC. Data sent over socket is formatted `<msg_size>|<code>|<msg_text>`.
    """

    def __init__(self, sock):
        self._buffer = self._new_buffer()
        self._sock = sock

    _CLOSED = -1
    _TEXT = 0
    _PROMPT = 1
    _EOFERROR = 2

    @property
    def encoding(self):
        """Return the name of the stream encoding."""
        return sys.getdefaultencoding()

    @property
    def errors(self):
        """Return the error setting."""
        return "strict"

    def _format_msg(self, msg, code):
        return "{}|{}|{}".format(len(msg), code, msg).encode(self.encoding, self.errors)

    def _new_buffer(self):
        return ""

    def _read(self):
        """Read from the socket.

        Returns
        -------
        (_PdbStr, code)
        """
        msg_data = ""
        while msg_data.count("|") < 2:
            c = self._sock.recv(1)
            if len(c) == 0:
                return _PdbStr(""), self._CLOSED

            msg_data += c.decode(self.encoding, self.errors)

        msg_data_items = msg_data.split("|")
        msg_size = int(msg_data_items[0])
        code = int(msg_data_items[1])
        if code == self._EOFERROR:
            raise EOFError

        msg = self._sock.recv(msg_size).decode(self.encoding, self.errors)
        return_code = code if len(msg) == msg_size else self._CLOSED
        return (_PdbStr(msg, prompt=(code == self._PROMPT)), return_code)

    def _read_eof(self):
        while True:
            msg, code = self._read()
            self._buffer += msg
            if code == self._CLOSED:
                break

    def read(self, size=-1):
        """Read `size` characters or until EOF is reached.

        Parameters
        ----------
        size : int
            The number of characters to return. If negative, reads until EOF.

        Returns
        -------
        str
        """
        if size is None or size < 0:
            self._read_eof()
            rv, self._buffer = self._buffer, self._new_buffer()
            return rv

        while len(self._buffer) < size:
            msg, code = self._read()
            self._buffer += msg
            if code == self._CLOSED:
                size = min(len(self._buffer), size)

        rv, self._buffer = self._buffer[:size], self._buffer[size:]
        return rv

    def readline(self, size=-1):
        """Read a string until a newline or EOF is reached.

        Parameters
        ----------
        size : int
            The number of characters to read. If `size` characters are read before
            a newline is seen, then `size` characters are returned.

        Returns
        -------
        str
        """
        while os.linesep not in self._buffer:
            if size >= 0 and len(self._buffer) >= size:
                break

            msg, code = self._read()
            self._buffer += msg

            if code == self._CLOSED:
                break

        if size >= 0 and os.linesep in self._buffer:
            idx = min(size, self._buffer.index(os.linesep) + len(os.linesep))
        elif size >= 0:
            idx = size
        elif os.linesep in self._buffer:
            idx = self._buffer.index(os.linesep) + len(os.linesep)
        else:
            idx = len(self._buffer)

        rv, self._buffer = self._buffer[:idx], self._buffer[idx:]
        return rv

    def read_prompt(self):
        """Read everything until a prompt is received and return it.

        Returns
        -------
        (str, bool) : A tuple containing the str output from the connection and
            a bool indicating if the connection is closed.
        """
        while True:
            msg, code = self._read()
            self._buffer += msg
            if code == self._CLOSED or msg.is_prompt:
                break

        rv, self._buffer = self._buffer, self._new_buffer()
        return rv, code == self._CLOSED

    def raise_eoferror(self):
        """Send `EOFError` code through socket.

        Returns
        -------
        bool : True if send was successful.
        """
        try:
            self._sock.sendall(self._format_msg("", self._EOFERROR))
            return True
        except OSError:
            return False

    def write(self, msg):
        """Write `msg` to the socket and return the number of bytes sent.

        Parameters
        ----------
        msg : str
            A string to send through the socket.

        Returns
        -------
        int : The number of bytes written to the socket.
        """
        if not isinstance(msg, _PdbStr):
            msg = _PdbStr(msg)
        code = self._PROMPT if msg.is_prompt else self._TEXT
        data = self._format_msg(msg, code=code)
        try:
            self._sock.sendall(data)
        except OSError:
            return 0

        # Offset num bytes written by the additional characters in the formatted
        # message.
        return len(msg)
