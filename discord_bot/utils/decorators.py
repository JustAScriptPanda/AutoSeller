from traceback import format_exc
import functools
import discord
from typing import List, Callable, Optional
from discord_bot.visuals.embeds import exception_embed

__all__ = ("users_blacklist", "base_command")

def users_blacklist(user_ids: List[int],
                    ignore_empty: Optional[bool] = True,
                    message: Optional[str] = None) -> Callable:
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(ctx: discord.Message, *args, **kwargs):
            if user_ids and str(ctx.author.id) in [str(uid) for uid in user_ids]:
                if message:
                    await ctx.reply(message)
                return
            await func(ctx, *args, **kwargs)
        return wrapper
    return decorator

def base_command(func: Callable):
    @functools.wraps(func)
    async def wrapper(ctx: discord.Message, *args, **kwargs):
        try:
            if hasattr(ctx, "response"):
                await ctx.response.defer()
            else:
                await ctx.defer()
            await func(ctx, *args, **kwargs)
        except Exception:
            await ctx.reply(embed=exception_embed(format_exc()))
    return wrapper
