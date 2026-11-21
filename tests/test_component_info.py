from backend.component_info import COMPONENT_INFO, get_component_info


def test_component_info_formats_known_components():
    assert get_component_info("CPUFan") == (
        "Component: CPUFan\n"
        "Recyclable: Yes\n"
        "Hazardous: No"
    )
    assert get_component_info("LCDScreen") == (
        "Component: LCDScreen\n"
        "Recyclable: Partial\n"
        "Hazardous: Yes"
    )
    assert get_component_info("Battery") == (
        "Component: Battery\n"
        "Recyclable: Yes\n"
        "Hazardous: Yes"
    )


def test_component_info_handles_unknown_names():
    assert get_component_info("NewComponent") == (
        "Component: NewComponent\n"
        "Recyclable: Unknown\n"
        "Hazardous: Unknown"
    )
    assert get_component_info("") == (
        "Component: Unknown\n"
        "Recyclable: Unknown\n"
        "Hazardous: Unknown"
    )


def test_component_lookup_contains_all_model_classes():
    assert set(COMPONENT_INFO) == {
        "Battery",
        "DVDRom",
        "Hinge",
        "Keyboard",
        "Motherboard",
        "DCCable",
        "PowerSwitch",
        "RAM",
        "ScrewKit",
        "USBPort",
        "WifiCard",
        "Speaker",
        "CMOSBattery",
        "HardDiskDrive",
        "WebCam",
        "LCDScreen",
        "Bezel",
        "HeatSink",
        "SSD",
        "CPUFan",
        "TouchPad",
        "Processor",
        "RAMCover",
        "BasePanel",
        "TopPanel",
        "LVDSCable",
    }
    partial_classes = {
        name
        for name, (recyclable, _) in COMPONENT_INFO.items()
        if recyclable == "Partial"
    }
    hazardous_classes = {
        name
        for name, (_, hazardous) in COMPONENT_INFO.items()
        if hazardous == "Yes"
    }
    assert partial_classes == {
        "DVDRom",
        "Keyboard",
        "PowerSwitch",
        "WebCam",
        "LCDScreen",
        "TouchPad",
    }
    assert hazardous_classes == {
        "Battery",
        "Motherboard",
        "CMOSBattery",
        "LCDScreen",
    }
