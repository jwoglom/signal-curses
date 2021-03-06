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

import os
import pathlib

__all__ = ['default_config_dir']


def _possible_config_folders():
    folders = []
    configFolder = os.getenv('XDG_DATA_HOME')
    if configFolder:
        folders.append(os.path.join(configFolder, 'signal-cli'))
    else:
        folders.append(os.path.join(
            pathlib.Path.home(), '.local/share/signal-cli'))

    folders.append(os.path.join(pathlib.Path.home(), '.config/signal'))
    folders.append(os.path.join(pathlib.Path.home(), '.config/textsecure'))

    return folders


def default_config_dir():
    for f in _possible_config_folders():
        if os.path.exists(f):
            return f
    return _possible_config_folders()[0]
