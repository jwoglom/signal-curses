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

import time

import npyscreen
import pyqrcode


class SetupLinkPromptForm(npyscreen.Form):
    def create(self):
        self.prompt()

    def prompt(self):
        state = self.parentApp.state
        self.parentApp.setNextForm('LINK')
        npyscreen.notify_confirm("Couldn't open your signal config file for:\nPhone: {}\nConfig dir: {}".format(state.phone, state.configDir) +
                                 "\nDo you want to link a new device right now? Hit enter twice to select the OK button. To cancel, press Ctrl+C", title="No signal-cli config")


class SetupLinkForm(npyscreen.Form):
    def create(self):
        self.parentApp.startLinkDaemon()
        self.showQR()

    def getQR(self):
        if not self.parentApp.setup.showingToken:
            return
        while self.parentApp.setup.token is None:
            npyscreen.notify_wait(
                "Waiting for token...\n\nOpen Signal > Settings > Linked Devices > Add and scan the QR code.", title="Setup")
            time.sleep(0.1)
        if not self.parentApp.setup.token.startswith('tsdevice:'):
            npyscreen.notify_confirm(
            "There was not a valid registration token returned from signal-cli\n\nReturned token: {}".format(self.parentApp.setup.token), title="Setup")
            exit(0)
        return pyqrcode.create(self.parentApp.setup.token, error='L').terminal(quiet_zone=1)

    def getResponse(self):
        while self.parentApp.setup.response is None:
            time.sleep(1)
        return self.parentApp.setup.response

    def showQR(self):
        state = self.parentApp.state
        self.parentApp.setup.showingToken = True
        self.parentApp.tokenQR = self.getQR()
        self.parentApp.setup.showingToken = False
        npyscreen.blank_terminal()
        print("\r")
        for line in self.parentApp.tokenQR.splitlines():
            print(line)
            print("\r", end='')
        print("")
        print("Open Signal > Settings > Linked Devices > Add and scan the QR code.\r")
        npyscreen.notify_confirm(
            self.getResponse(), title="Restart signal-curses to begin chatting")
        exit(0)
