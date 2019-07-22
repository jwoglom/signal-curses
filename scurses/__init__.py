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
import base64
import curses
import npyscreen
import json
import os
import pathlib
import pydbus
import pyqrcode
import re
import socket
import subprocess
import sys
import threading
import time

from gi.repository import GLib
from signal import signal as py_signal
from signal import SIGINT, SIGTERM
from queue import Queue
from datetime import datetime

import scurses.models.setup
import scurses.tui.messages
import scurses.tui.setup
import scurses.utils.processes

from scurses.utils.logger import log


out_file = open('daemon.log', 'a')
out_file_lock = threading.Lock()


def exception_waitloop(fn, ex, sec, name=None):
    try:
        ret = fn()
    except ex as _:
        try:
            if name:
                print('Waiting for '+str(name), end='')
            for _ in range(sec):
                try:
                    ret = fn()
                except ex:
                    if name:
                        print('.', end='')
                        sys.stdout.flush()
                    time.sleep(1)
                    continue
                else:
                    break
            else:
                if name:
                    print('Giving up!')
                return False
        except KeyboardInterrupt:
            if name:
                print('')
            sys.exit(1)
    return ret


class AppForm(npyscreen.FormMuttActiveTraditionalWithMenus):
    COMMAND_WIDGET_CLASS = scurses.tui.messages.AppMessageBox
    COMMAND_WIDGET_NAME = 'Send: '
    COMMAND_WIDGET_BEGIN_ENTRY_AT = 1
    MAIN_WIDGET_CLASS = scurses.tui.messages.MessagesLine

    def create(self):
        log('appForm creating')
        self.m1 = self.add_menu(name="Main Menu", shortcut="^X")
        self.m1.addItemsFromList([
            ("Switch", self.whenSwitch, None, None, ("blah",)),
            ("Exit", self.whenExit, "e"),
        ])

        self.add_event_hander("RELOAD", self.reloadHandler)
        self.add_event_hander("SEND", self.sendHandler)

        super(AppForm, self).create()
        log('appForm created')

    def reloadHandler(self, event):
        # log('reloadHandler')

        self.wMain.update()

    def sendHandler(self, event):
        cur = self.wCommand.currentSend
        log('sendHandler', cur.value, cur.timestamp)

        self.parentApp.message_queue.put({
            'state': self.parentApp.state,
            'currentSend': cur
        })

    def whenSwitch(self, arg):
        self.parentApp.setNextForm('MAIN')
        self.parentApp.state.clear()
        self.parentApp.switchFormNow()

    def whenExit(self):
        self.parentApp.setNextForm(None)
        self.editing = False
        self.parentApp.handleExit()
        self.parentApp.switchFormNow()
        exit(0)

    def beforeEditing(self):
        self.wMain.always_show_cursor = False
        self.wMain.addValues([
            #   ('*', 'Connecting...',),
        ])
        self.wMain.display()

    def _updateTitle(self, name, numbers):
        self.wStatus1.value = 'Signal: {} '.format(
            name if name else ', '.join(numbers))
        self.wStatus2.value = '{} ({}) '.format(
            name, ', '.join(numbers)) if name else ', '.join(numbers)+' '
        self.wStatus1.display()
        self.wStatus2.display()

    def updateState(self):
        self._updateTitle(self.parentApp.state.toName,
                          self.parentApp.state.numbers)


class SelectFormTree(npyscreen.MLTree):
    pass


