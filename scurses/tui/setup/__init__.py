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

import npyscreen
import scurses.models.setup
import scurses.threads.setup
import scurses.tui.setup.forms

from scurses.utils.logger import log


class SetupApp(npyscreen.NPSAppManaged):
    state = None
    setup = None
    isShuttingDown = False

    def __init__(self, state, *args, **kwargs):
        self.state = state
        self.setup = scurses.models.setup.Setup()
        super(SetupApp, self).__init__(*args, **kwargs)

    def sendLinkLine(self, line):
        if not self.setup.token:
            token = line.strip()
            log('GOT TOKEN:', token)
            self.setup.token = token
        else:
            log('AFTER:', line)
            if not self.setup.response:
                self.setup.response = line
            else:
                self.setup.response += '\n' + line

    def startLinkDaemon(self):
        self.linkDaemon = scurses.threads.setup.SetupLinkDaemonThread(self)
        self.linkDaemon.start()

    def onStart(self):
        self.addForm(
            "MAIN", scurses.tui.setup.forms.SetupLinkPromptForm, name='SetupLinkPrompt')
        self.addForm("LINK", scurses.tui.setup.forms.SetupLinkForm,
                     name='SetupLinkForm')
        self.promptForm = self.getForm('MAIN')
        self.linkForm = self.getForm('LINK')

    def run(self, *args, **kwargs):
        super(SetupApp, self).run(*args, **kwargs)

    def onCleanExit(self):
        print("QR code:")
        print(self.setup.tokenQR)
