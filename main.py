import npyscreen

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

class AppForm(npyscreen.FormMuttActiveTraditionalWithMenus):
	"""def create(self):
		self.wStatus1 = self.add(npyscreen.TitleText, name='status1')
		self.wStatus2 = self.add(npyscreen.TitleText, name='status2')
		self.wCommand = self.add(npyscreen.TitleText, name='command')
		self.wMain = self.add(npyscreen.TitleText, name='main')"""

	COMMAND_WIDGET_CLASS = npyscreen.TitleText
	COMMAND_WIDGET_NAME = 'Send: '
	COMMAND_WIDGET_BEGIN_ENTRY_AT = 1

	MAIN_WIDGET_CLASS = npyscreen.SimpleGrid

	def beforeEditing(self):
		self.wMain.always_show_cursor = False
		self.wMain.values = [
			('from', 'foo'),
			('from', 'bar')]
		self.wMain.display()

		self.wStatus1.value = 'Title'
		self.wStatus2.value = 'Title2'

		self.wCommand.name = 'command:'
		self.wCommand.display()

class SignalApp(npyscreen.NPSAppManaged):
	def onStart(self):
		#self.addForm('MAIN', MainForm, name='Enter Message')
		self.addForm('MAIN', AppForm, name='Application')


if __name__ == '__main__':
	signal = SignalApp()
	signal.run()

	#print(npyscreen.wrapper_basic(formFunc))