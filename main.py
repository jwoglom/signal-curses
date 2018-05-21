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
from gi.repository import GLib
from signal import signal as py_signal
from signal import SIGINT, default_int_handler
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
        beg_fmt = '{:<'+str(date_size)+'}{:>'+str(size)+'}'
        if len(val) > 2:
            beg_fmt += ' | '
        first_beg = beg_fmt.format(val[0], self._gen_line_max(val[1], size_max))
        cont_beg = beg_fmt.format(val[0], '')
        ret = []
        if len(val) < 3:
            return [first_beg]

        text = val[2]
        ret.append(first_beg + str(text[:self.width]))
        text = text[self.width:]
        while len(text) > 0:
            ret.append(cont_beg + str(text[:self.width]))
            text = text[self.width:]
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

class AppMessageBox(npyscreen.TitleText):
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
        val = self.entry_widget.value
        log('handleEnter', inp, val)
        self.parent.wMain.addValues([
            (self._getSelfName(), val)])
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
        val = self.wCommand.entry_widget.value
        log('sendHandler', val)
        self.wCommand.entry_widget.value = ''
        self.wCommand.entry_widget.clear()

        self.parentApp.message_queue.put({
            'state': self.parentApp.state,
            'message': val
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
    convType = None
    USER = 'user'
    GROUP = 'group'

    user = None
    group = None

    configDir = None
    phone = None
    bus = None

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

    def shouldDisplayLine(self, lineState):
        if lineState.hasGroupInfo and lineState.groupId == self.groupId:
            return True

        return lineState.fromNumber == self.toNumber

    def shouldDisplayEnvelope(self, env):
        return env.should_display(self.toNumber, self.phone)

    def shouldNotifyLine(self, lineState):
        return lineState.fromNumber != self.phone

    def shouldNotifyEnvelope(self, env):
        return env.should_notify(self.toNumber, self.phone)

class SignalApp(npyscreen.StandardApp):
    app = None
    daemonThread = None
    daemonPopen = None
    busThread = None
    messageThread = None
    message_queue = Queue()
    raw_lines = []
    messageLines = []
    lineState = None
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

        self.lineState = LineState()

    def updateState(self, selected, is_group):
        self.state.load(selected, is_group)
        log('new state:', self.state)

        self.loadDisplayLines()
        self.app.updateState()

    def loadDisplayLines(self):
        for line in self.lines:
            if self.state.shouldDisplayLine(line):
                self.addLine(line)


    def addLine(self, lineState):
        gen_line = lineState.gen_line()
        self.app.wMain.addDatedValues([
            gen_line
        ])

    def addEnvelope(self, env):
        gen_line = env.gen_line()
        self.app.wMain.addDatedValues([
            gen_line
        ])

    def onInMainLoop(self):
        log('mloop forms', self._Forms)
        
    def initDaemon(self):
        log('main', self.app)
        self.daemonThread = SignalDaemonThread(self)
        self.daemonThread.start()

        self.busThread = SignalBusThread(self)
        self.busThread.start()

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
        self.killMessageThread()
        self.killDaemon()

    def sigint_handler(self, sig, frame):
        log('SIGINT')
        self.handleExit()
        exit(0)

    def handleDaemonLine(self, line):
        self.raw_lines.append(line)
        log('handleDaemonLine', line)
        data = json.loads(line)
        env = Envelope.load(data, self)
        self.envelopes.append(env)

        if self.state.shouldDisplayEnvelope(env):
            self.addEnvelope(env)
        elif self.state.shouldNotifyEnvelope(env):
            log('notifying line')
            gen_line = env.gen_line()
            txt = '{}:\n\n{}'.format(gen_line[0], gen_line[2])
            if env.group:
                txt = 'Group: {}\n'.format(self.lineState.groupName) + txt
            npyscreen.notify_wait(txt, title='New Message from {}'.format(gen_line[1]))
        else:
            log('not displaying or notifying')



    def old_handleDaemonLine(self, line):
        regexes = {
            'init': r'Envelope from: \“([\w\d\s]*)\” (\+\d+) \(device: (\d+)\)',
            'timestamp': r'Timestamp: (\d+) \((.*)\)',
            'msgTimestamp': r'Message timestamp: (\d+) \((.*)\)',
            'toLine': r'To: \“([\w\d\s]*)\” (\+\d+) , Message timestamp: (\d+) \((.*)\)',
            'body': r'Body: (.*)',
            'groupInfo': r'(Group info:)',
            'groupId': r'  Id: (.*)',
            'groupName': r'  Name: (.*)',
            'groupType': r'  Type: (.*)'
        }


        for typ in regexes.keys():
            regex = regexes[typ] 
            res = re.search(regex, line)
            match = res.groups() if res else None
            if not match:
                continue
            log(typ, 'matches', match)

            if typ == 'init':
                self.lineState.fromName = match[0]
                self.lineState.fromNumber = match[1]
            elif typ == 'timestamp':
                self.lineState.timestamp = match[0]
            elif typ == 'messageTimestamp':
                self.lineState.msgTimestamp = match[0]
            elif typ == 'toLine':
                self.lineState.toName = match[0]
                self.lineState.toNumber = match[1]
                self.lineState.msgTimestamp = match[2]
            elif typ == 'body':
                self.lineState.messageBody = match[0]
            elif typ == 'groupInfo':
                self.lineState.hasGroupInfo = True
            elif typ == 'groupId':
                self.lineState.groupId = match[0]
            elif typ == 'groupName':
                self.lineState.groupName = match[0]
            elif typ == 'groupType':
                self.lineState.groupType = match[0]
            log('re-loop')

        log('lineState', self.lineState)
        if self.lineState.is_ready_ws():
            log('lineStateReadyWs len', len(line))
            if len(line) < 2:
                self.lineState.hasWhitespaceLine = True

        if self.lineState.is_ready():
            log('lineStateReady')
            self.lines.append(self.lineState)

            if self.state.shouldDisplayLine(self.lineState):
                self.addLine(self.lineState)
            elif self.state.shouldNotifyLine(self.lineState):
                log('notifying line')
                gen_line = self.lineState.gen_line()
                txt = '{}:\n\n{}'.format(gen_line[0], gen_line[2])
                if self.lineState.hasGroupInfo:
                    txt = 'Group: {}\n'.format(self.lineState.groupName) + txt
                npyscreen.notify_wait(txt, title='New Message from {}'.format(gen_line[1]))
            else:
                log('not displaying or notifying')

            self.lineState = LineState()

        #self.app.wMain.addValues([('*', line)])

    def handleMessageLine(self, line):
        self.messageLines.append(line)
        log('handleMessageLine', line)

class LineState(object):
    fromName = None
    fromNumber = None

    toName = None
    toNumber = None

    timestamp = None
    msgTimestamp = None
    messageBody = None

    hasWhitespaceLine = None

    hasGroupInfo = None
    groupId = None
    groupName = None
    groupType = None

    def is_ready_ws(self):
        return self.fromNumber and self.timestamp and self.messageBody

    def is_ready(self):
        return self.is_ready_ws() and self.hasWhitespaceLine

    def format_ts(self):
        return str(datetime.fromtimestamp(int(self.timestamp)/1000))[:19]

    def gen_line(self):
        if self.fromName:
            return (self.format_ts(), '{} ({})'.format(self.fromName, self.fromNumber), self.messageBody)
        return (self.format_ts(), '{}'.format(self.fromNumber), self.messageBody)

    def __str__(self):
        return "name: {} num: {} ts: {} body: {}".format(
            self.fromName, self.fromNumber, self.timestamp, self.messageBody)

class Envelope(object):
    app = None

    source = None
    sourceDevice = None
    relay = None
    timestamp = None
    isReceipt = None
    dataMessage = None
    syncMessage = None
    callMessage = None

    @staticmethod
    def load(data, app):
        self = Envelope()
        self.app = app
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
        return (self.source == toNumber) and self.dataMessage.should_display()

    def should_notify(self, toNumber, phone):
        # fromNumber != phone
        log('should_notify', toNumber, phone, self.source, self.dataMessage.should_display())
        return (self.source != toNumber) and self.dataMessage.should_notify()

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

    def format_ts(self):
        return str(datetime.fromtimestamp(int(self.timestamp)/1000))[:19]

    def gen_line(self):
        if self.sourceName:
            return (self.format_ts(), '{} ({})'.format(self.sourceName, self.source), self.dataMessage.gen_line())
        return (self.format_ts(), '{}'.format(self.source), self.dataMessage.gen_line())


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

    @staticmethod
    def load(data):
        pass # stub

class CallMessage(object):

    @staticmethod
    def load(data):
        pass # stub


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


class SignalBusThread(threading.Thread):
    daemon = False
    app = None
    bus = None
    def __init__(self, app):
        super(SignalBusThread, self).__init__()
        self.app = app

    def get_message_bus(self):
        return self.bus.get('org.asamk.Signal')

    def receive(self, timestamp, source, groupID, message, attachments):
        log('RCV', timestamp, source, groupID, message, attachments)

    def run(self):
        log('bus thread')
        state = self.app.state
        return

        loop = GLib.MainLoop()

        if state.bus == 'system':
            self.bus = pydbus.SystemBus()
        else:
            self.bus = pydbus.SessionBus()

        log('waiting for dbus...')
        self.signal = exception_waitloop(self.get_message_bus, GLib.Error, 100)
        if not self.signal:
            log('dbus err')
            npyscreen.notify_wait('Unable to get signal {} bus'.format(state.bus), title='Error in SignalDaemonThread')
        log('got dbus')
        self.signal.onMessageReceived = self.receive
        loop.run()




class SignalMessageThread(threading.Thread):
    app = None
    daemon = False
    queue = None
    def __init__(self, app, queue):
        super(SignalMessageThread, self).__init__()
        self.app = app
        self.queue = queue

    def run(self):
        log('message thread')
        while True:
            item = self.queue.get()
            log('queue item', item)
            if 'exit' in item:
                break
            self.do_action(**item)
            self.queue.task_done()
        log('message thread exit')

    def do_action(self, state=None, message=None):
        self.send_message(state, message)

    def send_message(self, state, message):
        script = []
        if state.is_user:
            log('send_message user', state.toNumber, message)
            script = ['signal-cli', '--dbus', 'send', str(state.toNumber), '-m', message]
        elif state.is_group:
            log('send_message group', state.groupId, message)
            script = ['signal-cli', '--dbus', 'send', '-g', str(state.groupId), '-m', message]
        else:
            log('ERR: send_message inconsistent state')
            return
        popen = execute_popen(script)
        try:
            for line in execute(popen):
                #log('queue event')
                self.app.handleMessageLine(line)
                self.app.queue_event(npyscreen.Event("RELOAD"))
        except subprocess.CalledProcessError as e:
            log('EXCEPTION in message thread', e)

        log('send_message done')

class SignalConfigData(object):
    data = None
    def __init__(self, state):
        f = open('{}/data/{}'.format(state.configDir, state.phone), 'r')
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
    #py_signal(SIGINT, default_int_handler)
    signal.run()

    #print(npyscreen.wrapper_basic(formFunc))