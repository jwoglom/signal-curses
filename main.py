import npyscreen
import curses
import subprocess
import threading
import re
import pathlib
import json
import os
import time
import argparse
import pydbus
import base64
import pyqrcode
import socket
from gi.repository import GLib
from signal import signal as py_signal
from signal import SIGINT, SIGTERM
from queue import Queue
from datetime import datetime

CURSES_OTHER_ENTER = 10
from secret import SELF_PHONE, TO_PHONE

log_file = open('sc.log', 'w')
log_file_lock = threading.Lock()

out_file = open('daemon.log', 'a')
out_file_lock = threading.Lock()
def log(*args):
    log_file_lock.acquire()
    log_file.write(str(datetime.now())[:19]+' ')
    log_file.write(' '.join([str(i) for i in args]))
    log_file.write('\n')
    log_file.flush()
    log_file_lock.release()

def execute_popen(cmd):
    return subprocess.Popen(cmd, stdout=subprocess.PIPE,
        universal_newlines=True)

def execute(popen):
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, None)

def exception_waitloop(fn, ex, sec, name=None):
    try:
        ret = fn()
    except ex as er:
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

class MainForm(npyscreen.Popup):
    def create(self):
        self.to = self.add(npyscreen.TitleSelectOne, max_height=3,
            name='To:',
            values=['Bob Smith', 'John Doe', 'Jane Doe', 'Todd Smith'],
            scroll_exit=True)
        self.msg = self.add(npyscreen.TitleText, name='Message:')

    def afterEditing(self):
        print('after editing', self.to.value, self.msg.value)
        self.parentApp.setNextForm('DONE')

class MessagesLine(npyscreen.MultiLine):
    _size = 15
    _size_max = 30
    _date_size = 20
    _real_values = []
    def __init__(self, *args, **kwargs):
        #kwargs['columns'] = 6
        #kwargs['column_width'] = 20
        super(MessagesLine, self).__init__(*args, **kwargs)

    def update(self, *args, **kwargs):
        if self._real_values:
            self._gen_size()
            self._gen_values()
        super(MessagesLine, self).update(*args, **kwargs)

    def _gen_size(self):
        self._size = min(max([len(i[1]) for i in self._real_values]), self._size_max)

    def display_value(self, val):
        return val

    def _gen_line_max(self, val, size_max):
        if len(val) < size_max:
            return val
        c = '…'
        return val[:size_max-len(c)]+c

    def _gen_lines(self, val):
        return self._gen_lines_full(val, self._size, self._size_max, self._date_size)

    def _gen_lines_full(self, val, size, size_max, date_size):
        # (date, from, message, suffix)
        beg_fmt = '{:<'+str(date_size)+'}{:>'+str(size)+'}'
        if len(val) > 2:
            beg_fmt += ' | '
        first_beg = beg_fmt.format(val[0], self._gen_line_max(val[1], size_max))
        cont_beg = beg_fmt.format(val[0], '')
        ret = []
        if len(val) < 3:
            return [first_beg]

        text = val[2]
        ln = first_beg + str(text[:self.width])
        if len(val) >= 4:
            #log('adding suffix:', val[3])
            if (len(ln) + len(val[3])) <= (self.width + len(cont_beg)):
                ln += (' ' * (self.width - len(ln) - len(val[3]) - 1)) + val[3]
            else:
                # force a new line
                ln += (' ' * (self.width - len(ln) - 1))
        ret.append(ln)
        text = text[self.width:]
        while len(text) > 0:
            ln = cont_beg + str(text[:self.width])
            text = text[self.width:]
            if len(val) >= 4:
                #log('adding suffix:', val[3])
                if (len(ln) + len(val[3])) <= (self.width + len(cont_beg)):
                    ln += (' ' * (self.width - len(ln) - len(val[3]) - 1)) + val[3]
                else:
                    # force a new line
                    ln += (' ' * (self.width - len(ln) - 1))
            ret.append(ln)
        #log('lines:', '\n'.join(ret))
        return ret

    def _gen_values(self):
        self.values = []
        for v in self._real_values:
            [self.values.append(i) for i in self._gen_lines(v)]

    def _time_now(self):
        return str(datetime.now())[:19]

    def addValues(self, values):
        for val in values:
            comb = [self._time_now()] + list(val)
            self._real_values += [comb]

    def clearValues(self):
        self._real_values = []
        self.values = []

    def addDatedValues(self, values):
        self._real_values += values

        #self.update()

    def _mark_value_as(self, value, txt):
        log('mark: ', value, 'as: ', txt)
        return (value[0], value[1], value[2], txt)

    def _mark_value_eq(self, a, b):
        return (a[:3] == b[:3])

    def markAs(self, value, suffix):
        for i in range(len(self._real_values)):
            if self._mark_value_eq(self._real_values[i], value):
                log('markAs success:', value)
                self._real_values[i] = self._mark_value_as(value, suffix)

