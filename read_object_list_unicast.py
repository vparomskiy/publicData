#!/usr/bin/env python3
"""
query_objects.py
----------------
Unicast‑queries a BACnet/IP device for its object list.

usage:
    python query_objects.py 195.168.0.53               # default BACnet port 47808
    python query_objects.py 195.168.0.53 47810         # non‑standard remote port

If you already know the device‑instance ID you may pass it with -d/--device.
"""

import sys
import argparse
import types
from bacpypes.core import run, stop, enable_sleeping
from bacpypes.pdu import Address
from bacpypes.app import BIPSimpleApplication
from bacpypes.local.device import LocalDeviceObject
from bacpypes.basetypes import ServicesSupported
from bacpypes.apdu import (
    WhoIsRequest,
    IAmRequest,
    ReadPropertyRequest,
    ReadPropertyACK,
    Error,
    AbortPDU,
    RejectPDU,
)
from bacpypes.primitivedata import ObjectIdentifier
from bacpypes.constructeddata import ArrayOf

# --------------------------------------------------------------------------- #
def make_local_device(device_id: int = 599):
    """
    Create a minimal local Device object *without* trying to override
    protocolServicesSupported in the constructor – we tweak it afterwards.
    """
    ldev = LocalDeviceObject(
        objectName="BacpypesClient",
        objectIdentifier=("device", device_id),
        maxApduLengthAccepted=1024,
        segmentationSupported="noSegmentation",
        vendorIdentifier=999,
    )

    # turn on only the client services we need
    pss = ldev.protocolServicesSupported
    pss["whoIs"] = True
    pss["readProperty"] = True

    return ldev


# --------------------------------------------------------------------------- #
class ClientApplication(BIPSimpleApplication):
    """
    Derived application that handles:
      * I-Am → grab device instance, then send ReadProperty(objectList)
      * ReadPropertyACK → print & exit
    """

    def __init__(self, *args, target_addr: Address, target_port: int, device_instance: int | None):
        super().__init__(*args)
        self.target = Address(f"{target_addr}:{target_port}")
        self.known_device_instance = device_instance
        enable_sleeping()       # allow other threads to run

    # -- started by bacpypes core ------------------------------------------------
    def request_device_information(self):
        """Kick‑off after the core is running."""
        if self.known_device_instance is not None:
            self.read_object_list(self.known_device_instance)
        else:
            # Send unicast Who‑Is (device range 0‑4194303)
            who_is = WhoIsRequest()
            who_is.pduDestination = self.target
            print(f">>> Who‑Is → {self.target}")
            self.request(who_is)

    def indication(self, apdu):
        """We override to call request_device_information once the stack is ready."""
        # The first time indication() is called the network layer is up.
        self.indication = super().indication  # restore original
        self.request_device_information()
        super().indication(apdu)

    # -- incoming APDUs ----------------------------------------------------------
    def confirmation(self, apdu):
        if isinstance(apdu, IAmRequest):
            dev_instance = apdu.iAmDeviceIdentifier[1]
            print(f"<<< I‑Am from {apdu.pduSource} (device‑instance={dev_instance})")
            self.read_object_list(dev_instance)

        elif isinstance(apdu, ReadPropertyACK):
            value = apdu.propertyValue
            # objectList is an ArrayOf(ObjectIdentifier)
            if isinstance(value, ArrayOf):
                objects = [f"{obj[0]}:{obj[1]}" for obj in value.value]
                print("\n--- Object List ---")
                for idx, obj in enumerate(objects, 1):
                    print(f"{idx:3d}. {obj}")
                print("-------------------")
            else:
                print("Received unexpected datatype:", value)

            stop()  # all done

        elif isinstance(apdu, (Error, AbortPDU, RejectPDU)):
            print("BACnet error:", apdu)
            stop()

        else:
            # forward anything we don't care about
            super().confirmation(apdu)

    # -- helpers -----------------------------------------------------------------
    def read_object_list(self, device_instance: int):
        """Send ReadProperty(Device, objectList) to already‑known instance."""
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
    parser.add_argument("port", nargs='?', default=47808, type=int, help="target UDP port (default 47808)")
    parser.add_argument("-d", "--device", type=int, help="device‑instance ID (skip Who‑Is)")
    parser.add_argument("-l", "--local-port", type=int, default=47809,
                        help="local UDP port to bind (FREE; default 47809)")
    args = parser.parse_args()

    # Build local device and application
    this_device = make_local_device()
    app = ClientApplication(
        this_device,
        f"0.0.0.0:{args.local_port}",        # let OS choose IF; avoid busy 47808
        target_addr=args.ip,
        target_port=args.port,
        device_instance=args.device,
    )

    try:
        run()   # blocks until stop() is called
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":          # pragma: no cover
    main()
