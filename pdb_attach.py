# -*- mode: python -*-
"""pdb-attach is a python debugger that can attach to running processes."""

import argparse
import io
import os
import pdb
import signal
import socket
import sys

__all__ = ["listen", "unlisten"]


def listen(port):
    old_handler = signal.getsignal(signal.SIGUSR1)
    debugger = PdbServer(old_handler, port)
    signal.signal(signal.SIGUSR1, debugger)


def unlisten():
    cur_handler = signal.getsignal(signal.SIGUSR1)
    if isinstance(cur_handler, PdbServer):
        cur_handler.close()
        signal.signal(signal.SIGUSR1, cur_handler._old_handler)


class PdbServer(pdb.Pdb):
    """PdbServer is a backend that uses signal handlers to start the server."""

    # Set use_rawinput to False to defer io to file object arguments passed to
    # stdin and stdout.
    use_rawinput = False

    def __init__(self, old_handler, port, *args, **kwargs):
        self._old_handler = old_handler
        self._sock = socket.socket()
        self._sock.bind(("localhost", port))
        self._sock.listen(0)

        if "stdin" in kwargs:
            del kwargs["stdin"]
        if "stdout" in kwargs:
            del kwargs["stdout"]

        pdb.Pdb.__init__(self, *args, **kwargs)
        self.prompt = PdbStr(self.prompt, prompt=True)

    def __call__(self, signum, frame):
        """Start tracing the program."""
        self.set_trace(frame)

    def set_trace(self, frame=None):
        """Accept the connection to the client and start tracing the program."""
        self.stdin = self.stdout = PdbIOWrapper(self._sock.accept()[0])
        pdb.Pdb.set_trace(self, frame)

    def do_detach(self, arg):
        """Detach and disconnect socket."""
        self.clear_all_breaks()
        self.set_continue()
        self.stdin._sock.close()
        return True


class PdbClient:
    def __init__(self, pid, port):
        self.server_pid = pid
        self.port = port
        self._client = None
        self._client_io = None

    def connect(self):
        """Send a signal before connecting."""
        os.kill(self.server_pid, signal.SIGUSR1)
        self._client_io = PdbIOWrapper(
            socket.create_connection(("localhost", self.port))
        )

    def raise_eoferror(self):
        if not self._client_io.raise_eoferror():
            return "", True
        return self._client_io.read_prompt()

    def send_and_recv(self, cmd):
        if not cmd.endswith(os.linesep):
            cmd += os.linesep
        self._client_io.write(cmd)
        return self._client_io.read_prompt()


class PdbStr(str):
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
        (PdbStr, code)
        """
        msg_data = ""
        while msg_data.count("|") < 2:
            c = self._sock.recv(1)
            if len(c) == 0:
                return PdbStr(""), self._CLOSED

            msg_data += c.decode(self.encoding, self.errors)

        msg_data_items = msg_data.split("|")
        msg_size = int(msg_data_items[0])
        code = int(msg_data_items[1])
        if code == self._EOFERROR:
            raise EOFError

        msg = self._sock.recv(msg_size).decode(self.encoding, self.errors)
        return_code = code if len(msg) == msg_size else self._CLOSED
        return (PdbStr(msg, prompt=(code == self._PROMPT)), return_code)

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
        if not isinstance(msg, PdbStr):
            msg = PdbStr(msg)
        code = self._PROMPT if msg.is_prompt else self._TEXT
        data = self._format_msg(msg, code=code)
        try:
            self._sock.sendall(data)
        except OSError:
            return 0

        # Offset num bytes written by the additional characters in the formatted
        # message.
        return len(msg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pid", type=int, metavar="PID", help="The pid of the process to debug."
    )
    parser.add_argument(
        "port",
        type=int,
        metavar="PORT",
        help="The port to connect to the running process.",
    )
    args = parser.parse_args()

    client = PdbClient(args.pid, args.port)
    client.connect()
    lines, closed = client._client_io.read_prompt()
    while closed is False:
        try:
            lines, closed = client.send_and_recv(input(lines))
        except EOFError:
            lines, closed = client.raise_eoferror()
    if len(lines) > 0:
        print(lines)


if "__main__" == __name__:
    main()