class CurrentSend(object):
    timestamp = None
    value = None

    def __init__(self, timestamp, value):
        self.timestamp = timestamp
        self.value = value


class AppMessageBox(npyscreen.TitleText):
    currentSend = None
    def __init__(self, *args, **kwargs):
        super(AppMessageBox, self).__init__(*args, **kwargs)
        self.entry_widget.add_handlers({
            '^A': self._handleEnter,
            curses.KEY_ENTER: self._handleEnter,
            CURSES_OTHER_ENTER: self._handleEnter
        })

    def _getSelfName(self):
        return '{}'.format(self.parent.parentApp.state.phone)

    def _handleEnter(self, inp):
        now = int(time.time() * 1000)
        val = self.entry_widget.value
        log('handleEnter', inp, val, now)
        self.entry_widget.value = ''
        self.entry_widget.clear()

        self.currentSend = CurrentSend(now, val)
        self.parent.parentApp.handleSelfEnvelope(now, self._getSelfName(), val)
        self.parent.parentApp.queue_event(npyscreen.Event("SEND"))
        self.parent.parentApp.queue_event(npyscreen.Event("RELOAD"))


class AppForm(npyscreen.FormMuttActiveTraditionalWithMenus):
    COMMAND_WIDGET_CLASS = AppMessageBox
    COMMAND_WIDGET_NAME = 'Send: '
    COMMAND_WIDGET_BEGIN_ENTRY_AT = 1
    MAIN_WIDGET_CLASS = MessagesLine

    def create(self):
        self.m1 = self.add_menu(name="Main Menu", shortcut="^X")
        self.m1.addItemsFromList([
            ("Switch", self.whenSwitch, None, None, ("blah",)),
            ("Exit", self.whenExit, "e"),
        ])

        self.add_event_hander("RELOAD", self.reloadHandler)
        self.add_event_hander("SEND", self.sendHandler)

        super(AppForm, self).create()

    def reloadHandler(self, event):
        #log('reloadHandler')

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
        self.wStatus1.value = 'Signal: {} '.format(name if name else ', '.join(numbers))
        self.wStatus2.value = '{} ({}) '.format(name, ', '.join(numbers)) if name else ', '.join(numbers)+' '
        self.wStatus1.display()
        self.wStatus2.display()

    def updateState(self):
        self._updateTitle(self.parentApp.state.toName, self.parentApp.state.numbers)


class SelectFormTree(npyscreen.MLTree):
    pass


class SelectForm(npyscreen.Form):
    tree = None
    def create(self):
        super(SelectForm, self).create()
        self.tree = self.add(SelectFormTree)
        
        td = npyscreen.TreeData(content='Select one:', selectable=False, ignore_root=False)
        cobj = td.new_child(content='Contacts:', selectable=False)

        contacts = self.parentApp.configData.contacts
        for c in contacts:
            cobj.new_child(content='{} ({})'.format(c['name'], c['number']))
        gobj = td.new_child(content='Groups:', selectable=True)

        groups = self.parentApp.configData.groups
        for g in groups:
            gobj.new_child(content='{} ({})'.format(g['name'], ', '.join(g['members'])))

        self.tree.values = td

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
            npyscreen.notify_confirm('Invalid entry', title='Select User/Group')
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

    def updateState(self, selected, is_group):
        self.state.load(selected, is_group)
        log('new state:', self.state)

        self.loadDisplayLines()
        self.app.updateState()

    def loadDisplayLines(self):
        for line in self.lines:
            if self.state.shouldDisplayLine(line):
                self.addLine(line)

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
        #self.parent.wMain.addValues([
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
            log('ignoring envelope due to time difference of', str((time.time() - env.epoch_ts)))
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
                npyscreen.notify_wait(txt, title='New Message from {}'.format(gen_line[1]))
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
            npyscreen.notify_wait('You are receiving an inbound call', title='Call from {}'.format(env.source))

        if env.callMessage.is_busy():
            self.app.wMain.addValues([
                ('*', 'The caller {} is busy'.format(env.source))
            ])
            npyscreen.notify_wait('The caller is busy', title='Call from {}'.format(env.source))

        if env.callMessage.is_hangup():
            self.app.wMain.addValues([
                ('*', 'The caller {} hung up'.format(env.source))
            ])
            npyscreen.notify_wait('The caller hung up', title='Call from {}'.format(env.source))


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
        log('should_notify', toNumber, phone, self.source, self.dataMessage.should_display())
        return (self.source != toNumber) and (self.source != phone) and self.dataMessage.should_notify()

    def lookup_number(self, number):
        contacts = self.app.configData.contacts
        return next(i for i in contacts if i['number'] == number)

    @property
    def sourceName(self):
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
                log('msg: ts=', msg.get('timestamp'), 'sender=', msg.get('sender'))
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
            popen = execute_popen(script)
            self.app.daemonPopen = popen
            log('daemon popen')
            for line in execute(popen):
                #log('queue event')
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
            npyscreen.notify_wait('Unable to get signal {} bus. Messaging functionality will not function.'.format(self.app.state.bus), title='Error in SignalDaemonThread')
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

        env = self.app.generateSelfEnvelope(currentSend.timestamp, self.app.state.phone, message)
        log('send_message env:', env)
        self.app.markAsEnvelope(env, '(sent)')

        log('send_message done')

