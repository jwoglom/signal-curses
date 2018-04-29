import npyscreen
import curses
import subprocess
import threading
import re
import pathlib
import json
import os
from queue import Queue
from datetime import datetime

CURSES_OTHER_ENTER = 10
from secret import SELF_PHONE, TO_PHONE

log_file = open('sc.log', 'w')
log_file_lock = threading.Lock()
def log(*args):
    log_file_lock.acquire()
    log_file.write(str(datetime.now())[:19]+' ')
    log_file.write(' '.join([str(i) for i in args]))
    log_file.write('\n')
    log_file.flush()
    log_file_lock.release()

def execute_popen(cmd):
    return subprocess.Popen(cmd, stdout=subprocess.PIPE,
        universal_newlines=True, preexec_fn=os.setsid)

def execute(popen):
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line 
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, None)

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

    def _handleEnter(self, inp):
        val = self.entry_widget.value
        log('handleEnter', inp, val)
        self.parent.wMain.addValues([
            ('ENTER', val)])
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
        self.wStatus1.value = 'Signal: {} '.format(name)
        self.wStatus2.value = '{} ({}) '.format(name, ', '.join(numbers))
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

        self.parentApp.updateState(selected, is_group)
        self.parentApp.setNextForm('APP')


class AppState(object):
    convType = None
    USER = 'user'
    GROUP = 'group'

    user = None
    group = None

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


class SignalApp(npyscreen.StandardApp):
    app = None
    daemonThread = None
    daemonPopen = None
    messageThread = None
    message_queue = Queue()
    lines = []
    messageLines = []
    lineState = None
    state = None

    configData = None

    def onStart(self):
        self.configData = SignalConfigData(SELF_PHONE)
        log('contacts: ', len(self.configData.contacts))
        self.state = AppState()

        self.addForm('MAIN', SelectForm, name='Select User/Group')
        self.addForm('APP', AppForm, name='Application')
        log('start forms', self._Forms)
        self.app = self.getForm('APP')

        self.lineState = LineState()
        self.initDaemon()

    def updateState(self, selected, is_group):
        self.state.load(selected, is_group)
        log('new state:', self.state)
        self.app.updateState()

    def onInMainLoop(self):
        log('mloop forms', self._Forms)
        
    def initDaemon(self):
        log('main', self.app)
        self.daemonThread = SignalDaemonThread(self.app)
        self.daemonThread.start()

        self.messageThread = SignalMessageThread(self.app, self.message_queue)
        self.messageThread.start()

    def killMessageThread(self):
        self.message_queue.put({
            'exit': 1
        })

    def killDaemon(self):
        self.daemonPopen.kill()

    def handleExit(self):
        self.killMessageThread()
        self.killDaemon()

    def handleDaemonLine(self, line):
        self.lines.append(line)
        log('handleDaemonLine', line)
        regexes = {
            'init': r'Envelope from: \“([\w\d\s]*)\” (\+\d+) \(device: (\d+)\)',
            'timestamp': r'Timestamp: (\d+) \((.*)\)',
            'msgTimestamp': r'Message timestamp: (\d+) \((.*)\)',
            'toLine': r'To: \“([\w\d\s]*)\” (\+\d+) , Message timestamp: (\d+) \((.*)\)',
            'body': r'Body: (.*)'
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

            log('lineState', self.lineState)
            if self.lineState.is_ready():
                self.app.wMain.addDatedValues([
                    self.lineState.gen_line()
                ])
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

    def is_ready(self):
        return self.fromNumber and self.timestamp and self.messageBody

    def format_ts(self):
        return str(datetime.fromtimestamp(int(self.timestamp)/1000))[:19]

    def gen_line(self):
        if self.fromName:
            return (self.format_ts(), '{} ({})'.format(self.fromName, self.fromNumber), self.messageBody)
        return (self.format_ts(), '{}'.format(self.fromNumber), self.messageBody)

    def __str__(self):
        return "name: {} num: {} ts: {} body: {}".format(
            self.fromName, self.fromNumber, self.timestamp, self.messageBody)


class SignalDaemonThread(threading.Thread):
    app = None
    daemon = False
    def __init__(self, app):
        super(SignalDaemonThread, self).__init__()
        self.app = app

    def run(self):
        log('daemon thread')
        script = ['signal-cli', '-u', SELF_PHONE, 'daemon']
        #script = ['python3', 'sp.py']
        try:
            popen = execute_popen(script)
            self.app.parentApp.daemonPopen = popen
            for line in execute(popen):
                #log('queue event')
                self.app.parentApp.handleDaemonLine(line)
                self.app.parentApp.queue_event(npyscreen.Event("RELOAD"))
        except subprocess.CalledProcessError as e:
            pass
        log('daemon exit')

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
        self.send_message(state.toNumber, message)

    def send_message(self, number, message):
        log('send_message', number, message)
        script = ['signal-cli', '--dbus', 'send', str(number), '-m', message]
        popen = execute_popen(script)
        for line in execute(script):
            #log('queue event')
            self.app.parentApp.handleMessageLine(line)
            self.app.parentApp.queue_event(npyscreen.Event("RELOAD"))

        log('send_message done')

class SignalConfigData(object):
    data = None
    def __init__(self, phone):
        f = open('{}/.config/signal/data/{}'.format(pathlib.Path.home(), phone), 'r')
        self.data = json.loads(f.read())
        f.close()

    @property
    def groups(self):
        return self.data['groupStore']['groups']

    @property
    def contacts(self):
        return self.data['contactStore']['contacts']


if __name__ == '__main__':
    signal = SignalApp()
    signal.run()

    #print(npyscreen.wrapper_basic(formFunc))