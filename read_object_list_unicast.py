#!/usr/bin/env python3
"""
list_objects.py

Discover a single BACnet device at a known IP:port (no broadcast),
read its objectList, print to console, and exit.
"""

import sys
import argparse

from bacpypes.core import run, stop
from bacpypes.app import BIPSimpleApplication
from bacpypes.local.device import LocalDeviceObject
from bacpypes.pdu import Address
from bacpypes.apdu import (
    WhoIsRequest,
    IAmRequest,
    ReadPropertyRequest,
    ReadPropertyACK,
)


class BACnetClient(BIPSimpleApplication):
    def __init__(self, device, local_address):
        super().__init__(device, local_address)
        self._remote_instance = None
        self._object_list = None

    def confirmation(self, apdu):
        # Handle IAm (instance discovery)
        if isinstance(apdu, IAmRequest):
            # apdu.iAmDeviceIdentifier is a tuple ( 'device', instance )
            self._remote_instance = apdu.iAmDeviceIdentifier[1]
            # once we have the instance, stop the current run loop
            stop()

        # Handle ReadProperty ACK
        elif isinstance(apdu, ReadPropertyACK):
            # propertyValue.cast_out() returns a list of objectIdentifier tuples
            self._object_list = apdu.propertyValue.cast_out()
            stop()

    @property
    def remote_instance(self):
        return self._remote_instance

    @property
    def object_list(self):
        return self._object_list


def main():
    p = argparse.ArgumentParser(
        description="Read objectList from a BACnet device via unicast."
    )
    p.add_argument(
        "--local-ip", required=True,
        help="Local IPv4 address to bind (must be on 192.168.0.x)"
    )
    p.add_argument(
        "--local-port", type=int, default=47809,
        help="Local UDP port (must not be 47808)"
    )
    p.add_argument(
        "--remote-ip", default="192.168.0.53",
        help="BACnet device IP (default: 192.168.0.53)"
    )
    p.add_argument(
        "--remote-port", type=int, default=47808,
        help="BACnet device port (default: 47808)"
    )
    p.add_argument(
        "--remote-instance", type=int,
        help="If known, the device instance number; skips WhoIs"
    )
    args = p.parse_args()

    # 1) build our local device object
    device = LocalDeviceObject(
        objectName="bacpypes-client",
        objectIdentifier=599,             # your client’s device instance #
        maxApduLengthAccepted=1024,
        segmentationSupported="segmentedBoth",
        vendorIdentifier=15,
    )

    # 2) start the BACnet/IP application on local_ip:local_port
    local_addr = f"{args.local_ip}:{args.local_port}"
    app = BACnetClient(device, local_addr)

    # 3) discover remote instance if needed
    instance = args.remote_instance
    if instance is None:
        print(f"→ Sending directed WhoIs to {args.remote_ip}:{args.remote_port} …")
        whois = WhoIsRequest()
        whois.pduDestination = Address(f"{args.remote_ip}:{args.remote_port}")
        app.request(whois)
        run()
        instance = app.remote_instance
        if instance is None:
            print("✖ IAm not received; exiting.")
            sys.exit(1)
        print(f"← Discovered device instance: {instance}")

    # 4) request objectList from that device instance
    print(f"→ Reading objectList from instance {instance} …")
    rp = ReadPropertyRequest(
        objectIdentifier=('device', instance),
        propertyIdentifier='objectList'
    )
    rp.pduDestination = Address(f"{args.remote_ip}:{args.remote_port}")
    app.request(rp)
    run()

    # 5) print the result
    objs = app.object_list
    if objs is None:
        print("✖ No ReadPropertyACK received; exiting.")
        sys.exit(1)

    print("← objectList:")
    for obj in objs:
        # each obj is a tuple like ('analogInput', 1)
        print(f" - {obj[0]} #{obj[1]}")

if __name__ == "__main__":
    main()
