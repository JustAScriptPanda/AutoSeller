from __future__ import annotations

import sys
import os
import aiohttp
import json

__import__("warnings").filterwarnings("ignore")

try:
    import discord
    import aioconsole
    import asyncio
    from random import random
    from rgbprint import Color
    from datetime import datetime
    from traceback import format_exc
    from pypresence import AioPresence, DiscordNotFound

    from typing import List, Optional, Any, Union, AsyncGenerator, Iterable, TYPE_CHECKING
    from discord.errors import LoginFailure
    from asyncio import Task
    if TYPE_CHECKING:
        from .discord_bot.visuals.view import ControlPanel

    from core.instances import *
    from core.main_tools import *
    from core.clients import *
    from core.visuals import *
    from core.detection import *
    from core.utils import *
    from core.constants import VERSION, RAW_CODE_URL, ITEM_TYPES, PRESENCE_BOT_ID, URL_REPOSITORY
    from discord_bot import start as discord_bot_start

    os.system("cls" if os.name == "nt" else "clear")
except ModuleNotFoundError:
    import traceback
    print(traceback.format_exc())
    install = input("Uninstalled modules found, do you want to install them? Y/n: ").lower() == "y"

    if install:
        print("Installing modules now...")
        print("hi")
        os.system("pip uninstall pycord")
        os.system("pip install aiohttp rgbprint discord.py aioconsole pypresence")
        print("Successfully installed required modules.")
    else:
        print("Aborting installing modules.")

    input("Press \"enter\" to exit...")
    sys.exit(1)

__all__ = ("AutoSeller",)


