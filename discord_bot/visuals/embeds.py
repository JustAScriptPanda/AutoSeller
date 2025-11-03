from discord import Embed
from datetime import datetime
from typing import Optional

PRIMARY_COLOR = 0x25D366
ERROR_COLOR = 0xFF4B4B
LOADING_GIF = "https://cdn.discordapp.com/emojis/1241417265778262086.gif?size=48&quality=lossless"

def exception_embed(exc: str) -> Embed:
    return Embed(
        title="⚠️ An Error Occurred",
        description=f"```py\n{exc.strip()}```",
        color=ERROR_COLOR,
        timestamp=datetime.now()
    )

def custom_embed(title: str, description: str, color: int = PRIMARY_COLOR) -> Embed:
    return Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now()
    )

def loading_embed(title: str, description: Optional[str] = "Please wait...") -> Embed:
    embed = Embed(
        description=description,
        color=PRIMARY_COLOR,
        timestamp=datetime.now()
    )
    embed.set_author(name=title, icon_url=LOADING_GIF)
    return embed
