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

import socket
import subprocess
import threading

import scurses.utils.processes
from scurses.utils.logger import log


class SetupLinkDaemonThread(threading.Thread):
    daemon = False
    app = None

    def __init__(self, app):
        super(SetupLinkDaemonThread, self).__init__()
        self.app = app

    def run(self):
        log('link daemon thread')

        state = self.app.state
        script = ['echo', 'signal-cli', 'link',
                  '-n{} on {}'.format('signal-curses', socket.gethostname())]
        try:
            popen = scurses.utils.processes.execute_popen(script)
            self.app.daemonPopen = popen
            log('link daemon popen')
            for line in scurses.utils.processes.execute(popen):
                #log('queue event')
                """out_file_lock.acquire()
                out_file.write(line)
                out_file.flush()
                out_file_lock.release()"""
                log('link line:', line)
                if len(line) > 0:
                    self.app.sendLinkLine(line)
        except subprocess.CalledProcessError as e:
            if not self.app.isShuttingDown:
                log('EXCEPTION in daemon', e)
        log('daemon exit')
