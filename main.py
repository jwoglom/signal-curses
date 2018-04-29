import npyscreen
import curses
import subprocess
import threading
import re
from contextlib import redirect_stdout
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

def execute(cmd):
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line 
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)

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

	def addDatedValues(self, values):
		self._real_values += values

		#self.update()

class AppMessageBox(npyscreen.TitleText):
	def set_up_handlers(self):
		super(AppMessageBox, self).set_up_handlers()
		self.handlers[curses.KEY_ENTER] = self._handleEnter

	def _handleEnter(self, inp):
		log('handleEnter', inp)


class AppForm(npyscreen.FormMuttActiveTraditionalWithMenus):
	COMMAND_WIDGET_CLASS = AppMessageBox
	COMMAND_WIDGET_NAME = 'Send: '
	COMMAND_WIDGET_BEGIN_ENTRY_AT = 1
	MAIN_WIDGET_CLASS = MessagesLine

	def create(self):
		self.m1 = self.add_menu(name="Main Menu", shortcut="^X")
		self.m1.addItemsFromList([
			("Add Lines", self.whenAddLines, None, None, ("blah",)),
			("Switch", self.whenSwitch, None, None, ("blah",)),
			("Exit", self.whenExit, "e"),
		])

		self.add_event_hander("RELOAD", self.reloadHandler)
		super(AppForm, self).create()

	def reloadHandler(self, event):
		#log('reloadHandler')
		self.wMain.update()

	def whenAddLines(self, arg):
		self.wMain.addValues([
		('John Doe', 'text '*10),
		('Bob Smith', 'text '*50),])
		
	def whenSwitch(self, arg):
		self._updateTitle('John Smith')

	def whenExit(self):
		self.parentApp.setNextForm(None)
		self.editing = False
		self.parentApp.switchFormNow()

	def beforeEditing(self):
		self.wMain.always_show_cursor = False
		self.wMain.addValues([
		#	('*', 'Connecting...',),
		])
		self.wMain.display()

		self._updateTitle('John Doe')

	def _updateTitle(self, name):
		self.wStatus1.value = 'Signal: {} '.format(name)
		self.wStatus2.value = '{} '.format(name)
		self.wStatus1.display()
		self.wStatus2.display()

class SignalApp(npyscreen.StandardApp):
	app = None
	daemonThread = None
	lines = []
	lineState = None
	def onStart(self):
		#self.addForm('MAIN', MainForm, name='Enter Message')
		self.addForm('MAIN', AppForm, name='Application')
		log('start forms', self._Forms)
		self.app = self.getForm('MAIN')

		self.lineState = LineState()
		self.initDaemon()

	def onInMainLoop(self):
		log('mloop forms', self._Forms)
		
	def initDaemon(self):
		log('main', self.app)
		self.daemonThread = SignalDaemonThread(self.app)
		self.daemonThread.start()

	def handleLine(self, line):
		self.lines.append(line)
		log('handleLine', line)
		regexes = {
			'init': r'Envelope from: \“([\w\d\s]*)\” (\+\d+) \(device: (\d+)\)',
			'timestamp': r'Timestamp: (\d+) \((.*)\)',
			'msgTimestamp': r'Message timestamp: (\d+) \((.*)\)',
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
			elif typ == 'body':
				self.lineState.messageBody = match[0]

			log('lineState', self.lineState)
			if self.lineState.is_ready():
				self.app.wMain.addDatedValues([
					self.lineState.gen_line()
				])
				self.lineState = LineState()

		#self.app.wMain.addValues([('*', line)])

class LineState(object):
	fromName = None
	fromNumber = None
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
		#script = ["dbus-launch", "signal-cli", "-u '***REMOVED***'", "daemon"]
		script = ['python3', 'sp.py']
		for line in execute(script):
			#log('queue event')
			self.app.parentApp.handleLine(line)
			self.app.parentApp.queue_event(npyscreen.Event("RELOAD"))

		log('daemon exit')



if __name__ == '__main__':
	signal = SignalApp()
	signal.run()

	#print(npyscreen.wrapper_basic(formFunc))