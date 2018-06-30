# signal-curses
Curses-backed terminal interface for [Signal](https://signal.org) using [signal-cli](https://github.com/AsamK/signal-cli) and [npyscreen](https://github.com/npcole/npyscreen).

Setup
=====
* Install signal-cli (see [Installation](https://github.com/AsamK/signal-cli/blob/master/README.md)) and libunixsocket-java (see [DBus service](https://github.com/AsamK/signal-cli/wiki/DBus-service)).
* Install deps with ```pip install -r requirements.txt```
* Run with ```python3 main.py -u '+12345678901'```
* If signal-cli has not been run before, you will be prompted to link your phone with your computer. Scan the given terminal QR code in the Signal app under Settings > Linked Devices, and restart signal-curses. Your contacts and groups should appear, and you should be able to send messages.