class SelectForm(npyscreen.Form):
    tree = None

    def create(self):
        log('selectForm create')
        super(SelectForm, self).create()
        self.tree = self.add(SelectFormTree)

        td = npyscreen.TreeData(content='Select one:',
                                selectable=False, ignore_root=False)
        cobj = td.new_child(content='Contacts:', selectable=False)

        contacts = self.parentApp.configData.contacts
        for c in contacts:
            cobj.new_child(content='{} ({})'.format(c['name'], c['number']))
        gobj = td.new_child(content='Groups:', selectable=True)

        groups = self.parentApp.configData.groups
        for g in groups:
            gobj.new_child(content='{} ({})'.format(
                g['name'], ', '.join(g['members'])))

        self.tree.values = td
        log('selectForm done')

    def getFromId(self, tree_id):
        contacts = self.parentApp.configData.contacts
        groups = self.parentApp.configData.groups
        obj = [None, None] + contacts + [None] + groups
        is_group = (tree_id > len(contacts) + 2)

        return (obj[tree_id], is_group)

    def afterEditing(self):
        log(self.tree.value)
        selected, is_group = self.getFromId(self.tree.value)
        log(selected)
        if not selected:
            npyscreen.notify_confirm(
                'Invalid entry', title='Select User/Group')
            return

        self.parentApp.app.wMain.clearValues()
        self.parentApp.app.wMain.update()
        self.parentApp.updateState(selected, is_group)
        self.parentApp.setNextForm('APP')


class AppState(object):
    startup_time = None

    convType = None
    USER = 'user'
    GROUP = 'group'

    user = None
    group = None

    configDir = None
    phone = None
    bus = None

    def __init__(self):
        self.startup_time = time.time()

    def __str__(self):
        return 'state type: {} name: {} numbers: {}'.format(self.convType, self.toName, ', '.join(self.numbers))

    @property
    def is_user(self):
        return self.convType == self.USER

    @property
    def is_group(self):
        return self.convType == self.GROUP

    @property
    def toNumber(self):
        return self.user['number'] if self.is_user else None

    @property
    def toNumbers(self):
        return self.group['members'] if self.is_group else None

    @property
    def numbers(self):
        return [self.toNumber] if self.is_user else self.toNumbers if self.is_group else []

    @property
    def toName(self):
        return self.user['name'] if self.is_user else (
            self.group['name'] if self.is_group else None)

    @property
    def groupId(self):
        return self.group['groupId'] if self.is_group else None

    def load(self, selected, is_group):
        if is_group:
            self.convType = self.GROUP
            self.group = selected
        else:
            self.convType = self.USER
            self.user = selected

    def clear(self):
        self.convType = None
        self.user = None
        self.group = None

    def loadArgs(self, args):
        self.phone = args.phone
        self.configDir = args.configDir
        self.bus = args.bus

    def shouldDisplayEnvelope(self, env):
        return env.should_display(self.toNumber, self.phone)

    def shouldNotifyEnvelope(self, env):
        return env.should_notify(self.toNumber, self.phone)


