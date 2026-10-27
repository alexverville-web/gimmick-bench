"""Mac model identifiers -> marketing name, release year and RAM upgradeability.

macOS does not report a model's release year directly. This table covers
the Macs a motion design studio is likely to own (2017 onward). Unknown
identifiers fall back to the name macOS caches for "About This Mac", and are
otherwise reported as unknown rather than guessed.

ram_upgradeable: True only where RAM sits in user-accessible slots.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# identifier: (name, year, ram_upgradeable)
MODELS: Dict[str, Tuple[str, int, bool]] = {
    # Intel
    "iMac18,1": ("iMac 21.5-inch", 2017, False),
    "iMac18,2": ("iMac 21.5-inch 4K", 2017, False),
    "iMac18,3": ("iMac 27-inch 5K", 2017, True),
    "iMacPro1,1": ("iMac Pro", 2017, False),
    "iMac19,1": ("iMac 27-inch 5K", 2019, True),
    "iMac19,2": ("iMac 21.5-inch 4K", 2019, False),
    "iMac20,1": ("iMac 27-inch 5K", 2020, True),
    "iMac20,2": ("iMac 27-inch 5K", 2020, True),
    "Macmini8,1": ("Mac mini", 2018, True),
    "MacPro6,1": ("Mac Pro", 2013, True),
    "MacPro7,1": ("Mac Pro", 2019, True),
    "MacBookPro14,3": ("MacBook Pro 15-inch", 2017, False),
    "MacBookPro15,1": ("MacBook Pro 15-inch", 2018, False),
    "MacBookPro15,2": ("MacBook Pro 13-inch", 2018, False),
    "MacBookPro15,3": ("MacBook Pro 15-inch", 2019, False),
    "MacBookPro16,1": ("MacBook Pro 16-inch", 2019, False),
    "MacBookPro16,2": ("MacBook Pro 13-inch", 2020, False),
    "MacBookPro16,3": ("MacBook Pro 13-inch", 2020, False),
    "MacBookPro16,4": ("MacBook Pro 16-inch", 2019, False),
    # Apple Silicon M1
    "MacBookAir10,1": ("MacBook Air M1", 2020, False),
    "MacBookPro17,1": ("MacBook Pro 13-inch M1", 2020, False),
    "Macmini9,1": ("Mac mini M1", 2020, False),
    "iMac21,1": ("iMac 24-inch M1", 2021, False),
    "iMac21,2": ("iMac 24-inch M1", 2021, False),
    "MacBookPro18,1": ("MacBook Pro 16-inch M1 Pro", 2021, False),
    "MacBookPro18,2": ("MacBook Pro 16-inch M1 Max", 2021, False),
    "MacBookPro18,3": ("MacBook Pro 14-inch M1 Pro", 2021, False),
    "MacBookPro18,4": ("MacBook Pro 14-inch M1 Max", 2021, False),
    "Mac13,1": ("Mac Studio M1 Max", 2022, False),
    "Mac13,2": ("Mac Studio M1 Ultra", 2022, False),
    # M2
    "Mac14,2": ("MacBook Air 13-inch M2", 2022, False),
    "Mac14,7": ("MacBook Pro 13-inch M2", 2022, False),
    "Mac14,3": ("Mac mini M2", 2023, False),
    "Mac14,12": ("Mac mini M2 Pro", 2023, False),
    "Mac14,5": ("MacBook Pro 14-inch M2 Max", 2023, False),
    "Mac14,9": ("MacBook Pro 14-inch M2 Pro", 2023, False),
    "Mac14,6": ("MacBook Pro 16-inch M2 Max", 2023, False),
    "Mac14,10": ("MacBook Pro 16-inch M2 Pro", 2023, False),
    "Mac14,15": ("MacBook Air 15-inch M2", 2023, False),
    "Mac14,13": ("Mac Studio M2 Max", 2023, False),
    "Mac14,14": ("Mac Studio M2 Ultra", 2023, False),
    "Mac14,8": ("Mac Pro M2 Ultra", 2023, False),
    # M3
    "Mac15,3": ("MacBook Pro 14-inch M3", 2023, False),
    "Mac15,4": ("iMac 24-inch M3", 2023, False),
    "Mac15,5": ("iMac 24-inch M3", 2023, False),
    "Mac15,6": ("MacBook Pro 14-inch M3 Pro", 2023, False),
    "Mac15,8": ("MacBook Pro 14-inch M3 Max", 2023, False),
    "Mac15,10": ("MacBook Pro 14-inch M3 Max", 2023, False),
    "Mac15,7": ("MacBook Pro 16-inch M3 Pro", 2023, False),
    "Mac15,9": ("MacBook Pro 16-inch M3 Max", 2023, False),
    "Mac15,11": ("MacBook Pro 16-inch M3 Max", 2023, False),
    "Mac15,12": ("MacBook Air 13-inch M3", 2024, False),
    "Mac15,13": ("MacBook Air 15-inch M3", 2024, False),
    "Mac15,14": ("Mac Studio M3 Ultra", 2025, False),
    # M4
    "Mac16,1": ("MacBook Pro 14-inch M4", 2024, False),
    "Mac16,6": ("MacBook Pro 14-inch M4 Pro/Max", 2024, False),
    "Mac16,8": ("MacBook Pro 14-inch M4 Pro", 2024, False),
    "Mac16,5": ("MacBook Pro 16-inch M4 Pro/Max", 2024, False),
    "Mac16,7": ("MacBook Pro 16-inch M4 Pro", 2024, False),
    "Mac16,2": ("iMac 24-inch M4", 2024, False),
    "Mac16,3": ("iMac 24-inch M4", 2024, False),
    "Mac16,10": ("Mac mini M4", 2024, False),
    "Mac16,11": ("Mac mini M4 Pro", 2024, False),
    "Mac16,12": ("MacBook Air 13-inch M4", 2025, False),
    "Mac16,13": ("MacBook Air 15-inch M4", 2025, False),
    "Mac16,9": ("Mac Studio M4 Max", 2025, False),
}


def lookup(model_id: Optional[str]) -> Optional[Tuple[str, int, bool]]:
    if not model_id:
        return None
    return MODELS.get(model_id.strip())


def year_from_marketing_name(name: Optional[str]) -> Optional[int]:
    """Pull the year out of names like 'MacBook Pro (14-inch, 2023)'."""
    if not name:
        return None
    import re
    m = re.search(r"\b(20\d\d)\b", name)
    return int(m.group(1)) if m else None
