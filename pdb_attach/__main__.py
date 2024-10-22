# -*- mode: python -*-
"""Pdb-attach client that can be run as a module."""
import argparse

from . import PdbClient

if "__main__" == __name__:
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