class SignalApp(npyscreen.StandardApp):
    app = None
    daemonThread = None
    daemonPopen = None
    messageThread = None
    message_queue = Queue()
    raw_lines = []
    messageLines = []
    state = None
    isShuttingDown = False
    lines = []
    envelopes = []

    configData = None

    def __init__(self, options=None, *args, **kwargs):
        super(SignalApp, self).__init__(*args, **kwargs)

        self.state = AppState()
        self.state.loadArgs(options)
        self.configData = SignalConfigData(self.state)

        self.initDaemon()

    def onStart(self):
        log('contacts: ', len(self.configData.contacts))

        self.addForm('MAIN', SelectForm, name='Select User/Group')
        self.addForm('APP', AppForm, name='Application')
        log('start forms', self._Forms)
        self.app = self.getForm('APP')
        log('app is defined')

    def updateState(self, selected, is_group):
        self.state.load(selected, is_group)
        log('new state:', self.state)

        self.app.updateState()

    def addEnvelope(self, env):
        gen_line = env.gen_line()
        self.app.wMain.addDatedValues([
            gen_line
        ])

    def markAsEnvelope(self, env, suffix):
        log('markAsEnvelope:', env, suffix)
        gen_line = env.gen_line()
        self.app.wMain.markAs(gen_line, suffix)
        self.app.wMain.update()

    def onInMainLoop(self):
        log('mloop forms', self._Forms)

    def initDaemon(self):
        log('main', self.app)
        self.daemonThread = SignalDaemonThread(self)
        self.daemonThread.start()

        self.messageThread = SignalMessageThread(self, self.message_queue)
        self.messageThread.start()

    def killMessageThread(self):
        self.message_queue.put({
            'exit': 1
        })

    def killDaemon(self):
        self.daemonPopen.send_signal(SIGINT)

    def handleExit(self):
        self.isShuttingDown = True
        self.killDaemon()
        self.killMessageThread()

    def sigint_handler(self, sig, frame):
        log('SIGINT')
        self.handleExit()
        exit(0)

    def sigterm_handler(self, sig, frame):
        log('SIGTERM')
        self.handleExit()
        exit(0)

    def generateSelfEnvelope(self, now, name, msg):
        return Envelope.load({"envelope": {
            "timestamp": now,
            "source": self.state.phone,
            "dataMessage": {
                "timestamp": now,
                "message": msg
            }
        }}, self, Envelope.SELF)

    def handleSelfEnvelope(self, now, name, msg):
        env = self.generateSelfEnvelope(now, name, msg)
        self.handleEnvelope(env)
        self.markAsEnvelope(env, '(sending)')
        # self.parent.wMain.addValues([
        #    (self._getSelfName(), val)])

    def handleDaemonLine(self, line):
        self.raw_lines.append(line)
        log('handleDaemonLine', line)
        data = json.loads(line)
        env = Envelope.load(data, self, Envelope.NETWORK)
        self.handleEnvelope(env)

    def handleEnvelope(self, env):
        self.envelopes.append(env)

        if env.timestamp and (time.time() - env.epoch_ts) >= 60:
            log('ignoring envelope due to time difference of',
                str((time.time() - env.epoch_ts)))
            return

        if env.dataMessage.is_message():
            if self.state.shouldDisplayEnvelope(env):
                self.addEnvelope(env)
            elif self.state.shouldNotifyEnvelope(env):
                log('notifying line')
                gen_line = env.gen_line()
                txt = '{}:\n\n{}'.format(gen_line[0], gen_line[2])
                if env.group:
                    txt = 'Group: {}\n'.format(json.dumps(env.group)) + txt
                npyscreen.notify_wait(
                    txt, title='New Message from {}'.format(gen_line[1]))
            else:
                log('not displaying or notifying dataMessage')

        if env.syncMessage.is_read_message():
            log('is read message', env.syncMessage)
            for e in self.envelopes[:-1]:
                if env.syncMessage.sync_read_matches(e):
                    log('mark_read', e)
                    self.markAsEnvelope(e, '(read)')

        if env.callMessage.is_offer():
            self.app.wMain.addValues([
                ('*', 'You are receiving an inbound call from {}'.format(env.source))
            ])
            npyscreen.notify_wait(
                'You are receiving an inbound call', title='Call from {}'.format(env.source))

        if env.callMessage.is_busy():
            self.app.wMain.addValues([
                ('*', 'The caller {} is busy'.format(env.source))
            ])
            npyscreen.notify_wait('The caller is busy',
                                  title='Call from {}'.format(env.source))

        if env.callMessage.is_hangup():
            self.app.wMain.addValues([
                ('*', 'The caller {} hung up'.format(env.source))
            ])
            npyscreen.notify_wait('The caller hung up',
                                  title='Call from {}'.format(env.source))

    def handleMessageLine(self, line):
        self.messageLines.append(line)
        log('handleMessageLine', line)


