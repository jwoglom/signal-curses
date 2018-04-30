# signal-curses
Curses-backed terminal interface for [Signal](https://signal.org) using [signal-cli](https://github.com/AsamK/signal-cli) and [npyscreen](https://github.com/npcole/npyscreen).

Setup
=====
* Install signal-cli (see [Installation](https://github.com/AsamK/signal-cli/blob/master/README.md)) and libunixsocket-java (see [DBus service](https://github.com/AsamK/signal-cli/wiki/DBus-service)).
* Link with your primary Signal device by running  ```signal-cli link -d "device name"```, pasting the given URL into a QR code generator, and scanning it on your phone on the "Linked devices" screen.
* Install deps with ```pip install -r requirements.txt```
* Run with ```python3 main.py -u '+12345678901'```
