# -*- mode: python -*-
"""pdb-attach is a python debugger that can attach to running processes."""
import os
import platform
import warnings
import logging
import pdb
import signal
import code
import contextlib
import io
import socket
import sys
from .io_wrapper import PdbIOWrapper

__all__ = ["listen", "unlisten"]

def listen(port):
    old_handler = signal.getsignal(signal.SIGUSR1)
    debugger = PdbServer(old_handler, port, *args, **kwargs)
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
        self.prompt = _PdbStr(self.prompt, prompt=True)

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
        self._client_io = PdbIOWrapper(socket.create_connection(("localhost", self.port)))

    def raise_eoferror(self):
        if not self._client_io.raise_eoferror():
            return "", True
        return self._client_io.read_prompt()

    def send_and_recv(self, cmd):
        if not cmd.endswith(os.linesep):
            cmd += os.linesep
        self._client_io.write(cmd)
        return self._client_io.read_prompt()