class Setup(object):
    token = None
    tokenQR = None
    showingToken = False
    response = None

class SetupLinkDaemonThread(threading.Thread):
    daemon = False
    app = None
    def __init__(self, app):
        super(SetupLinkDaemonThread, self).__init__()
        self.app = app

    def run(self):
        log('link daemon thread')

        state = self.app.state
        script = ['signal-cli', 'link', '-n{} on {}'.format('signal-curses', socket.gethostname())]
        try:
            popen = execute_popen(script)
            self.app.daemonPopen = popen
            log('link daemon popen')
            for line in execute(popen):
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

class SetupLinkPromptForm(npyscreen.Form):
    def create(self):
        self.prompt()

    def prompt(self):
        state = self.parentApp.state
        self.parentApp.setNextForm('LINK')
        npyscreen.notify_confirm("Couldn't open your signal config file for:\nPhone: {}\nConfig dir: {}".format(state.phone, state.configDir) +
                                 "\nDo you want to link a new device right now? Hit Tab-Enter to continue, or Ctrl+C", title="No signal-cli config")

class SetupLinkForm(npyscreen.Form):
    def create(self):
        self.parentApp.startLinkDaemon()
        self.showQR()

    def getQR(self):
        if not self.parentApp.setup.showingToken:
            return
        while self.parentApp.setup.token is None:
            npyscreen.notify_wait("Waiting for token...", title="Setup")
            time.sleep(1)
        return pyqrcode.create(self.parentApp.setup.token).terminal(quiet_zone=1)

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
        print("QR Code:")
        for line in self.parentApp.tokenQR.splitlines():
            print(line)
            print("\r", end='')
        print("")
        print("In the Signal app, scan this QR code in Settings > Linked Devices.\r")
        npyscreen.notify_confirm(self.getResponse(), title="Restart signal-curses to begin chatting")
        exit(0)



class SetupApp(npyscreen.NPSAppManaged):
    state = None
    setup = None

    def __init__(self, state, *args, **kwargs):
        self.state = state
        self.setup = Setup()
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
        self.linkDaemon = SetupLinkDaemonThread(self)
        self.linkDaemon.start()

    def onStart(self):
        self.addForm("MAIN", SetupLinkPromptForm, name='SetupLinkPrompt')
        self.addForm("LINK", SetupLinkForm, name='SetupLinkForm')
        self.promptForm = self.getForm('MAIN')
        self.linkForm = self.getForm('LINK')

    def run(self, *args, **kwargs):
        super(SetupApp, self).run(*args, **kwargs)

    def onCleanExit(self):
        print("QR code:")
        print(self.setup.tokenQR)

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
            setup = SetupApp(state)
            setup.run()
            exit(0)
        self.data = json.loads(f.read())
        f.close()

    @property
    def groups(self):
        return self.data['groupStore']['groups']

    @property
    def contacts(self):
        return self.data['contactStore']['contacts']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Curses interface for Signal')
    parser.add_argument('-u', dest='phone', help='Your phone number', required=True)
    parser.add_argument('--bus', dest='bus', help='DBus session type (default: session)', default='session', choices=['session', 'system'])
    parser.add_argument('-c', dest='configDir', help='Config folder', default='{}/.config/signal'.format(pathlib.Path.home()))

    args = parser.parse_args()
    log('args', args)

    signal = SignalApp(options=args)
    py_signal(SIGINT, signal.sigint_handler)
    py_signal(SIGTERM, signal.sigterm_handler)
    signal.run()