class AutoSeller(ConfigLoader):
    __slots__ = ("config", "_items", "auth", "buy_checker", "blacklist",
                 "seen", "not_resable", "current_index", "done",
                 "total_sold", "selling", "loaded_time", "control_panel", "rich_presence")

    def __init__(self,
                 config: dict,
                 blacklist: FileSync,
                 seen: FileSync,
                 not_resable: FileSync) -> None:
        super().__init__(config)
        
        self.config = config

        self._items = dict()
        self.auth = Auth(config.get("Cookie", "").strip())
        self.buy_checker = BuyChecker(self)

        self.blacklist = blacklist
        self.seen = seen
        self.not_resable = not_resable

        self.rich_presence = None
        if self.presence_enabled:
            self.rich_presence = AioPresence(PRESENCE_BOT_ID)

        self.current_index = 0
        self.done = False
        self.total_sold = 0
        self.selling = WithBool()
        self.loaded_time: datetime = None
        self.control_panel: ControlPanel = None

    @property
    def items(self) -> List[Item]:
        return list(self._items.values())

    @property
    def current(self) -> Optional[Item]:
        if not self.items or self.current_index >= len(self.items):
            return None
        return self.items[self.current_index]

    def get_item(self, _id: int, default: Optional[Any] = None) -> Union[Item, Any]:
        return self._items.get(_id, default)

    def add_item(self, item: Item) -> Item:
        self._items.update({item.id: item})
        return item

    def remove_item(self, _id: int) -> Optional[Item]:
        return self._items.pop(_id, None)

    def next_item(self, *, step_index: int = 1) -> None:
        if not self.items:
            self.done = True
            return
            
        self.current_index = (self.current_index + step_index) % len(self.items)

        if self.presence_enabled and self.rich_presence and self.current:
            asyncio.create_task(self.update_presence())

        if self.current_index == 0:
            self.done = True

        self.fetch_item_info(step_index=step_index)

    async def update_presence(self) -> None:
        if not self.rich_presence or not self.current:
            return
            
        easter_egg = random() < 0.3

        try:
            await self.rich_presence.update(
                state=f"{self.current_index + 1} out of {len(self.items)}",
                details=f"Selling {self.current.name} limited",
                large_image=self.current.thumbnail if not easter_egg else "https://cdn.discordapp.com/avatars/1284536257958903808/fa4fba77caa6cc68f2972e2ea33e67a5.png?size=4096",
                large_text=f"{self.current.name} limited" if not easter_egg else "Pisun easter egg (3% chance)",
                small_image="https://cdn.discordapp.com/app-assets/1005469189907173486/1025422070600978553.png?size=160",
                small_text="Roblox",
                buttons=[{"url": self.current.link, "label": "Selling Item"},
                         {"url": URL_REPOSITORY, "label": "Use Tool Yourself"}],
                start=int(self.loaded_time.timestamp()) if self.loaded_time else None
            )
        except Exception as e:
            Display.error(f"Failed to update rich presence: {str(e)}")

    async def filter_non_resable(self):
        if not self.items:
            return None
            
        if (self.current_index + 2) % 30 or not self.current_index:
            return None

        try:
            start_idx = self.current_index
            end_idx = min(start_idx + 30, len(self.items))
            items_to_check = self.items[start_idx:end_idx]
            
            if not items_to_check:
                return None
                
            item_ids = [item.item_id for item in items_to_check]
            
            async with self.auth.post(
                "https://apis.roblox.com/marketplace-items/v1/items/details",
                json={"itemIds": item_ids}
            ) as response:
                if response.status != 200:
                    return None
                    
                response_data = await response.json()
                
                if response_data is None:
                    return
                    
                if isinstance(response_data, dict):
                    if "data" in response_data:
                        response_data = response_data["data"]
                    else:
                        return
                
                if not isinstance(response_data, list):
                    return
                
                for item_details in response_data:
                    if isinstance(item_details, dict):
                        item_id = item_details.get("itemTargetId")
                        resale_restriction = item_details.get("resaleRestriction")
                        
                        if resale_restriction == 1 and item_id:
                            try:
                                item_id_int = int(item_id)
                            except (ValueError, TypeError):
                                continue
                                
                            self.not_resable.add(item_id_int)
                            if item_id_int in self._items:
                                self.remove_item(item_id_int)
                        
        except Exception as e:
            Display.error(f"Error filtering non-resable items: {str(e)}")

    def fetch_item_info(self, *, step_index: int = 1) -> Optional[Iterable[Task]]:
        if not self.items:
            return None
            
        try:
            if self.current_index + step_index >= len(self.items):
                return None
                
            item = self.items[self.current_index + step_index]
        except IndexError:
            return None

        tasks = [
            asyncio.create_task(item.fetch_sales(save_sales=False)),
            asyncio.create_task(item.fetch_resales(save_resales=False))
        ]
        
        if self.current_index % 30 == 0 and len(self.items) > 0:
            tasks.append(asyncio.create_task(self.filter_non_resable()))
            
        return tasks

    def sort_items(self, _type: str) -> None:
        if not self._items:
            return
        self._items = dict(sorted(self._items.items(), key=lambda x: getattr(x[1], _type, "")))

    async def start(self):
        await asyncio.gather(
            self.auth.fetch_csrf_token(),
            self.handle_exceptions()
        )

        Display.info("Checking cookie to be valid")
        if await self.auth.fetch_user_info() is None:
            return Display.exception("Invalid cookie provided")

        Display.info("Checking premium owning")
        if not await self.auth.fetch_premium():
            return Display.exception("You dont have premium to sell limiteds")

        await self._load_items()
        if self.items:
            self.sort_items("name")

        if self.presence_enabled and self.rich_presence:
            try:
                await self.rich_presence.connect()
                await self.update_presence()
            except DiscordNotFound:
                Display.warning("Could not find Discord running to show presence")

        try:
            async with self:
                tasks = []
                if self.discord_bot:
                    tasks.append(discord_bot_start(self))
                if self.buy_webhook:
                    tasks.append(self.buy_checker.start())
                tasks.append(self.auth.csrf_token_updater())
                tasks.append(self.start_selling())
                
                await asyncio.gather(*filter(None, tasks))
        except LoginFailure:
            return Display.exception("Invalid discord token provided")
        except Exception as e:
            return Display.exception(f"Error occurred:\n\n{str(e)}")

    async def start_selling(self):
        for i in range(min(2, len(self.items))):
            for task in self.fetch_item_info(step_index=i) or []:
                try:
                    await task
                except Exception as e:
                    Display.error(f"Error fetching item info: {str(e)}")

        if not self.items:
            Display.error("No items to sell")
            return

        if self.auto_sell: 
            await self._auto_sell_items()
        else: 
            await self._manual_selling()

        Tools.clear_console()
        await Display.custom(
            f"Sold [g{self.total_sold}x] items",
            "done", Color(207, 222, 0))

        clear_items = await Display.input(f"Do you want to reset your selling progress? (Y/n): ")

        if clear_items.lower() == "y":
            self.seen.clear()
            Display.success("Cleared your limiteds selling progress")
            Tools.exit_program()

    async def sell_item(self):
        if not self.current:
            Display.error("No current item to sell")
            self.next_item()
            return
            
        max_retries = 5
        retry_delay = 2
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                await Display.custom(
                    f"Selling [g{len(self.current.collectibles)}x] of [g{self.current.name}] items...",
                    "selling", Color(255, 153, 0))

                sold_amount = await self.current.sell_collectibles(
                    skip_on_sale=self.skip_on_sale,
                    skip_if_cheapest=self.skip_if_cheapest,
                    verbose=True,
                    retries=3
                )

                if sold_amount is not None:
                    self.total_sold += sold_amount

                    if self.sale_webhook and sold_amount > 0:
                        asyncio.create_task(self.send_sale_webhook(self.current, sold_amount))

                if self.save_progress:
                    self.seen.add(self.current.id)

                self.next_item()
                return
                
            except Exception as e:
                error_msg = str(e)
                
                if "412" in error_msg or "Precondition Failed" in error_msg:
                    retry_count += 1
                    if retry_count < max_retries:
                        Display.warning(f"Precondition Failed (412). Retrying in {retry_delay} seconds... (Attempt {retry_count}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        try:
                            await self.current.fetch_sales(save_sales=False)
                            await self.current.fetch_resales(save_resales=False)
                        except:
                            pass
                    else:
                        Display.error(f"Failed to sell after {max_retries} attempts due to 412 errors. Skipping item.")
                        if self.save_progress:
                            self.seen.add(self.current.id)
                        self.next_item()
                        break
                else:
                    Display.error(f"Error selling item: {error_msg}")
                    await asyncio.sleep(2)
                    if self.save_progress:
                        self.seen.add(self.current.id)
                    self.next_item()
                    break

    async def _auto_sell_items(self):
        while not self.done and self.items:
            await self.sell_item()
            await asyncio.sleep(1.5)

    async def _manual_selling(self):
        while not self.done and self.items:
            try:
                await self.update_console()
                choice = (await aioconsole.ainput()).strip()

                match choice:
                    case "1":
                        if self.selling:
                            Display.error("This item is already being sold")
                            await asyncio.sleep(0.7)
                            continue

                        with self.selling:
                            await self.sell_item()

                            if self.control_panel is not None:
                                asyncio.create_task(self.control_panel.update_message(self.control_panel.make_embed()))
                    case "2":
                        if not self.current:
                            Display.error("No current item selected")
                            continue
                            
                        new_price = await Display.input(f"Enter the new price you want to sell: ")

                        if not new_price.isdigit():
                            Display.error("Invalid price amount was provided")
                            await asyncio.sleep(0.7)
                            continue
                        elif int(new_price) < 0:
                            Display.error("Price can not be lower than 0")
                            await asyncio.sleep(0.7)
                            continue

                        self.current.price_to_sell = int(new_price)

                        Display.success(f"Successfully set a new price to sell! ([g${self.current.price_to_sell}])")
                    case "3":
                        if not self.current:
                            Display.error("No current item to blacklist")
                            continue
                            
                        self.blacklist.add(self.current.id)
                        self.next_item()

                        Display.success(f"Successfully added [g{self.current.name} ({self.current.id})] into a blacklist!")
                    case "4":
                        if not self.current:
                            Display.error("No current item to skip")
                            continue
                            
                        if self.save_progress:
                            self.seen.add(self.current.id)

                        self.next_item()
                        Display.skipping(
                            f"Skipped [g{len(self.current.collectibles)}x] collectibles")
                    case _:
                        continue

                await asyncio.sleep(0.7)
            except Exception as e:
                Display.error(f"Error in manual selling: {str(e)}")
                await asyncio.sleep(1)

    async def __fetch_items(self) -> AsyncGenerator:
        Display.info("Loading your inventory")
        user_items = await AssetsLoader(get_user_inventory, ITEM_TYPES.keys()).load(self.auth)
        if not user_items:
            Display.exception("You dont have any limited UGC items")
            return

        item_ids = [str(asset["assetId"]) for asset in user_items]

        Display.info("Loading items thumbnails")
        items_thumbnails = await AssetsLoader(get_assets_thumbnails, item_ids, 100).load(self.auth)

        Display.info(f"Found {len(user_items)} items. Checking them...")
        items_details = await AssetsLoader(get_items_details, item_ids, 120).load(self.auth)

        batch_size = 100
        for i in range(0, len(user_items), batch_size):
            batch_end = min(i + batch_size, len(user_items))
            batch_items = user_items[i:batch_end]
            batch_details = items_details[i:batch_end] if items_details else []
            batch_thumbnails = items_thumbnails[i:batch_end] if items_thumbnails else []
            
            batch_item_ids = [str(item["assetId"]) for item in batch_items]
            try:
                async with self.auth.post(
                    "https://apis.roblox.com/marketplace-items/v1/items/details",
                    json={"itemIds": batch_item_ids}
                ) as response:
                    if response.status == 200:
                        resale_data = await response.json()
                        if isinstance(resale_data, dict) and "data" in resale_data:
                            resale_data = resale_data["data"]
                        elif not isinstance(resale_data, list):
                            resale_data = []
                    else:
                        resale_data = []
            except Exception:
                resale_data = []
            
            resale_map = {}
            for rd in resale_data:
                if isinstance(rd, dict):
                    item_id = rd.get("itemTargetId")
                    restriction = rd.get("resaleRestriction")
                    if item_id:
                        resale_map[str(item_id)] = restriction
            
            for idx, item in enumerate(batch_items):
                item_id = str(item["assetId"])
                
                item_details = batch_details[idx] if idx < len(batch_details) else {}
                thumbnail = batch_thumbnails[idx] if idx < len(batch_thumbnails) else None
                
                if resale_map.get(item_id) == 1:
                    try:
                        self.not_resable.add(int(item_id))
                    except:
                        pass
                    continue
                    
                try:
                    ignored_items = list(self.seen | self.blacklist | self.not_resable)
                    if (int(item_id) in ignored_items or 
                        item_details.get("creatorTargetId") in self.creators_blacklist):
                        continue
                except:
                    continue
                    
                yield item, item_details, thumbnail

    async def _load_items(self) -> None:
        if self.loaded_time is not None:
            return Display.exception("You have already loaded items")

        Display.info("Getting current limiteds cap")
        items_cap = await get_current_cap(self.auth)

        async for item, item_details, thumbnail in self.__fetch_items():
            if not item_details:
                continue
                
            try:
                item_id = int(item["assetId"])
            except:
                continue
            
            item_obj = self.get_item(item_id)
            
            if item_obj is None:
                if not items_cap:
                    continue
                    
                asset_type = item_details.get("assetType")
                if not asset_type:
                    continue
                    
                item_type_key = ITEM_TYPES.get(asset_type)
                if not item_type_key:
                    continue
                    
                asset_cap_data = items_cap.get(item_type_key, {})
                price_floor = asset_cap_data.get("priceFloor", 0)
                
                lowest_resale_price = item_details.get("lowestResalePrice", 0)
                
                sell_price = define_sale_price(
                    self.under_cut_amount, 
                    self.under_cut_type,
                    price_floor, 
                    lowest_resale_price
                )
                
                item_obj = Item(
                    item, item_details,
                    price_to_sell=sell_price,
                    thumbnail=thumbnail,
                    auth=self.auth
                )
                self.add_item(item_obj)
            
            try:
                item_obj.add_collectible(
                    serial=item.get("serialNumber", 0),
                    item_id=item.get("collectibleItemId"),
                    instance_id=item.get("collectibleItemInstanceId")
                )
            except:
                pass

        if not self.items:
            Display.error(f"You dont have any limiteds that are not in[g blacklist/] directory")
            clear_items = await Display.input(f"Do you want to reset your selling progress? (Y/n): ")

            if clear_items.lower() == "y":
                self.seen.clear()
                Display.success("Cleared your limiteds selling progress")
                Tools.exit_program()
            else:
                return

        if self.keep_serials or self.keep_copy:
            items_to_remove = []
            for item in self.items:
                if len(item.collectibles) <= self.keep_copy:
                    items_to_remove.append(item.id)
                    continue

                for col in item.collectibles:
                    if col.serial > self.keep_serials:
                        col.skip_on_sale = True
            
            for item_id in items_to_remove:
                self.remove_item(item_id)

        if not self.items:
            not_met = []

            if self.keep_copy: not_met.append(f"{self.keep_copy} copies or higher")
            if self.keep_serials: not_met.append(f"{self.keep_serials} serial or higher")

            list_requirements = ", ".join(not_met)
            return Display.exception(f"You dont have any limiteds with {list_requirements}")

        self.loaded_time = datetime.now()
        Display.success(f"Successfully loaded {len(self.items)} items")

    async def update_console(self) -> None:
        Tools.clear_console()
        Display.main()

        if not self.current:
            Display.error("No items available")
            return

        item = self.current

        data = {
            "Info": {
                "Discord Bot": define_status(self.discord_bot),
                "Save Items": define_status(self.save_progress),
                "Under Cut": f"-{self.under_cut_amount}{'%' if self.under_cut_type == 'percent' else ''}",
                "Total Blacklist": f"{len(self.blacklist)}"
            },
            "Current Item": {
                "Name": item.name,
                "Creator": item.creator_name,
                "Price": f"{item.price:,}",
                "Quality": f"{item.quantity:,}",
                "Lowest Price": item.define_lowest_resale_price(),
                "Price to Sell": f"{item.price_to_sell:,}",
                "RAP": item.define_recent_average_price(),
                "Latest Sale": item.define_latest_sale()
            }
        }

        Display.sections(data)
        await Display.custom("[1] - Sell | [2] - Set Price | [3] - Blacklist | [4] - Skip\n> ",
                             "input", BaseColors.gray, end="")
    
    async def send_sale_webhook(self, item: Item, sold_amount: int) -> None:
        if not item:
            return
            
        try:
            embed = discord.Embed(
                color=2469096,
                timestamp=datetime.now(),
                description=f"**Item name: **`{item.name}`\n"
                            f"**Sold amount: **`{sold_amount}`\n"
                            f"**Sold for: **`{item.price_to_sell}`",
                title="A New Item Went on Sale",
                url=item.link
            )
            embed.set_footer(text="Were sold at")
            
            data = {
                "content": self.user_to_ping,
                "embeds": [embed.to_dict()]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.sale_webhook_url, json=data, timeout=30) as response:
                    if response.status == 429:
                        await asyncio.sleep(30)
                        await self.send_sale_webhook(item, sold_amount)
        except Exception as e:
            Display.error(f"Failed to send sale webhook: {str(e)}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        tasks = []
        tasks.append(self.auth.close_session())
        if self.control_panel and self.control_panel.message:
            tasks.append(self.control_panel.message.delete())
        
        if self.rich_presence:
            tasks.append(self.rich_presence.close())

        await asyncio.gather(*filter(None, tasks), return_exceptions=True)


async def main() -> None:
    Display.info("Setting up everything...")

    Display.info("Checking for updates")
    if await check_for_update(RAW_CODE_URL, VERSION):
        await Display.custom(
            "Your code is outdated. Please update it from github",
            "new", Color(163, 133, 0), exit_after=True)

    Display.info("Loading config")
    config = load_file("config.json")
    if not config:
        Display.exception("Failed to load config.json")
        return

    Display.info("Loading data assets")
    try:
        blacklist = FileSync("blacklist/blacklist.json")
        seen = FileSync("blacklist/seen.json")
        not_resable = FileSync("blacklist/not_resable.json")
    except Exception as e:
        Display.exception(f"Failed to load data files: {str(e)}")
        return

    auto_seller = AutoSeller(config, blacklist, seen, not_resable)

    try:
        await auto_seller.start()
    except Exception as e:
        return Display.exception(f"Error occurred:\n\n{str(e)}")


if __name__ == "__main__":
    asyncio.run(main())
