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

import curses
import npyscreen
import time

from datetime import datetime

from scurses.models.send import CurrentSend
from scurses.utils.logger import log

__all__ = ['MessagesLine']


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
        self._size = min(max([len(i[1])
                              for i in self._real_values]), self._size_max)

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
        first_beg = beg_fmt.format(
            val[0], self._gen_line_max(val[1], size_max))
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
                    ln += (' ' * (self.width - len(ln) -
                                  len(val[3]) - 1)) + val[3]
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

        # self.update()

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


CURSES_OTHER_ENTER = 10

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