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
import threading

from datetime import datetime


log_file = open('sc.log', 'w')
log_file_lock = threading.Lock()


def log(*args):
    log_file_lock.acquire()
    log_file.write(str(datetime.now())[:19]+' ')
    log_file.write(' '.join([str(i) for i in args]))
    log_file.write('\n')
    log_file.flush()
    log_file_lock.release()
