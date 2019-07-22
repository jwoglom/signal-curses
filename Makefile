SIGNALCLI_VERSION=0.6.2

java:
ifeq (, $(shell which java))
	$(warning java not installed)
	sudo apt-get install default-jre
else
	$(warning java installed)
endif

signal-cli:
ifeq (, $(shell which signal-cli))
	$(warning signal-cli is not in PATH, adding to /usr/local/bin)
	wget https://github.com/AsamK/signal-cli/releases/download/v${SIGNALCLI_VERSION}/signal-cli-${SIGNALCLI_VERSION}.tar.gz -O /tmp/signal-cli-${SIGNALCLI_VERSION}.tar.gz && \
	sudo tar xf /tmp/signal-cli-${SIGNALCLI_VERSION}.tar.gz -C /opt && \
	sudo ln -sf /opt/signal-cli-${SIGNALCLI_VERSION}/bin/signal-cli /usr/local/bin/
else
	$(warning signal-cli installed)
endif


libunixsocket-java:
ifeq (, $(shell ls /usr/lib/jni/libunix-java.so))
	$(warning libunix-java JNI module not found, installing libunixsocket-java)
	sudo apt-get install libunixsocket-java
else
	$(warning libunixsocket-java installed)
endif

python-gobject:
ifeq (, $(shell ls /usr/lib/python3/dist-packages/gi))
	$(warning gi not found in python3 dist-packages)
	sudo apt-get install python-gobject libgirepository1.0-dev libglib2.0-dev libcairo2-dev libffi-dev python3-gi
else
	$(warning python-gobject installed)
endif

pkg-config:
ifeq (, $(shell which pkg-config))
	$(warning pkg-config not installed)
	sudo apt-get install pkg-config
else
	$(warning pkg-config installed)
endif

pipenv:
	$(warning installing pipenv)	
	pipenv install

install: java signal-cli libunixsocket-java python-gobject pkg-config pipenv

