#!/usr/bin/env python3
"""
read_object_list_unicast.py
Query a BACnet/IP device for its objectList via unicast.
"""

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
from bacpypes.primitivedata import ObjectIdentifier
from bacpypes.constructeddata import ArrayOf


# --------------------------------------------------------------------------- #
def make_local_device(device_id: int = 599):
    """Create a bare‑bones LocalDeviceObject – no extra tweaking needed."""
    return LocalDeviceObject(
        objectName="BacpypesClient",
        objectIdentifier=("device", device_id),
        maxApduLengthAccepted=1024,
        segmentationSupported="noSegmentation",
        vendorIdentifier=999,
    )


# --------------------------------------------------------------------------- #
class ClientApplication(BIPSimpleApplication):
    """Handle I‑Am and ReadProperty responses."""

    def __init__(self, *args, target_addr: Address, target_port: int,
                 device_instance: int | None):
        super().__init__(*args)
        self.target = Address(f"{target_addr}:{target_port}")
        self.known_device_instance = device_instance
        enable_sleeping()

    # first call after the stack comes up
    def indication(self, apdu):
        self.indication = super().indication          # restore default
        self.kickoff()                                # start our logic
        super().indication(apdu)

    def kickoff(self):
        if self.known_device_instance is not None:
            self.read_object_list(self.known_device_instance)
        else:
            who_is = WhoIsRequest()
            who_is.pduDestination = self.target
            print(f">>> Who‑Is → {self.target}")
            self.request(who_is)

    def confirmation(self, apdu):
        if isinstance(apdu, IAmRequest):
            dev_inst = apdu.iAmDeviceIdentifier[1]
            print(f"<<< I‑Am from {apdu.pduSource} (device‑instance={dev_inst})")
            self.read_object_list(dev_inst)

        elif isinstance(apdu, ReadPropertyACK):
            value = apdu.propertyValue
            if isinstance(value, ArrayOf):
                print("\n--- Object List ---")
                for idx, obj in enumerate(value.value, 1):
                    print(f"{idx:3d}. {obj[0]}:{obj[1]}")
                print("-------------------")
            else:
                print("Received unexpected datatype:", value)
            stop()

        elif isinstance(apdu, (Error, AbortPDU, RejectPDU)):
            print("BACnet error:", apdu)
            stop()
        else:
            super().confirmation(apdu)

    # helper ---------------------------------------------------------------
    def read_object_list(self, device_instance: int):
        req = ReadPropertyRequest(
            objectIdentifier=('device', device_instance),
            propertyIdentifier='objectList',
        )
        req.pduDestination = self.target
        print(f">>> ReadProperty(objectList) → {self.target} (device {device_instance})")
        self.request(req)


# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ip", help="target BACnet/IP address")
    parser.add_argument("port", nargs="?", default=47808, type=int,
                        help="target UDP port (default 47808)")
    parser.add_argument("-d", "--device", type=int,
                        help="device‑instance ID (skip Who‑Is)")
    parser.add_argument("-l", "--local-port", type=int, default=47809,
                        help="free local UDP port (default 47809)")
    args = parser.parse_args()

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
        pass


if __name__ == "__main__":
    main()
