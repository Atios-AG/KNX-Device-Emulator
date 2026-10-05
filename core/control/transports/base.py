"""Base class for control transports.

A transport delivers commands from the outside in and calls the single
ControlInterface.execute(). All the transports are interchangeable; adding a
new one (MQTT, for example) means one more file next to these, same as a
device plugin.
"""

from __future__ import annotations

from ..interface import ControlInterface


class ControlTransport:
    #: the name used in [control] transport = ...
    NAME: str = ""

    def __init__(self, interface: ControlInterface, config: dict[str, str]):
        self.interface = interface
        self.config = config
        #: called by the transport when it asks to terminate the application
        #: (on the quit command, for example). Set from main.py.
        self.on_stop = None

    def request_stop(self) -> None:
        if self.on_stop is not None:
            self.on_stop()

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
