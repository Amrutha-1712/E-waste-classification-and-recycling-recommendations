from __future__ import annotations

COMPONENT_INFO: dict[str, tuple[str, str]] = {
    "Battery": ("Yes", "Yes"),
    "DVDRom": ("Partial", "No"),
    "Hinge": ("Yes", "No"),
    "Keyboard": ("Partial", "No"),
    "Motherboard": ("Yes", "Yes"),
    "DCCable": ("Yes", "No"),
    "PowerSwitch": ("Partial", "No"),
    "RAM": ("Yes", "No"),
    "ScrewKit": ("Yes", "No"),
    "USBPort": ("Yes", "No"),
    "WifiCard": ("Yes", "No"),
    "Speaker": ("Yes", "No"),
    "CMOSBattery": ("Yes", "Yes"),
    "HardDiskDrive": ("Yes", "No"),
    "WebCam": ("Partial", "No"),
    "LCDScreen": ("Partial", "Yes"),
    "Bezel": ("Yes", "No"),
    "HeatSink": ("Yes", "No"),
    "SSD": ("Yes", "No"),
    "CPUFan": ("Yes", "No"),
    "TouchPad": ("Partial", "No"),
    "Processor": ("Yes", "No"),
    "RAMCover": ("Yes", "No"),
    "BasePanel": ("Yes", "No"),
    "TopPanel": ("Yes", "No"),
    "LVDSCable": ("Yes", "No"),
}


def get_component_info(predicted_class: str) -> str:
    component_name = (
        predicted_class
        if isinstance(predicted_class, str) and predicted_class
        else "Unknown"
    )
    info = COMPONENT_INFO.get(component_name)
    if info is None:
        recyclable, hazardous = "Unknown", "Unknown"
    else:
        recyclable, hazardous = info

    return (
        f"Component: {component_name}\n"
        f"Recyclable: {recyclable}\n"
        f"Hazardous: {hazardous}"
    )
