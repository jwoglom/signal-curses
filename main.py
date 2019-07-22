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
import argparse
import pathlib
import scurses

from signal import signal as py_signal
from signal import SIGINT, SIGTERM

CONFIG_FOLDER = '.local/share/signal-cli'
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Curses interface for Signal')
    parser.add_argument('-u', dest='phone', help='Your phone number', required=True)
    parser.add_argument('--bus', dest='bus', help='DBus session type (default: session)', default='session', choices=['session', 'system'])
    parser.add_argument('-c', dest='configDir', help='Config folder', default='{}/{}'.format(pathlib.Path.home(), CONFIG_FOLDER))

    args = parser.parse_args()
    scurses.log('args', args)

    signal = scurses.SignalApp(options=args)
    py_signal(SIGINT, signal.sigint_handler)
    py_signal(SIGTERM, signal.sigterm_handler)
    signal.run()
