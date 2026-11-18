from __future__ import annotations

from typing import TypedDict


class RecommendationDetails(TypedDict):
    reuse: str
    handling: str
    recycling: str
    safety: str


class Recommendation(RecommendationDetails):
    disposition: str


RECOMMENDATIONS: dict[str, RecommendationDetails] = {
    "Battery": {
        "reuse": "Reuse only if the pack is undamaged and can be safely tested.",
        "handling": "Do not puncture, crush, bend, or short the terminals.",
        "recycling": "Take it to a battery take-back point or a certified e-waste recycler.",
        "safety": "Keep swollen, hot, leaking, or damaged batteries away from people and combustible materials; contact a qualified handler.",
    },
    "DVDRom": {
        "reuse": "Test the drive and reuse it where compatible.",
        "handling": "Remove it without bending the metal casing or exposed connector.",
        "recycling": "Send an unusable drive to an e-waste recycler for metal and electronic-material recovery.",
        "safety": "Do not dismantle the optical mechanism; follow local e-waste collection rules.",
    },
    "Hinge": {
        "reuse": "Reuse intact hinges for a compatible repair.",
        "handling": "Watch for sharp edges and keep the paired hinges together.",
        "recycling": "Separate from mixed waste and take it with laptop components to a recycler.",
        "safety": "Avoid forcing a stuck hinge or leaving small metal parts where they can injure someone.",
    },
    "Keyboard": {
        "reuse": "Reuse a working keyboard as a replacement part.",
        "handling": "Disconnect its ribbon cable by the connector tab, not by pulling the cable.",
        "recycling": "Use an electronics take-back program when it is no longer serviceable.",
        "safety": "Do not burn or shred the plastic and electronic assembly.",
    },
    "Motherboard": {
        "reuse": "A tested board may be reused for a compatible repair or parts recovery.",
        "handling": "Protect the board from static discharge and avoid bending it.",
        "recycling": "Give it to a certified electronics recycler that recovers circuit-board metals.",
        "safety": "Remove batteries only when safe; do not burn boards or use informal acid recovery.",
    },
    "DCCable": {
        "reuse": "Reuse an intact cable with its matching voltage and connector.",
        "handling": "Inspect insulation and strain relief before reconnecting.",
        "recycling": "Send damaged cables to an e-waste or cable-recycling collection point.",
        "safety": "Do not use cables with exposed conductors or attempt to repair a mains-powered adapter lead.",
    },
    "PowerSwitch": {
        "reuse": "Reuse a working switch board in a compatible repair.",
        "handling": "Keep its small connector and cable protected.",
        "recycling": "Recycle the board with electronic components rather than household refuse.",
        "safety": "Disconnect all power sources before handling it.",
    },
    "RAM": {
        "reuse": "Test and reuse compatible memory modules before recycling.",
        "handling": "Hold the module by its edges and protect the contacts from static.",
        "recycling": "Take failed modules to an electronics recycler for circuit-board recovery.",
        "safety": "Avoid scraping gold contacts or mixing small parts into general waste.",
    },
    "ScrewKit": {
        "reuse": "Sort and reuse undamaged screws for compatible repairs.",
        "handling": "Keep small fasteners in a closed container.",
        "recycling": "Separate clean metal fasteners for local metal recycling where accepted.",
        "safety": "Do not leave loose screws where they can be swallowed or cause puncture injuries.",
    },
    "USBPort": {
        "reuse": "Reuse the port only as part of a tested compatible board or repair.",
        "handling": "Avoid bending the connector shell or pins.",
        "recycling": "Recycle it with its circuit board through an electronics collection program.",
        "safety": "Do not burn or chemically strip the connector.",
    },
    "WifiCard": {
        "reuse": "Check compatibility and reuse a functioning wireless card.",
        "handling": "Disconnect antenna leads by their plugs and protect the card from static.",
        "recycling": "Recycle a failed card as electronic equipment.",
        "safety": "Keep tiny antenna connectors and screws secured during removal.",
    },
    "Speaker": {
        "reuse": "Reuse a working speaker pair in a compatible repair.",
        "handling": "Avoid tearing the cone or pinching its fine wires.",
        "recycling": "Take failed speakers to an e-waste recycler for material separation.",
        "safety": "Do not burn the speaker or cut its magnet assembly without suitable controls.",
    },
    "CMOSBattery": {
        "reuse": "Replace only with the specified compatible cell or assembly.",
        "handling": "Keep the cell terminals insulated and do not recharge a non-rechargeable coin cell.",
        "recycling": "Use a household battery or e-waste collection point.",
        "safety": "Coin cells are a severe ingestion hazard; keep them away from children and pets.",
    },
    "HardDiskDrive": {
        "reuse": "Test and reuse the drive only after securely erasing data.",
        "handling": "Keep it dry and avoid impact to the platters and read head.",
        "recycling": "Use a certified recycler or secure data-destruction service for failed drives.",
        "safety": "Treat stored information as sensitive; do not donate or discard it before data sanitization.",
    },
    "WebCam": {
        "reuse": "Reuse a functioning camera module in a compatible device.",
        "handling": "Protect the lens and disconnect its cable carefully.",
        "recycling": "Send a failed module to an electronics recycler.",
        "safety": "Do not dismantle the lens assembly with improvised tools.",
    },
    "LCDScreen": {
        "reuse": "Reuse an intact panel after confirming connector and panel compatibility.",
        "handling": "Carry it upright with both hands and avoid twisting or pressure.",
        "recycling": "Use a specialist display or e-waste recycler, especially for older panels.",
        "safety": "Do not break the panel; older backlights may contain hazardous materials.",
    },
    "Bezel": {
        "reuse": "Reuse an intact bezel for a compatible screen repair.",
        "handling": "Release clips gradually to avoid sharp broken plastic.",
        "recycling": "Sort clean plastic according to local rules; otherwise use e-waste collection.",
        "safety": "Do not burn plastic parts.",
    },
    "HeatSink": {
        "reuse": "Reuse a clean, undamaged heat sink in a compatible repair.",
        "handling": "Remove attached thermal material without spreading it.",
        "recycling": "Separate recyclable metal where local programs allow, or use e-waste collection.",
        "safety": "Edges and fins can be sharp; avoid inhaling dust from old thermal compounds.",
    },
    "SSD": {
        "reuse": "Reuse a working SSD only after securely erasing stored data.",
        "handling": "Protect its connector from static and physical damage.",
        "recycling": "Use an electronics recycler or secure destruction service for failed drives.",
        "safety": "Do not discard the device before sanitizing sensitive data.",
    },
    "CPUFan": {
        "reuse": "Reuse a quiet, working fan with the correct connector and dimensions.",
        "handling": "Remove dust gently and keep the cable and blades intact.",
        "recycling": "Recycle a failed fan with electronic components.",
        "safety": "Disconnect power before cleaning; do not spin the fan with compressed air at high speed.",
    },
    "TouchPad": {
        "reuse": "Reuse a working touchpad with its compatible ribbon cable.",
        "handling": "Avoid creasing the ribbon cable or scratching the touch surface.",
        "recycling": "Send a failed touchpad to an e-waste recycler.",
        "safety": "Do not burn or shred the assembly.",
    },
    "Processor": {
        "reuse": "Reuse a tested processor only in a compatible socket and board.",
        "handling": "Hold it by its edges and protect pins or contact pads from bending.",
        "recycling": "Recycle unusable processors through a certified electronics recycler.",
        "safety": "Avoid informal chemical extraction or burning of electronic parts.",
    },
    "RAMCover": {
        "reuse": "Reuse an intact cover during a compatible repair.",
        "handling": "Keep its small screws and clips together.",
        "recycling": "Recycle clean metal or plastic by material where accepted; otherwise use e-waste collection.",
        "safety": "Check for sharp edges before handling.",
    },
    "BasePanel": {
        "reuse": "Reuse an undamaged base panel for a compatible chassis repair.",
        "handling": "Remove attached batteries and boards only if this can be done safely.",
        "recycling": "Sort clean plastics and metals locally or take the panel to an e-waste facility.",
        "safety": "Do not burn plastic; check for sharp broken edges.",
    },
    "TopPanel": {
        "reuse": "Reuse an intact top panel for a compatible chassis repair.",
        "handling": "Remove the display and cables only with appropriate tools and care.",
        "recycling": "Use a display/e-waste recycler if it includes a screen or electronic parts.",
        "safety": "Do not break or bend an attached display panel.",
    },
    "LVDSCable": {
        "reuse": "Reuse an undamaged display cable only with the matching panel and board.",
        "handling": "Release the connector lock and avoid pulling or sharply folding the cable.",
        "recycling": "Recycle damaged cables with electronic components.",
        "safety": "Keep the cable away from sharp edges and do not use it if insulation is damaged.",
    },
}

DISPOSITIONS = {
    "Battery": "Potentially hazardous; send to a battery take-back or specialist recycler.",
    "CMOSBattery": "Potentially hazardous coin cell; use a battery collection point.",
    "LCDScreen": "Potentially hazardous if it contains an older backlight; use a specialist display recycler.",
    "HardDiskDrive": "Reusable after secure data erasure; otherwise use certified e-waste recycling.",
    "SSD": "Reusable after secure data erasure; otherwise use certified e-waste recycling.",
}


def get_recommendation(component: str) -> Recommendation | None:
    details = RECOMMENDATIONS.get(component)
    if details is None:
        return None
    return {
        "disposition": DISPOSITIONS.get(
            component, "Reusable if functional; otherwise recycle through e-waste collection."
        ),
        **details,
    }
