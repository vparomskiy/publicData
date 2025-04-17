#!/usr/bin/env python3
"""
read_object_list_unicast.py
Collects a BACnet/IP device's objectList via unicast and writes all output to
'src.log' instead of the console.
"""

# --------------------------------------------------------------------------- #
# universal logging / silence‑to‑file setup
import sys
import logging
log_file = "src.log"

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

# Redirect anything that mistakenly goes to stdout/stderr.
# (buffering=1 ==> line‑buffered so messages appear promptly.)
sys.stdout = open(log_file, "a", buffering=1)
sys.stderr = open(log_file, "a", buffering=1)

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
import argparse
from bacpypes.core import run, stop, enable_sleeping
from bacpypes.pdu import Address
from bacpypes.app import BIPSimpleApplication
from bacpypes.local.device import LocalDeviceObject
from bacpypes.apdu import (
    WhoIsRequest, IAmRequest,
    ReadPropertyRequest, ReadPropertyACK,
    Error, AbortPDU, RejectPDU,
)
from bacpypes.constructeddata import ArrayOf

# --------------------------------------------------------------------------- #
def make_local_device(device_id: int = 599) -> LocalDeviceObject:
    """Return a bare‑bones LocalDeviceObject."""
    return LocalDeviceObject(
        objectName="BacpypesClient",
        objectIdentifier=("device", device_id),
        maxApduLengthAccepted=1024,
        segmentationSupported="noSegmentation",
        vendorIdentifier=999,
    )

# --------------------------------------------------------------------------- #
class ClientApplication(BIPSimpleApplication):
    """Minimal client that asks for objectList then exits."""

    def __init__(self, *args, target_addr: str, target_port: int,
                 device_instance: int | None):
        super().__init__(*args)
        self.target = Address(f"{target_addr}:{target_port}")
        self.known_device_instance = device_instance
        enable_sleeping()

    # first callback once the stack is up ----------------------------------
    def indication(self, apdu):
        self.indication = super().indication
        self._kickoff()
        super().indication(apdu)

    def _kickoff(self):
        if self.known_device_instance is not None:
            self._read_object_list(self.known_device_instance)
        else:
            who_is = WhoIsRequest()
            who_is.pduDestination = self.target
            log.info("Who‑Is → %s", self.target)
            self.request(who_is)

    # incoming APDUs -------------------------------------------------------
    def confirmation(self, apdu):
        if isinstance(apdu, IAmRequest):
            dev_inst = apdu.iAmDeviceIdentifier[1]
            log.info("I‑Am ← %s (device‑instance=%d)", apdu.pduSource, dev_inst)
            self._read_object_list(dev_inst)

        elif isinstance(apdu, ReadPropertyACK):
            value = apdu.propertyValue
            if isinstance(value, ArrayOf):
                log.info("--- Object List start ---")
                for idx, obj in enumerate(value.value, 1):
                    log.info("%3d. %s:%d", idx, obj[0], obj[1])
                log.info("--- Object List end -----")
            else:
                log.error("Unexpected datatype in ReadPropertyACK: %r", value)
            stop()

        elif isinstance(apdu, (Error, AbortPDU, RejectPDU)):
            log.error("BACnet error: %s", apdu)
            stop()
        else:
            super().confirmation(apdu)

    # helper --------------------------------------------------------------
    def _read_object_list(self, device_instance: int):
        req = ReadPropertyRequest(
            objectIdentifier=('device', device_instance),
            propertyIdentifier='objectList',
        )
        req.pduDestination = self.target
        log.info("ReadProperty(objectList) → %s (device %d)",
                 self.target, device_instance)
        self.request(req)

# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Unicast BACnet/IP object‑list reader (logs → src.log)"
    )
    parser.add_argument("ip", help="target BACnet/IP address")
    parser.add_argument("port", nargs="?", default=47808, type=int,
                        help="target UDP port (default 47808)")
    parser.add_argument("-d", "--device", type=int,
                        help="device‑instance ID (skip Who‑Is)")
    parser.add_argument("-l", "--local-port", type=int, default=47809,
                        help="free local UDP port to bind (default 47809)")
    args = parser.parse_args()

    # Build local device and application
    this_device = make_local_device()
    app = ClientApplication(
        this_device,
        f"0.0.0.0:{args.local_port}",
        target_addr=args.ip,
        target_port=args.port,
        device_instance=args.device,
    )

    try:
        run()
    except KeyboardInterrupt:
        # even Ctrl‑C shouldn't write to console
        log.info("Interrupted by user")

# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    main()
