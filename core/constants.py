from enum import Enum
import re

VERSION = "1.3.1"

SIGNATURE = f"Velocity X v{VERSION}"

TITLE = r"""
 _    __      __          _ _         __  __
| |  / /___  / /___  ____(_) |_ _   _ \ \/ /
| | / / __ \/ / __ \/ ___/ / __| | | | \  / 
| |/ / /_/ / / /_/ / /__/ / |_| |_| | /  \ 
|___/\____/_/\____/\___/_/\__|\__, |/_/\_\
                              |___/       
"""

FAILED_IMAGE_URL = "https://i.ibb.co/Cs3Wvgb/7189017466763a9ed8874824aceba073.png"
RAW_CODE_URL = "https://raw.githubusercontent.com/JustAScript/AutoSeller/refs/heads/main/main.py"
URL_REPOSITORY = "https://github.com/JustAScriptPanda/AutoSeller"

# Webhook URL validation pattern
WEBHOOK_PATTERN = re.compile(
    r"https?://discord.com/api/webhooks/\d+/\w+[-_]\w+"
)

# Color code pattern for ANSI escape sequences (used in Display class)
COLOR_CODE_PATTERN = re.compile(r"\033\[[0-9;]*m")

ITEM_TYPES = {
    8: "Hat",
    41: "HairAccessory",
    42: "FaceAccessory",
    43: "NeckAccessory",
    44: "ShoulderAccessory",
    45: "FrontAccessory",
    46: "BackAccessory",
    47: "WaistAccessory",
    64: "TShirtAccessory",
    65: "ShirtAccessory",
    66: "PantsAccessory",
    67: "JacketAccessory",
    68: "SweaterAccessory",
    69: "ShortsAccessory",
    72: "DressSkirtAccessory",
}

PRESENCE_BOT_ID = 1399802221142605836