class Envelope(object):
    app = None
    origin = None
    NETWORK = 'NETWORK'
    SELF = 'SELF'
    _data = None

    source = None
    sourceDevice = None
    relay = None
    timestamp = None
    isReceipt = None
    dataMessage = None
    syncMessage = None
    callMessage = None

    @staticmethod
    def load(data, app, origin):
        self = Envelope()
        self.app = app
        self._data = data
        self.origin = origin
        e = data['envelope']
        self.source = e.get('source')
        self.sourceDevice = e.get('sourceDevice')
        self.relay = e.get('relay')
        self.timestamp = e.get('timestamp')
        self.isReceipt = e.get('isReceipt')
        self.dataMessage = DataMessage.load(e.get('dataMessage'))
        self.syncMessage = SyncMessage.load(e.get('syncMessage'))
        self.callMessage = CallMessage.load(e.get('callMessage'))
        return self

    def should_display(self, toNumber, phone):
        return ((self.source == toNumber) or (self.source == phone)) and self.dataMessage.should_display()

    def should_notify(self, toNumber, phone):
        # fromNumber != phone
        log('should_notify', toNumber, phone, self.source,
            self.dataMessage.should_display())
        return (self.source != toNumber) and (self.source != phone) and self.dataMessage.should_notify()

    def lookup_number(self, number):
        contacts = self.app.configData.contacts
        return next(i for i in contacts if i['number'] == number)

    @property
    def sourceName(self):
        if self.source == self.app.state.phone:
            return 'You'
        contact = self.lookup_number(self.source)
        return contact['name'] if contact else None

    @property
    def group(self):
        return self.dataMessage.groupInfo

    @property
    def epoch_ts(self):
        return int(self.timestamp)/1000

    def format_ts(self):
        return str(datetime.fromtimestamp(self.epoch_ts))[:19]

    def gen_line(self):
        if self.sourceName:
            return (self.format_ts(), '{} ({})'.format(self.sourceName, self.source), self.dataMessage.gen_line())
        return (self.format_ts(), '{}'.format(self.source), self.dataMessage.gen_line())

    def __str__(self):
        return json.dumps(self._data)


class DataMessage(object):
    timestamp = None
    message = None
    expiresInSeconds = None
    attachments = None
    groupInfo = None

    @staticmethod
    def load(data):
        self = DataMessage()
        if data:
            self.timestamp = data.get('timestamp')
            self.message = data.get('message')
            self.expiresInSeconds = data.get('expiresInSeconds')
            self.attachments = data.get('attachments')
            self.groupInfo = data.get('groupInfo')
        return self

    def is_message(self):
        return self.timestamp and self.message

    def should_display(self):
        return self.is_message()

    def should_notify(self):
        return self.is_message()

    def gen_line(self):
        return self.message


class SyncMessage(object):
    _data = None
    sentMessage = None
    blockedNumbers = None
    readMessages = None

    @staticmethod
    def load(data):
        self = SyncMessage()
        self._data = data
        if data:
            self.sentMessage = data.get('sentMessage')
            self.blockedNumbers = data.get('blockedNumbers')
            self.readMessages = data.get('readMessages')
        return self

    def is_read_message(self):
        return self.readMessages and len(self.readMessages) > 0

    def _compare_ts(self, envTs, msgTs):
        return abs(envTs - msgTs) < 1000

    def sync_read_matches(self, env):
        ret = False
        for msg in self.readMessages:
            if env and env.dataMessage.is_message():
                log('dm: ts=', env.dataMessage.timestamp, 'source=', env.source)
                log('msg: ts=', msg.get('timestamp'),
                    'sender=', msg.get('sender'))
                ret = ret or ((env.source == msg.get('sender')) and
                              self._compare_ts(env.dataMessage.timestamp, msg.get('timestamp')))

        return ret

    def __str__(self):
        return json.dumps(self._data)


class CallMessage(object):
    _data = None
    offerMessage = None
    busyMessage = None
    hangupMessage = None
    iceUpdateMessages = None

    @staticmethod
    def load(data):
        self = CallMessage()
        self._data = data
        if data:
            self.offerMessage = data.get('offerMessage')
            self.busyMessage = data.get('busyMessage')
            self.hangupMessage = data.get('hangupMessage')
            self.iceUpdateMessages = data.get('iceUpdateMessages')
        return self

    def is_offer(self):
        return self.offerMessage

    def is_busy(self):
        return self.busyMessage

    def is_hangup(self):
        return self.hangupMessage


