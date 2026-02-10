from __future__ import annotations

import sys
import os
import hmac
import base64
import hashlib
import time
import json
import logging
from math import floor

__import__("warnings").filterwarnings("ignore")

try:
    import discord
    import aioconsole
    import asyncio
    import aiohttp
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
        os.system("pip install aiohttp rgbprint discord.py aioconsole pypresence rich")
        print("Successfully installed required modules.")
    else:
        print("Aborting installing modules.")

    input("Press \"enter\" to exit...")
    sys.exit(1)

__all__ = ("AutoSeller", "TwoStepVerification")

# ==================== NEW: Two-Step Verification Class ====================
class TwoStepVerification:
    @staticmethod
    def generate_totp(secret: str) -> str:
        try:
            missing_padding = len(secret) % 8
            if missing_padding:
                secret += '=' * (8 - missing_padding)

            key = base64.b32decode(secret, casefold=True)
            counter = int(time.time() // 30)
            counter_bytes = counter.to_bytes(8, byteorder="big")
            hmac_hash = hmac.new(key, counter_bytes, hashlib.sha1).digest()
            
            offset = hmac_hash[-1] & 0x0F
            code = (
                (hmac_hash[offset] & 0x7F) << 24 |
                (hmac_hash[offset + 1] & 0xFF) << 16 |
                (hmac_hash[offset + 2] & 0xFF) << 8 |
                (hmac_hash[offset + 3] & 0xFF)
            )
            return str(code % 1000000).zfill(6)
        except Exception as e:
            print(f"TOTP Error: {e}")
            return None

    @staticmethod
    async def handle_challenge(session, headers, user_id, challenge_id, challenge_metadata, challenge_type, totp_secret):
        try:
            if challenge_type not in ["twostepverification", "forceauthenticator"]:
                print(f"Unsupported challenge type: {challenge_type}")
                return None

            metadata = json.loads(base64.b64decode(challenge_metadata).decode("utf-8"))
            totp_code = TwoStepVerification.generate_totp(totp_secret)
            if not totp_code:
                return None

            print(f"Handling {challenge_type} challenge with TOTP: {totp_code}")

            if challenge_type == "forceauthenticator":
                async with session.post(
                    "https://apis.roblox.com/reauthentication-service/v1/token/redeem",
                    json={"challengeId": challenge_id, "challengeMetadata": base64.b64decode(challenge_metadata).decode("utf-8"), "challengeType": challenge_type},
                    headers=headers
                ) as response:
                    if response.status != 200:
                        async with session.post(
                            f"https://twostepverification.roblox.com/v1/users/{user_id}/challenges/authenticator/send-code",
                            json={"challengeId": challenge_id, "actionType": "Generic"},
                            headers=headers
                        ) as send_response:
                            if send_response.status != 200:
                                print(f"Failed to send 2FA code: {await send_response.text()}")
                                return None
                            send_data = await send_response.json()
                            new_challenge_id = send_data.get("challengeId")
                            if not new_challenge_id:
                                return None
                            verify_payload = {"challengeId": new_challenge_id, "actionType": "Generic", "code": totp_code}
                    else:
                        redeem_data = await response.json()
                        verify_payload = {"challengeId": redeem_data.get("challengeId") or challenge_id, "actionType": "Generic", "code": totp_code}

                async with session.post(
                    f"https://twostepverification.roblox.com/v1/users/{user_id}/challenges/authenticator/verify",
                    json=verify_payload, headers=headers
                ) as response:
                    if response.status != 200:
                        print(f"2FA verify failed: {await response.text()}")
                        return None
                    verification_token = (await response.json()).get("verificationToken")
                    if not verification_token:
                        return None

                challenge_metadata_obj = {"verificationToken": verification_token, "rememberDevice": False, "challengeId": verify_payload['challengeId'], "actionType": "Generic"}
                
                async with session.post(
                    "https://apis.roblox.com/challenge/v1/continue",
                    json={"challengeId": challenge_id, "challengeMetadata": json.dumps(challenge_metadata_obj), "challengeType": "twostepverification"},
                    headers=headers
                ) as response:
                    if response.status != 200:
                        print(f"Challenge continue failed: {await response.text()}")
                        return None

                print("2FA challenge solved successfully")
                return {
                    "rblx-challenge-id": challenge_id,
                    "rblx-challenge-metadata": base64.b64encode(json.dumps(challenge_metadata_obj).replace(" ", "").encode()).decode(),
                    "rblx-challenge-type": "twostepverification"
                }
            else:
                second_challenge_id = metadata.get("challengeId")
                if not second_challenge_id:
                    return None

                async with session.post(
                    f"https://twostepverification.roblox.com/v1/users/{user_id}/challenges/authenticator/verify",
                    json={"challengeId": second_challenge_id, "actionType": metadata.get("actionType", "Generic"), "code": totp_code},
                    headers=headers
                ) as response:
                    if response.status != 200:
                        print(f"2FA verify failed: {await response.text()}")
                        return None
                    verification_token = (await response.json()).get("verificationToken")
                    if not verification_token:
                        return None

                challenge_metadata_continue = json.dumps({
                    "verificationToken": verification_token, "rememberDevice": False,
                    "challengeId": second_challenge_id, "actionType": metadata.get("actionType", "Generic")
                })

                async with session.post(
                    "https://apis.roblox.com/challenge/v1/continue",
                    json={"challengeId": challenge_id, "challengeMetadata": challenge_metadata_continue, "challengeType": challenge_type},
                    headers=headers
                ) as response:
                    if response.status != 200:
                        print(f"Challenge continue failed: {await response.text()}")
                        return None
                    
                    print("2FA challenge solved successfully")
                    return {
                        "rblx-challenge-id": challenge_id,
                        "rblx-challenge-metadata": base64.b64encode(challenge_metadata_continue.replace(" ", "").encode()).decode(),
                        "rblx-challenge-type": challenge_type
                    }
        except Exception as e:
            print(f"Error handling 2FA challenge: {e}")
            return None

# ==================== ENHANCED Auth Class (core/clients.py update) ====================
# Note: You'll need to update your existing Auth class to include these methods
# or create an enhanced version. Here's what to add to Auth class:

class EnhancedAuth(Auth):
    """Enhanced Auth with 2FA support and better request handling"""
    
    def __init__(self, cookie: str, totp_secret: str = None, max_threads: int = 5):
        super().__init__(cookie)
        self.totp_secret = totp_secret
        self.semaphore = asyncio.Semaphore(max_threads)
        self.price_floor_cache = {}
        
    async def request_with_retry(self, method: str, url: str, max_retries: int = 5, **kwargs):
        """Enhanced request with retry, 2FA handling, and rate limiting"""
        for attempt in range(max_retries):
            try:
                request_headers = kwargs.pop('headers', {}).copy()
                if self.csrf_token:
                    request_headers['x-csrf-token'] = self.csrf_token
                
                async with self.semaphore:
                    async with self.session.request(method, url, headers=request_headers, **kwargs) as response:
                        response_text = await response.text()
                        
                        if response.status == 200:
                            try:
                                return json.loads(response_text)
                            except json.JSONDecodeError:
                                return True

                        # Handle 2FA challenges
                        if response.status == 403 and "rblx-challenge-id" in response.headers:
                            if self.totp_secret:
                                challenge_headers = await TwoStepVerification.handle_challenge(
                                    self.session, request_headers, self.user_id,
                                    response.headers["rblx-challenge-id"],
                                    response.headers["rblx-challenge-metadata"],
                                    response.headers["rblx-challenge-type"],
                                    self.totp_secret
                                )
                                if challenge_headers:
                                    request_headers.update(challenge_headers)
                                    kwargs['headers'] = request_headers
                                    continue
                            else:
                                print("2FA challenge received but no TOTP secret configured")
                                return None

                        # Handle CSRF token refresh
                        if response.status == 403 and "x-csrf-token" in response.headers:
                            self.csrf_token = response.headers["x-csrf-token"]
                            print(f"CSRF token refreshed (attempt {attempt+1})")
                            kwargs['headers'] = request_headers
                            await asyncio.sleep(0.5)
                            continue

                        # Handle rate limiting
                        if response.status == 429:
                            wait_time = min(3 * (attempt + 1), 20)
                            print(f"Rate limited (429), waiting {wait_time}s (attempt {attempt+1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            kwargs['headers'] = request_headers
                            continue

                        print(f"API Error {response.status}: {response_text[:500]}")
                        return None
                        
            except asyncio.TimeoutError:
                print(f"Request timeout (attempt {attempt+1})")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"Request error: {e}")
                await asyncio.sleep(1)
        
        print(f"Max retries ({max_retries}) exceeded")
        return None
    
    async def get_price_floor(self, asset_type: int) -> int:
        """Get price floor with caching"""
        if asset_type in self.price_floor_cache:
            return self.price_floor_cache[asset_type]
        
        url = f"https://itemconfiguration.roblox.com/v1/items/price-floor?collectibleItemType=1&creationType=1&assetType={asset_type}"
        data = await self.request_with_retry("GET", url)
        
        if data and isinstance(data, dict):
            price_floor = data.get("priceFloor", 0)
        else:
            price_floor = 0
            
        self.price_floor_cache[asset_type] = price_floor
        return price_floor

# ==================== UPDATED AutoSeller Class ====================
class AutoSeller(ConfigLoader):
    __slots__ = ("config", "_items", "auth", "buy_checker", "blacklist",
                 "seen", "not_resable", "current_index", "done",
                 "total_sold", "selling", "loaded_time", "control_panel",
                 "price_floor_cache", "resell_cache", "enhanced_auth")

    def __init__(self,
                 config: dict,
                 blacklist: FileSync,
                 seen: FileSync,
                 not_resable: FileSync) -> None:
        super().__init__(config)
        
        self.config = config

        self._items = dict()
        
        # Use enhanced auth if TOTP secret is provided
        if config.get("TOTP_Secret"):
            self.auth = EnhancedAuth(
                config.get("Cookie", "").strip(),
                totp_secret=config.get("TOTP_Secret"),
                max_threads=config.get("Settings", {}).get("Threads", 5)
            )
            print("[INFO] Enhanced Auth with 2FA support enabled")
        else:
            self.auth = Auth(config.get("Cookie", "").strip())
            print("[WARNING] No TOTP_Secret in config. 2FA challenges may fail.")
            
        self.enhanced_auth = isinstance(self.auth, EnhancedAuth)
        self.buy_checker = BuyChecker(self)

        self.blacklist = blacklist
        self.seen = seen
        self.not_resable = not_resable

        if self.presence_enabled:
            self.rich_presence = AioPresence(PRESENCE_BOT_ID)

        self.current_index = 0
        self.done = False
        self.total_sold = 0
        self.selling = WithBool()
        self.loaded_time: datetime = None
        self.control_panel: ControlPanel = None
        
        # New caching systems
        self.price_floor_cache = {}
        self.resell_cache = {}

    @property
    def items(self) -> List[Item]:
        return list(self._items.values())

    @property
    def current(self) -> Item:
        return self.items[self.current_index]

    def get_item(self, _id: int, default: Optional[Any] = None) -> Union[Item, Any]:
        return self._items.get(_id, default)

    def add_item(self, item: Item) -> Item:
        self._items.update({item.id: item})
        return item

    def remove_item(self, _id: int) -> Item:
        return self._items.pop(_id)

    def next_item(self, *, step_index: int = 1) -> None:
        self.current_index = (self.current_index + 1) % len(self.items)

        if self.presence_enabled:
            asyncio.create_task(self.update_presence())

        if not self.current_index:
            self.done = True

        self.fetch_item_info(step_index=step_index)

    async def update_presence(self) -> None:
        easter_egg = random() < 0.3

        await self.rich_presence.update(
            state=f"{self.current_index + 1} out of {len(self.items)}",
            details=f"Selling {self.current.name} limited",
            large_image=self.current.thumbnail if not easter_egg else "https://cdn.discordapp.com/avatars/1284536257958903808/fa4fba77caa6cc68f2972e2ea33e67a5.png?size=4096",
            large_text=f"{self.current.name} limited" if not easter_egg else "Pisun easter egg (3% chance)",
            small_image="https://cdn.discordapp.com/app-assets/1005469189907173486/1025422070600978553.png?size=160",
            small_text="Roblox",
            buttons=[{"url": self.current.link, "label": "Selling Item"},
                     {"url": URL_REPOSITORY, "label": "Use Tool Yourself"}],
            start=int(self.loaded_time.timestamp())
        )

    # ==================== NEW: Enhanced API Methods ====================
    async def get_cached_price_floor(self, asset_type: int) -> int:
        """Get price floor with caching"""
        if asset_type in self.price_floor_cache:
            return self.price_floor_cache[asset_type]
        
        if self.enhanced_auth:
            price_floor = await self.auth.get_price_floor(asset_type)
        else:
            # Fallback to manual request
            url = f"https://itemconfiguration.roblox.com/v1/items/price-floor?collectibleItemType=1&creationType=1&assetType={asset_type}"
            data = await self.auth.request("GET", url)
            price_floor = data.get("priceFloor", 0) if data and isinstance(data, dict) else 0
        
        self.price_floor_cache[asset_type] = price_floor
        return price_floor
    
    async def prefetch_resell_data(self, item_ids: list):
        """Prefetch resell data for multiple items efficiently"""
        print(f"[INFO] Prefetching resell data for {len(item_ids)} items...")
        
        for c_id in item_ids:
            if c_id in self.resell_cache:
                continue
                
            instances = {}
            cursor = ""
            
            while True:
                url = f"https://apis.roblox.com/marketplace-sales/v1/item/{c_id}/resellable-instances"
                url += f"?ownerType=User&ownerId={self.auth.user_id}&limit=500"
                if cursor:
                    url += f"&cursor={cursor}"
                
                data = await self.auth.request("GET", url)
                if not data or 'itemInstances' not in data:
                    break
                
                for inst in data['itemInstances']:
                    instance_id = inst.get("collectibleInstanceId")
                    if instance_id:
                        instances[instance_id] = inst
                
                cursor = data.get("nextPageCursor")
                if not cursor:
                    break
            
            self.resell_cache[c_id] = instances
        
        print(f"[INFO] Resell data cached for {len(self.resell_cache)} items")
    
    async def filter_non_resable(self):
        if (self.current_index + 2) % 30 or not self.current_index:
            return None

        try:
            async with self.auth.post(
                "apis.roblox.com/marketplace-items/v1/items/details",
                json={"itemIds": [i.item_id for i in self.items[self.current_index:30]]}
            ) as response:
                data = await response.json()
                
                # Check if response is a dictionary with data
                if isinstance(data, dict) and "data" in data:
                    items_data = data["data"]
                elif isinstance(data, list):
                    items_data = data
                else:
                    # Try to get items from different possible response structures
                    items_data = data.get("items", []) or data.get("data", [])
                
                for item_details in items_data:
                    if isinstance(item_details, dict):
                        item_id = item_details.get("itemTargetId") or item_details.get("assetId")
                        
                        if item_id and item_details.get("resaleRestriction") == 1:
                            self.not_resable.add(item_id)
                            self.remove_item(item_id)
        except Exception as e:
            print(f"Error in filter_non_resable: {e}")
            # Don't crash on this error, just continue

    def fetch_item_info(self, *, step_index: int = 1) -> Optional[Iterable[Task]]:
        try:
            item = self.items[self.current_index + step_index]
        except IndexError:
            return None

        return (
            asyncio.create_task(item.fetch_sales(save_sales=False)),
            asyncio.create_task(item.fetch_resales(save_resales=False)),
            asyncio.create_task(self.filter_non_resable())
        )

    def sort_items(self, _type: str) -> None:
        self._items = dict(sorted(self._items.items(), key=lambda x: getattr(x[1], _type)))

    async def start(self):
        await asyncio.gather(self.auth.fetch_csrf_token(),
                             self.handle_exceptions())

        Display.info("Checking cookie to be valid")
        if await self.auth.fetch_user_info() is None:
            return Display.exception("Invalid cookie provided")

        Display.info("Checking premium owning")
        if not await self.auth.fetch_premium():
            return Display.exception("You dont have premium to sell limiteds")

        await self._load_items()
        self.sort_items("name")

        if self.presence_enabled:
            try:
                await self.rich_presence.connect()
                await self.update_presence()
            except DiscordNotFound:
                return Display.exception("Could find Discord running to show presence")

        try:
            async with self:
                tasks = (
                    discord_bot_start(self) if self.discord_bot else None,
                    self.buy_checker.start() if self.buy_webhook else None,
                    self.auth.csrf_token_updater(),
                    self.start_selling()
                )
                await asyncio.gather(*filter(None, tasks))
        except LoginFailure:
            return Display.exception("Invalid discord token provided")
        except:
            return Display.exception(f"Unknown error occurred:\n\n{format_exc()}")

    async def start_selling(self):
        for i in range(2):
            tasks = self.fetch_item_info(step_index=i)
            if tasks:
                for task in tasks:
                    await task

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
        await Display.custom(
            f"Selling [g{len(self.current.collectibles)}x] of [g{self.current.name}] items...",
            "selling", Color(255, 153, 0))

        sold_amount = await self.current.sell_collectibles(
            skip_on_sale=self.skip_on_sale,
            skip_if_cheapest=self.skip_if_cheapest,
            verbose=True
        )

        if sold_amount is not None:
            self.total_sold += sold_amount

            if self.sale_webhook and sold_amount > 0:
                asyncio.create_task(self.send_sale_webhook(self.current, sold_amount))

        if self.save_progress:
            self.seen.add(self.current.id)

        self.next_item()

    async def _auto_sell_items(self):
        while not self.done:
            await self.sell_item()
            await asyncio.sleep(0.5)

    async def _manual_selling(self):
        while not self.done:
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
                    self.blacklist.add(self.current.id)
                    self.next_item()

                    Display.success(f"Successfully added [g{self.current.name} ({self.current.id})] into a blacklist!")
                case "4":
                    if self.save_progress:
                        self.seen.add(self.current.id)

                    self.next_item()
                    Display.skipping(
                        f"Skipped [g{len(self.current.collectibles)}x] collectibles")
                case _:
                    continue

            await asyncio.sleep(0.7)

    # ==================== ENHANCED: Inventory Loading with Efficient Scanning ====================
    async def __fetch_items_enhanced(self) -> AsyncGenerator:
        """Enhanced inventory loading with batch processing"""
        Display.info("Loading your inventory (enhanced mode)")
        
        # Define all collectible asset types
        asset_types = [8, 41, 42, 43, 44, 45, 46, 47, 64, 65, 66, 67, 68, 69, 72]
        all_items = []
        
        # Load all items from inventory
        for asset_type in asset_types:
            cursor = ""
            while True:
                data = await self.auth.request(
                    "GET",
                    f"https://inventory.roblox.com/v2/users/{self.auth.user_id}/inventory/{asset_type}?"
                    f"cursor={cursor}&limit=100&sortOrder=Desc"
                )
                
                if not data or 'data' not in data:
                    break
                
                for item in data['data']:
                    # Apply filters early
                    if item.get("assetId") in self.blacklist:
                        continue
                    
                    if item.get("serialNumber") and int(item.get("serialNumber", 0)) <= getattr(self, 'keep_serials', 0):
                        continue
                    
                    all_items.append({
                        "item": item,
                        "asset_type": asset_type
                    })
                
                cursor = data.get("nextPageCursor")
                if not cursor:
                    break
        
        if not all_items:
            Display.exception("You dont have any limited UGC items")
            return
        
        # Batch process item details and thumbnails
        item_ids = [str(item["item"]["assetId"]) for item in all_items]
        
        Display.info(f"Found {len(all_items)} items. Processing in batches...")
        
        # Get item details in batches of 120
        items_details_map = {}
        for i in range(0, len(item_ids), 120):
            batch_ids = item_ids[i:i+120]
            details = await get_items_details(self.auth, batch_ids)
            if details and isinstance(details, list):
                for detail in details:
                    if detail and "assetId" in detail:
                        items_details_map[detail["assetId"]] = detail
        
        # Get thumbnails in batches of 100
        thumbnails_map = {}
        for i in range(0, len(item_ids), 100):
            batch_ids = item_ids[i:i+100]
            thumbnails = await get_assets_thumbnails(self.auth, batch_ids)
            if thumbnails and isinstance(thumbnails, list):
                for thumb in thumbnails:
                    if thumb and "assetId" in thumb:
                        thumbnails_map[thumb["assetId"]] = thumb
        
        # Yield processed items
        for entry in all_items:
            item_data = entry["item"]
            asset_id = item_data["assetId"]
            
            yield (
                item_data,
                items_details_map.get(asset_id, {}),
                thumbnails_map.get(asset_id, {})
            )

    async def __fetch_items(self) -> AsyncGenerator:
        # Use enhanced version if enabled in config
        if self.config.get("Settings", {}).get("Use_Enhanced_Scanner", True):
            async for item_info in self.__fetch_items_enhanced():
                yield item_info
        else:
            # Original method
            Display.info("Loading your inventory")
            user_items = await AssetsLoader(get_user_inventory, ITEM_TYPES.keys()).load(self.auth)
            if not user_items:
                Display.exception("You dont have any limited UGC items")

            item_ids = [str(asset["assetId"]) for asset in user_items]

            Display.info("Loading items thumbnails")
            items_thumbnails = await AssetsLoader(get_assets_thumbnails, item_ids, 100).load(self.auth)

            Display.info(f"Found {len(user_items)} items. Checking them...")
            items_details = await AssetsLoader(get_items_details, item_ids, 120).load(self.auth)

            for item_info in zip(user_items, items_details, items_thumbnails):
                yield item_info

    async def _load_items(self) -> None:
        if self.loaded_time is not None:
            return Display.exception("You have already loaded items")

        Display.info("Getting current limiteds cap")
        items_cap = await get_current_cap(self.auth)

        ignored_items = list(self.seen | self.blacklist | self.not_resable)

        async for item, item_details, thumbnail in self.__fetch_items():
            item_id = item["assetId"]

            if (
                item_id in ignored_items
                or item_details.get("creatorTargetId") in getattr(self, 'creators_blacklist', [])
            ):
                continue

            item_obj = self.get_item(item_id)

            if item_obj is None:
                # Handle the new API response structure
                asset_cap = 0  # Default value since price floors are not available in new API
                
                # Try to get the price floor from the new API if available
                if items_cap and isinstance(items_cap, dict):
                    item_type = ITEM_TYPES[item_details.get("assetType", 0)]
                    
                    # Check if items_cap has the expected structure
                    if isinstance(items_cap, dict) and "limitedItemPriceFloors" in items_cap:
                        price_floors = items_cap.get("limitedItemPriceFloors")
                        if price_floors and item_type in price_floors:
                            asset_cap = price_floors[item_type].get("priceFloor", 0)
                    elif item_type in items_cap and items_cap[item_type]:
                        # Old structure
                        asset_cap = items_cap[item_type].get("priceFloor", 0)
                
                # Get actual price floor from API if enhanced auth is available
                if self.enhanced_auth:
                    asset_cap = max(asset_cap, await self.get_cached_price_floor(item_details.get("assetType", 0)))
                
                sell_price = define_sale_price(
                    getattr(self, 'under_cut_amount', 0),
                    getattr(self, 'under_cut_type', 'percent'),
                    asset_cap,
                    item_details.get("lowestResalePrice", 0)
                )

                item_obj = Item(
                    item, item_details,
                    price_to_sell=sell_price,
                    thumbnail=thumbnail,
                    auth=self.auth
                )
                self.add_item(item_obj)

            item_obj.add_collectible(
                serial=item.get("serialNumber"),
                item_id=item.get("collectibleItemId"),
                instance_id=item.get("collectibleItemInstanceId")
            )

        if not self.items:
            Display.error(f"You dont have any limiteds that are not in[g blacklist/] directory")
            clear_items = await Display.input(f"Do you want to reset your selling progress? (Y/n): ")

            if clear_items.lower() == "y":
                self.seen.clear()
                Display.success("Cleared your limiteds selling progress")
                Tools.exit_program()

        if getattr(self, 'keep_serials', 0) or getattr(self, 'keep_copy', 0):
            for item in self.items:
                if len(item.collectibles) <= getattr(self, 'keep_copy', 0):
                    self.remove_item(item.id)
                    continue

                for col in item.collectibles:
                    if col.serial > getattr(self, 'keep_serials', 0):
                        col.skip_on_sale = True

        if not self.items:
            not_met = []

            if getattr(self, 'keep_copy', 0): 
                not_met.append(f"{getattr(self, 'keep_copy', 0)} copies or higher")
            if getattr(self, 'keep_serials', 0): 
                not_met.append(f"{getattr(self, 'keep_serials', 0)} serial or higher")

            list_requirements = ", ".join(not_met)
            return Display.exception(f"You dont have any limiteds with {list_requirements}")

        # Prefetch resell data for better performance
        if self.config.get("Settings", {}).get("Prefetch_Resell_Data", True):
            unique_ids = list(set(item.id for item in self.items))
            await self.prefetch_resell_data(unique_ids)

        self.loaded_time = datetime.now()

    async def update_console(self) -> None:
        Tools.clear_console()
        Display.main()

        item = self.current

        data = {
            "Info": {
                "Discord Bot": define_status(self.discord_bot),
                "Save Items": define_status(self.save_progress),
                "Under Cut": f"-{self.under_cut_amount}{'%' if self.under_cut_type == 'percent' else ''}",
                "Total Blacklist": f"{len(self.blacklist)}",
                "2FA Enabled": "Yes" if self.enhanced_auth and self.auth.totp_secret else "No"
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

        async with ClientSession() as session:
            async with session.post(self.sale_webhook_url, json=data) as response:
                if response.status == 429:
                    await asyncio.sleep(30)
                    await self.send_sale_webhook(item, sold_amount)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        tasks = (
            self.auth.close_session(),
            self.control_panel.message.delete() if self.control_panel else None
        )

        await asyncio.gather(*filter(None, tasks))


async def main() -> None:
    Display.info("Setting up everything...")

    Display.info("Checking for updates")
    if await check_for_update(RAW_CODE_URL, VERSION):
        await Display.custom(
            "Your code is outdated. Please update it from github",
            "new", Color(163, 133, 0), exit_after=True)

    Display.info("Loading config")
    config = load_file("config.json")

    Display.info("Loading data assets")
    blacklist = FileSync("blacklist/blacklist.json")
    seen = FileSync("blacklist/seen.json")
    not_resable = FileSync("blacklist/not_resable.json")

    auto_seller = AutoSeller(config, blacklist, seen, not_resable)

    try:
        await auto_seller.start()
    except:
        return Display.exception(f"Unknown error occurred:\n\n{format_exc()}")


if __name__ == "__main__":
    asyncio.run(main())

"""
    ___     __      ___       _  _       _  _          _    _         _         ___          _  _       ____       ___        ____   
   F _ ",   FJ     F __".    FJ  L]     F L L]        F L  J J       /.\       F __".       FJ  L]     F ___J     F _ ",     F ___J  
  J `-' |  J  L   J (___|   J |  | L   J   \| L      J J .. L L     //_\\     J (___|      J |__| L   J |___:    J `-'(|    J |___:  
  |  __/F  |  |   J\___ \   | |  | |   | |\   |      | |/  \| |    / ___ \    J\___ \      |  __  |   | _____|   |  _  L    | _____| 
  F |__/   F  J  .--___) \  F L__J J   F L\\  J      F   /\   J   / L___J \  .--___) \     F L__J J   F L____:   F |_\  L   F L____: 
 J__|     J____L J\______J J\______/F J__L \\__L    J___//\\___L J__L   J__L J\______J    J__L  J__L J________L J__| \\__L J________L
 |__L     |____|  J______F  J______F  |__L  J__|    |___/  \___| |__L   J__|  J______F    |__L  J__| |________| |__|  J__| |________|
                                                                                                                                     

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#**##***%%%%%%%%%%%%%%%%%%%%%%%%%@@@@@@@@@@@@@@@@@@@@@@@@@@@
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%##*+=-:::::::::-----=+*##%%%%%%%%%%%%%%%%@@@@@@@@@@@@@@@@@@@@@@@
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%##+=--:::::::::::::::::::::::::-+*##%%%%%%%%%%%%%@@@@@@@@@@@@@@@@@@@@
%%%%%%%%%%%%%%%%%%%%%%%%%%#**+=-:::::::::::::::::::::::::::::::::::-=**#%%%%%%%%%%%%%%@@@@@@@@@@@@@%
######%%%%%%%%%%%%%%%%%##+=-:::::::::::::::::::::::::::::::::::::::::::=*#%%%%%%%%%%%%%%%%%%%%%%%%%%
##########%%%%%%%%###*+=-::::::::::::::::::::::::::::::::::::::::::::::::-*#%%%%%%%%%%%%%%%%%%%%%%%%
##############%%###+=----::::::::::::::::::::::::::::::::::::::::::::::::::-*#%%%%%%%%%%%%%%%%%%%%%%
#################*=------------:----:::::::::::::::::::::::::::::::::::::::::-*#%%%%%%%%%%%%%%%%%%%%
################*+=------------------------------:::::::::::::::::::::::::::::-*#%%%%%%%%%%%%%%%%%%%
##############+=====------------------------------:::::::::::::::::::::::::::::=##%%%%%%%%%%%%%%%%%%
############*=----===--------------=======------------:::::::::::::::::::::::::-*###%%%%%%%%%%%%%%%%
##########*+------====-------===================---------::----:::::---::::::::-+######%%%%%%%%%%%%%
#########*=--------====-===========+++++++****++===------------------=---:::::::=*#########%%%%%%%%%
########+--------============+++++++++*###%@@@%#*+=====--------=++======---:::::=*###########%%%%%%%
#######+=--------=============+++++++++%%%@@@@@@@#**++===-----=*#==+++===---:::-+*##############%%%%
######+=---------=====------===========+*#%@@@@@@@@%%#**+++++*%@%#*##*++====---=+**##############%%%
#####*==---------====------------=========+*#%%%%%%%%%#*******#%@@%%#**++++====--=+*################
####*+==--------=====--------------=============+=++++*****#######%%#####***++===-=+***#############
###*+===--------=====----------------================++*#%###%%###*******###**++===--+***###########
##*====--------=====-------------------================+##**#######%%%%#####***++==--=+****#########
##*======------====----==-=======------=================+**######%%%%%%%%%%%%%%#*#*=::-=+***########
##+=======---======--------------==------=======------====++****###%%%%%##%%%@@%#+=-:::-+****#######
#*+===============----------------==--------------=----====++***###%%%%%%%%#+--:::::::::-+****######
#*+=========+=====------=====-------------------==--------===+****#**++----::::::::::::::-+*****####
*+====================------------------------==----------===+++++++==----::::::::::::::::-+*****###
+=========++++=========--=-----=--------------===----------=+++=======---:::::::::::::::::-=******##
+==+++===+*++==--===============-----------------==---------++==+====-----:::::::::::::::::-+******#
++++++++++*+++=====================----======---==----------====+==-----::::::::::::::::::::=+*****#
+++=====++++++=+==================================--==---------====----:::::::::::::::::::::-+******
++++====++**+++++++======++====++===============----==----------===----:::::::::::::::::::::-=+*****
+++++++++****+==++++=====+++==++++===============-====-----------------:::::::::::::::::::::-=+*****
**++++++****++++++++=======+++=+++========++===========----------------::::::::::::::::::::::=+*****
**+*********++=++++++=======++++++=======================---------------::::::::::::::::::::-=++****
**++++*+*****++*++*++++==========+================----=====-------------::::::::::::::::::::-=+*****
**++++++*##***+++++=+++++=================---=======----===--------------::::::::::--::::::::=+*****
********###***++==+++=++++======+=========-=---===---------=--------------:::::::::--:::::::-=+*****
***+*****###**+++++=+==++++========++=+++====--===--===----==-------------::::::::--::::::::-++*****
*********#####*+++*+++++++++==========++++=========-------------------------::-::--::::::::-=+******
*********######++*+++++=++=+=========================------------------------------:::::::--+++*****
*********######*****++++++++++++======================-----------------------------:::::::-=++++****
*******#########******+*+=+++++++++=++=++====================---------------------:::::::-=++++++***
*****############*+******+++++++++++++==+====================-------------------------:::-=+++++++**
******############***#***++===+==+==+==========================-----------------------:--=+++++++++*
******#############**##****+==+++++++====+++++===-==============------------------------=+++++++++++
*******##########%%#****##****++++++++=+=+++=+==============---===---------------------=++++++++++++
********###%%%%###%%%##*********++++++++++++==+====================---==--------------=+++++++++++++
**********#%%%%%%#%%%%%##***+****+++++++==+++===----======+++++========-------------=+++++++++++++++
***********##%%%%%%#%%%%%%####*****++++*++=+++++=======+++++++=====----======-----==++++++++++++++++
************##%%%%%%%#%%%%%%%%######******++**++******+++++++=====----====-----===++++++++++++++*+++
**************#%%%%%%%%%%%%%%%%%%%%%%%#########*#**#**+++++=+===================+++++++++++++++*****
*********####**##%%%%%%%%%%%%%%%%%%%%%%%%%%%###***++++++==++==++==============+++++++++*************
###################%%%@@@%%%%%%%##########*******++++++=++++++++++=========+++**********************
%%%%%%%%%%%#%%#%%%%%%%%@@@@@@@@%%##%##*##*****##**++++++++***++++++++++++**************************##
%%%%%%%%%%%%%%%%%%%%%%%%%%@@@@@@@@@@%%%%%@%########***************++++****************************###
%%%%%%%%%%%%%%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@%%%%%%%%%%##########********************************###
"""
