"""
    signal-curses: Curses-backed terminal interface for Signal using signal-cli and npyscreen.
    Copyright (C) 2018  James Woglom

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from scurses import SignalApp
from signal import signal as py_signal
from signal import SIGINT, SIGTERM

__all__ = ['run']


def run(args):
    signal = SignalApp(options=args)
    py_signal(SIGINT, signal.sigint_handler)
    py_signal(SIGTERM, signal.sigterm_handler)
    signal.run()
