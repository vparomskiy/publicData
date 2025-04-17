#!/usr/bin/env python3
"""
read_object_list_unicast.py

Discover a single BACnet/IP device via unicast Who‑Is, then
read its objectList and objectName for each entry.

Usage:
    ./read_object_list_unicast.py
        [--local-ip LOCAL_IP] [--local-port LOCAL_PORT]
        [--remote-ip REMOTE_IP] [--remote-port REMOTE_PORT]

Defaults:
  LOCAL_IP    = 0.0.0.0   (bind on all NICs)
  LOCAL_PORT  = 0         (OS picks ephemeral UDP port)
  REMOTE_IP   = 192.168.0.53
  REMOTE_PORT = 47808
"""

import sys
import argparse
from collections import deque

from bacpypes.core import run, deferred, stop
from bacpypes.local.device import LocalDeviceObject
from bacpypes.app import BIPSimpleApplication
from bacpypes.pdu import Address
from bacpypes.primitivedata import ObjectIdentifier, CharacterString
from bacpypes.constructeddata import ArrayOf
from bacpypes.apdu import (
    WhoIsRequest, IAmRequest,
    ReadPropertyRequest, ReadPropertyACK
)
from bacpypes.iocb import IOCB

# ---- configure your client/device here if needed ----
CLIENT_DEVICE_ID   = 599
CLIENT_DEVICE_NAME = "BACpypesUnicastClient"
# ------------------------------------------------------

ArrayOfObjectIdentifier = ArrayOf(ObjectIdentifier)

class BACnetBrowser(BIPSimpleApplication):
    def __init__(self, local_device, local_addr, remote_addr):
        super().__init__(local_device, local_addr)
        self.remote_addr = remote_addr
        deferred(self.send_whois)

    def send_whois(self):
        """Send a Who-Is directly to the remote device (no broadcast)."""
        req = WhoIsRequest()
        req.pduDestination = self.remote_addr
        self.request(req)

    def indication(self, apdu):
        """Catch the I-Am from the device under test."""
        if isinstance(apdu, IAmRequest):
            dev_id   = apdu.deviceIdentifier
            dev_addr = apdu.pduSource
            print(f"→ I-Am received: instance {dev_id} @ {dev_addr}\n")
            # step into reading its object list
            self.read_object_list(dev_id, dev_addr)

    def read_object_list(self, device_id, device_addr):
        """Read the `objectList` property (ArrayOf(ObjectIdentifier))."""
        ctx = {
            'object_list': [],
            'object_names': [],
        }
        req = ReadPropertyRequest(
            objectIdentifier=device_id,
            propertyIdentifier='objectList',
            destination=device_addr,
        )
        iocb = IOCB(req)
        iocb.context = ctx
        iocb.add_callback(self._on_object_list)
        self.request_io(iocb)

    def _on_object_list(self, iocb):
        ctx = iocb.context
        if iocb.ioError:
            print("Error reading objectList:", iocb.ioError)
            stop(); return

        apdu = iocb.ioResponse
        if not isinstance(apdu, ReadPropertyACK):
            print("Unexpected response type:", type(apdu))
            stop(); return

        ctx['object_list'] = apdu.propertyValue.cast_out(ArrayOfObjectIdentifier)
        ctx['_queue']      = deque(ctx['object_list'])

        print(f"→ {len(ctx['object_list'])} objects found; fetching names…\n")
        deferred(self._read_next_name, ctx)

    def _read_next_name(self, ctx):
        """Sequentially read objectName for each objectIdentifier."""
        if not ctx['_queue']:
            # all done, print summary
            for oid, name in zip(ctx['object_list'], ctx['object_names']):
                print(f"{oid}: {name}")
            stop(); return

        oid = ctx['_queue'].popleft()
        req = ReadPropertyRequest(
            objectIdentifier=oid,
            propertyIdentifier='objectName',
            destination=self.remote_addr,
        )
        iocb = IOCB(req)
        iocb.context = ctx
        iocb.add_callback(self._on_object_name)
        self.request_io(iocb)

    def _on_object_name(self, iocb):
        ctx = iocb.context
        if iocb.ioError:
            ctx['object_names'].append(f"<error: {iocb.ioError}>")
        else:
            apdu = iocb.ioResponse
            ctx['object_names'].append(
                apdu.propertyValue.cast_out(CharacterString)
            )
        deferred(self._read_next_name, ctx)


def main():
    parser = argparse.ArgumentParser(description="Read BACnet object list via unicast")
    parser.add_argument("--local-ip",    default="0.0.0.0",
                        help="Local bind IP (default: all interfaces)")
    parser.add_argument("--local-port",  type=int, default=0,
                        help="Local UDP port (0 ⇒ ephemeral)")
    parser.add_argument("--remote-ip",   default="192.168.0.53",
                        help="BACnet controller IP")
    parser.add_argument("--remote-port", type=int, default=47808,
                        help="BACnet controller port")
    args = parser.parse_args()

    # compose address tuples
    local_addr  = f"{args.local_ip}:{args.local_port}"
    remote_addr = Address(f"{args.remote_ip}:{args.remote_port}")

    # build our BACnet client device
    local_device = LocalDeviceObject(
        objectName=CLIENT_DEVICE_NAME,
        objectIdentifier=CLIENT_DEVICE_ID,
        maxApduLengthAccepted=1024,
        segmentationSupported="segmentedBoth",
        vendorIdentifier=15,
    )

    # launch the app
    app = BACnetBrowser(local_device, local_addr, remote_addr)
    run()


if __name__ == "__main__":
    main()