class SignalDaemonThread(threading.Thread):
    daemon = False
    app = None

    def __init__(self, app):
        super(SignalDaemonThread, self).__init__()
        self.app = app

    def run(self):
        log('daemon thread')

        state = self.app.state
        script = ['signal-cli', '-u', state.phone, 'daemon', '--json']
        #script = ['python3', 'sp.py']
        try:
            popen = scurses.utils.processes.execute_popen(script)
            self.app.daemonPopen = popen
            log('daemon popen')
            for line in scurses.utils.processes.execute(popen):
                out_file_lock.acquire()
                out_file.write(line)
                out_file.flush()
                out_file_lock.release()
                log('line:', line)
                self.app.handleDaemonLine(line)
                self.app.queue_event(npyscreen.Event("RELOAD"))
        except subprocess.CalledProcessError as e:
            if not self.app.isShuttingDown:
                log('EXCEPTION in daemon', e)
        log('daemon exit')


class SignalMessageThread(threading.Thread):
    app = None
    daemon = False
    queue = None
    signal = None
    bus = None

    def __init__(self, app, queue):
        super(SignalMessageThread, self).__init__()
        self.app = app
        self.queue = queue

    def get_message_bus(self):
        return self.bus.get('org.asamk.Signal')

    def run(self):
        log('message thread')

        if self.app.state.bus == 'system':
            self.bus = pydbus.SystemBus()
        else:
            self.bus = pydbus.SessionBus()

        log('waiting for ({}) dbus...'.format(self.app.state.bus))
        self.signal = exception_waitloop(self.get_message_bus, GLib.Error, 60)
        if not self.signal:
            log('dbus err')
            npyscreen.notify_wait('Unable to get signal {} bus. Messaging functionality will not function.'.format(
                self.app.state.bus), title='Error in SignalDaemonThread')
            exit(1)
        log('got dbus')
        # self.signal.onMessageReceived

        while True:
            item = self.queue.get()
            log('queue item', item)
            if 'exit' in item:
                break
            self.do_action(**item)
            self.queue.task_done()
        log('message thread exit')

    def do_action(self, state=None, currentSend=None):
        self.send_message(state, currentSend)

    def send_message(self, state, currentSend):
        message = currentSend.value
        script = []
        if state.is_user:
            log('send_message user', state.toNumber, message)
            self.signal.sendMessage(message, [], [str(state.toNumber)])
        elif state.is_group:
            log('send_message group', state.groupId, message)
            b64 = base64.b64encode(state.groupId.encode())
            log('group id:', state.groupId, ' b64:', b64)
            self.signal.sendGroupMessage(message, [], b64)
        else:
            log('ERR: send_message inconsistent state')
            return

        env = self.app.generateSelfEnvelope(
            currentSend.timestamp, self.app.state.phone, message)
        log('send_message env:', env)
        self.app.markAsEnvelope(env, '(sent)')

        log('send_message done')


class SignalConfigData(object):
    data = None

    def __init__(self, state):
        phoneDir = '{}/data'.format(state.configDir)
        noConfig = False
        try:
            f = open('{}/{}'.format(phoneDir, state.phone), 'r')
        except FileNotFoundError as e:
            log('ERR: config load', e)
            noConfig = True

        if noConfig:
            setup = scurses.tui.setup.SetupApp(state)
            setup.run()
            exit(0)
        self.data = json.loads(f.read())

        noContacts = (not self.data['contactStore'] and (
            not self.data['groupStore'] or not self.data['groupStore']['groups']))
        if noContacts:
            log('noContacts!')
        f.close()

    @property
    def groups(self):
        if self.data['groupStore'] and 'groups' in self.data['groupStore']:
            return self.data['groupStore']['groups']
        return []

    @property
    def contacts(self):
        if self.data['contactStore'] and 'contacts' in self.data['contactStore']:
            return self.data['contactStore']['contacts']
        return []
