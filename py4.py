#!/usr/bin/env python3
"""
read_object_list_unicast.py
===========================

Unicast BACnet/IP client that fetches a device's objectList and writes all
output (DEBUG‑level) to `src.log`.

Usage
-----
    python read_object_list_unicast.py 192.168.0.53
    python read_object_list_unicast.py 192.168.0.53 47810  --local-port 47820
    python read_object_list_unicast.py 192.168.0.53 -d 400001
    python read_object_list_unicast.py 192.168.0.53 --quiet   # only warnings+

Options
-------
  ip                 target device IP address (BACnet/IP)
  port               target UDP port (default 47808)
  -l, --local-port   free local UDP port to bind (default 47809)
  -d, --device       device‑instance ID (skip Who‑Is)
  --quiet            keep only WARNING+ in the log
  --verbose          force DEBUG even if later reduced in code
"""

# ──────────────────────────  universal logging setup  ───────────────────────
import sys
import logging
from logging.handlers import RotatingFileHandler

LOG_FILE = "src.log"
_MAX_BYTES = 2 * 1024 * 1024   # 2 MiB before rotating
_BACKUPS   = 3                 # src.log, src.log.1 … src.log.3

root_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
)
root_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)8s] %(name)s: %(message)s"
))
logging.basicConfig(level=logging.DEBUG, handlers=[root_handler])

# redirect stdout / stderr to the same file (line‑buffered)
sys.stdout = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
sys.stderr = sys.stdout

log = logging.getLogger(__name__)

# ──────────────────────────  BACpypes imports  ──────────────────────────────
import argparse
from bacpypes.core import run, stop, enable_sleeping, deferred
from bacpypes.pdu import Address
from bacpypes.app import BIPSimpleApplication
from bacpypes.local.device import LocalDeviceObject
from bacpypes.apdu import (
    WhoIsRequest, IAmRequest,
    ReadPropertyRequest, ReadPropertyACK,
    Error, AbortPDU, RejectPDU,
)
from bacpypes.constructeddata import ArrayOf

# push BACpypes' own loggers to DEBUG so wire‑level details are captured
for mod_name in ("bacpypes", "bacpypes.app", "bacpypes.core", "bacpypes.comm"):
    logging.getLogger(mod_name).setLevel(logging.DEBUG)

# ──────────────────────────  helper functions  ──────────────────────────────
def make_local_device(device_id: int = 599) -> LocalDeviceObject:
    """Return a minimal LocalDeviceObject for use as a client."""
    return LocalDeviceObject(
        objectName="BacpypesClient",
        objectIdentifier=("device", device_id),
        maxApduLengthAccepted=1024,
        segmentationSupported="noSegmentation",
        vendorIdentifier=999,
    )

# ──────────────────────────  BACnet client app  ─────────────────────────────
class ClientApplication(BIPSimpleApplication):
    """Unicast objectList reader."""

    def __init__(self, local_device, local_addr: str,
                 target_addr: str, target_port: int,
                 device_instance: int | None):
        super().__init__(local_device, local_addr)
        self.target = Address(f"{target_addr}:{target_port}")
        self.known_device_instance = device_instance
        enable_sleeping()

        log.debug("ClientApplication initialised (target %s)", self.target)

        # schedule first action when the reactor starts
        deferred(self._kickoff)

    # --------------------------------------------------------------------- #
    def _kickoff(self):
        if self.known_device_instance is not None:
            log.debug("deviceInstance pre‑supplied → skip Who‑Is")
            self._read_object_list(self.known_device_instance)
        else:
            who_is = WhoIsRequest()
            who_is.pduDestination = self.target
            log.info("Who‑Is → %s", self.target)
            self.request(who_is)

    # --------------------------------------------------------------------- #
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
                log.error("Unexpected datatype: %r", value)
            stop()

        elif isinstance(apdu, (Error, AbortPDU, RejectPDU)):
            log.error("BACnet error: %s", apdu)
            stop()
        else:
            super().confirmation(apdu)

    # --------------------------------------------------------------------- #
    def _read_object_list(self, device_instance: int):
        req = ReadPropertyRequest(
            objectIdentifier=('device', device_instance),
            propertyIdentifier='objectList',
        )
        req.pduDestination = self.target
        log.info("ReadProperty(objectList) → %s (device %d)",
                 self.target, device_instance)
        self.request(req)

# ──────────────────────────  main entry point  ──────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Unicast BACnet/IP object‑list reader (all logs → src.log)"
    )
    parser.add_argument("ip", help="target BACnet/IP address")
    parser.add_argument("port", nargs="?", default=47808, type=int,
                        help="target UDP port (default 47808)")
    parser.add_argument("-d", "--device", type=int,
                        help="device‑instance ID (skip Who‑Is)")
    parser.add_argument("-l", "--local-port", type=int, default=47809,
                        help="free local UDP port to bind (default 47809)")
    parser.add_argument("--quiet", action="store_true",
                        help="keep only WARNING+ entries in src.log")
    parser.add_argument("--verbose", action="store_true",
                        help="force DEBUG level even if later reduced")
    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    elif args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=== run started ===")

    this_device = make_local_device()
    _ = ClientApplication(
        this_device,
        f"0.0.0.0:{args.local_port}",
        target_addr=args.ip,
        target_port=args.port,
        device_instance=args.device,
    )

    try:
        run()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        log.info("=== run finished ===")

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
