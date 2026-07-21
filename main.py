import asyncio, aiohttp, json, html, requests, re, os
from datetime import datetime, timezone
from typing import cast
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, BaseFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) # type: ignore
ASF_URL = os.getenv("ASF_URL")
ASF_PASSWORD = os.getenv("ASF_PASSWORD")

PAGE_SIZE = 40
GAMES = {730: "CS2", 440: "TF2", 570: "Dota 2"}
appid = 753
contextid = 6
console_users, redeem_users = set(), set()
twofa_tasks, inventory_cache, redeem_messages, bot_redeem_users, bot_redeem_messages = {}, {}, {}, {}, {}

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) # type: ignore
dp = Dispatcher()

class AdminFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == ADMIN_ID # type: ignore

class AdminCallbackFilter(BaseFilter):
    async def __call__(self, callback: CallbackQuery) -> bool:
        return callback.from_user.id == ADMIN_ID
    
def asf_get(path: str):
    return requests.get(f"http://127.0.0.1:1242{path}", headers={"Authentication": ASF_PASSWORD})

def get_currency_name(currency_id: int) -> str:
    if currency_id == 1:
        return "USD"
    elif currency_id == 3:
        return "EUR"
    elif currency_id == 5:
        return "RUB"
    elif currency_id == 18:
        return "UAH"
    elif currency_id == 6:
        return "PLN"
    elif currency_id == 0:
        return ""
    else:
        return "???"

def get_inventory_icon(desc: dict) -> str:
    tags = desc.get("tags", [])
    for tag in tags:
        category = tag.get("category", "")
        name = tag.get("localized_tag_name", "")
        if category == "item_class":
            if "Trading Card" in name:
                return "🃏"
            if "Emoticon" in name:
                return "😀"
            if "Profile Background" in name:
                return "🖼"
            if "Booster Pack" in name:
                return "📦"
            if "Steam Gems" in name:
                return "💎"
        if "Gift" in name:
            return "🎁"
    item_type = desc.get("type", "").lower()
    if "knife" in item_type:
        return "🔪"
    if "pistol" in item_type:
        return "🔫"
    if "rifle" in item_type:
        return "🎯"
    if "graffiti" in item_type:
        return "🎨"
    if "music kit" in item_type:
        return "🎵"
    return "📦"
    
def format_asf(data: dict) -> str:
    result = data.get("Result", {})
    config = result.get("GlobalConfig", {})
    current_version = result.get("Version")
    latest_version = result.get("LatestVersion", current_version)
    lines = [f"Версия ASF: {current_version}"]
    if current_version != latest_version:
        lines.append(f"Доступно обновление: {latest_version}")
    memory_kb = result.get("MemoryUsage", 0)
    memory_mb = memory_kb / 1024
    lines.append(f"Используется памяти: {memory_mb:.2f} MB")
    lines.append(f"Работает: {get_uptime(result.get('ProcessStartTime'))}")
    return "\n".join(lines)

def get_uptime(start_time_str: str) -> str:
    start_time_str = start_time_str[:26] + "Z"
    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta = now - start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}д {hours}ч {minutes}м {seconds}с"

def get_bot_status_icon(bot: dict) -> str:
    online = bot.get("IsConnectedAndLoggedOn", False)
    farming = bot.get("CardsFarmer", {}).get("NowFarming", False)
    idle_games = bot.get("BotConfig", {}).get("GamesPlayedWhileIdle", [])
    loaded = bool(bot.get("BotName")) and bool(bot.get("SteamID"))
    if not loaded:
        return "🔄"
    if farming:
        return "🎴"
    if idle_games and online:
        return "⌚"
    if online:
        return "🟢"
    return "🔴"

def format_bot_ui(bot: dict) -> str:
    online = get_bot_status_icon(bot)
    now_farming = bot.get("CardsFarmer", {}).get("NowFarming")
    if now_farming:
        status_line = "🃏 Идет фарм карточек"
    else:
        status_line = "🃏 Карточки не фармится"
    time = bot.get("CardsFarmer", {}).get("TimeRemaining", "00:00:00")
    games_to_farm = len(bot.get("CardsFarmer", {}).get("GamesToFarm", []))
    twofa = "есть" if bot.get("HasMobileAuthenticator") else "нет"
    balance = bot.get("WalletBalance", 0) / 100
    currency = get_currency_name(bot.get("WalletCurrency", 0))
    redeem = bot.get("GamesToRedeemInBackgroundCount", 0)
    steam_id = bot.get("SteamID")
    nickname = html.escape(str(bot.get("Nickname") or ""))
    profile_url = f"https://steamcommunity.com/profiles/{steam_id}"
    text = (
        f"{online}"
        f" {bot.get('BotName') or 'Загрузка...'}"
        f"(<a href=\"{profile_url}\">{nickname}</a>)\n"
        f"{status_line}\n")
    idle_games = bot.get("BotConfig", {}).get("GamesPlayedWhileIdle", [])
    if idle_games:
        names = [GAMES.get(g, str(g)) for g in idle_games]
        if bot.get("IsConnectedAndLoggedOn"):
            idle_text = f"⌚ Накрутка часов: включена ({', '.join(names)})"
        else:
            idle_text = f"⌚ Накрутка часов: включена ({', '.join(names)}) применится после запуска"
        text += f"{idle_text}\n"
    else:
        text += "⌚ Накрутка часов: выключена\n"
    text += (
        f"🆔 : <code>{steam_id}</code>\n"
        f"🔐 2FA: {twofa}\n\n"
        f"💰 Баланс: {balance:.2f} {currency}\n")
    if redeem > 0:
        text += f"\nКлючей в очереди: {redeem}\n"
    if now_farming:
        text += f"\nОсталось: {time}\n"
        if games_to_farm > 0:
            text += f"В очереди игр: {games_to_farm}\n"
    return text

def get_asf_status_text():
    response = requests.get(ASF_URL, headers={"Authentication": ASF_PASSWORD}) # type: ignore
    if response.status_code != 200:
        return f"Ошибка API: {response.status_code}"
    data = response.json()
    if not data.get("Success"):
        return "ASF вернул ошибку"
    status_text = format_asf(data)
    return f"<b>💻 Панель управления ASF</b>\n\n{status_text}"
    
def get_farm_summary(bots: dict) -> str:
    total_games = 0
    total_time_seconds = 0
    for bot in bots.values():
        farmer = bot.get("CardsFarmer", {})
        if farmer.get("NowFarming"):
            games = farmer.get("CurrentGamesFarming", [])
            total_games += len(games)
            time_str = farmer.get("TimeRemaining", "00:00:00")
            h, m, s = map(int, time_str.split(":"))
            total_time_seconds += h * 3600 + m * 60 + s
    if total_games == 0:
        return "На аккаунтах нечего не фармиться"
    hours = total_time_seconds // 3600
    minutes = (total_time_seconds % 3600) // 60
    return (
        f"Игр фармится: {total_games}\n"
        f"Осталось времени: {hours}ч {minutes}м\n"
        f"Карт осталось: ~{total_games * 3}")

def format_bot(bot_data: dict) -> str:
    return json.dumps(bot_data, indent=2, ensure_ascii=False)

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆙 Обновить", callback_data="refresh")],
        [InlineKeyboardButton(text="🤖 Боты", callback_data="bots")],
        [InlineKeyboardButton(text="🔑 Активация ключей на всех аккаунтах", callback_data="redeem_keys")],
        [InlineKeyboardButton(text="📁 Плагины", callback_data="plugins")],
        [InlineKeyboardButton(text="💻 Консоль", callback_data="console")],
        [InlineKeyboardButton(text="♻ Перезапустить ASF", callback_data="restart_asf_confirm")]])

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back")]])

def games_keyboard(bot_name, is_enabled):
    if is_enabled:
        text = "Остановить накрутку CS2"
    else:
        text = "⌚ Накрутить часы CS2"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=f"farm|{bot_name}|730")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"bot_{bot_name}")]])

def bots_keyboard(bots: dict):
    keyboard = []
    for name, bot in bots.items():
        status = get_bot_status_icon(bot)
        loaded = (bool(bot.get("BotName")) and bool(bot.get("SteamID")))
        if not loaded:
            callback_data = "bot_loading"
        else:
            callback_data = f"bot_{name}"
        keyboard.append([InlineKeyboardButton(text=f"{status} {name}", callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def is_bot_playing(bot_name: str) -> bool:
    response = asf_get("/Api/Bot/ASF")
    if response.status_code != 200:
        return False
    data = response.json()
    bot = data.get("Result", {}).get(bot_name, {})
    return bool(bot.get("PlayingBlocked", False)) or bool(bot.get("CurrentGamesPlayed", []))

def is_idle_enabled(bot_name: str, app_id: int) -> bool:
    response = requests.get(f"http://127.0.0.1:1242/Api/Bot/{bot_name}", headers={"Authentication": ASF_PASSWORD})
    if response.status_code != 200:
        return False
    data = response.json()
    bot = data.get("Result", {}).get(bot_name, {})
    config = bot.get("BotConfig", {})
    return app_id in config.get("GamesPlayedWhileIdle", [])

async def get_2fa_code(bot_name: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:1242/Api/Bot/{bot_name}/TwoFactorAuthentication/Token", headers={"Authentication": ASF_PASSWORD}) as response: # type: ignore
            if response.status != 200:
                return f"Ошибка HTTP {response.status}"
            data = await response.json()
            if not data.get("Success"):
                return "Ошибка ASF"
            try:
                return data["Result"][bot_name]["Result"]
            except:
                return "Не удалось получить код"

async def get_confirmations(bot_name: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:1242/Api/Bot/{bot_name}/TwoFactorAuthentication/Confirmations", headers={"Authentication": ASF_PASSWORD}) as response: # type: ignore
            if response.status != 200:
                return []
            data = await response.json()
            if not data.get("Success"):
                return []
            try:
                return data["Result"][bot_name]["Result"]
            except:
                return []

async def get_inventory(bot_name: str, appid: int, contextid: int = 2):
    url = (f"http://127.0.0.1:1242/Api/Bot/{bot_name}/Inventory/{appid}/{contextid}")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={"Authentication": ASF_PASSWORD}) as response: # type: ignore
            if response.status != 200:
                return None
            data = await response.json()
            if not data.get("Success"):
                return None
            try:
                return data["Result"]
            except:
                return None

async def render_inventory_page(callback: CallbackQuery, bot_name: str, inventory_type: str, appid: int, contextid: int, page: int):
    await callback.message.edit_text("Загрузка inventory...") # type: ignore
    inventory = await get_inventory(bot_name, appid, contextid)
    if not inventory:
        await callback.message.edit_text("Не удалось загрузить inventory") # type: ignore
        return
    bot_inventory = inventory.get(bot_name, {})
    assets = bot_inventory.get("Assets", [])
    descriptions = bot_inventory.get("Descriptions", [])
    if not assets:
        await callback.message.edit_text("Инвентарь пуст", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"inventory_{bot_name}")]])) # type: ignore
        return
    desc_map = {}
    for desc in descriptions:
        key = (str(desc.get("classid")), str(desc.get("instanceid")))
        desc_map[key] = desc
    total_pages = (len(assets) + PAGE_SIZE - 1) // PAGE_SIZE
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_assets = assets[start:end]
    lines = []
    marketable_count = 0
    tradable_count = 0
    cards_count = 0
    emotes_count = 0
    backgrounds_count = 0
    gems_count = 0
    for asset in page_assets:
        key = (str(asset.get("classid")), str(asset.get("instanceid")))
        desc = desc_map.get(key, {})
        name = desc.get("market_name", "Unknown")
        amount = asset.get("amount", 1)
        tradable = ("🔄" if desc.get("tradable") else "❌")
        marketable = ("💰" if desc.get("marketable") else "🔒")
        icon = get_inventory_icon(desc)
        if desc.get("marketable"):
            marketable_count += 1
        if desc.get("tradable"):
            tradable_count += 1
        if icon == "🃏":
            cards_count += amount
        elif icon == "😀":
            emotes_count += amount
        elif icon == "🖼":
            backgrounds_count += amount
        elif icon == "💎":
            gems_count += amount
        lines.append(f"{icon} {tradable}{marketable} {name} x{amount}")
    inv_name = ("CS2" if appid == 730 else "Steam")
    stats = (
        f"📦 Items: {len(assets)}\n"
        f"💰 Marketable: {marketable_count}\n"
        f"🔄 Tradable: {tradable_count}")
    if appid == 753:
        stats += (
            f"\n🃏 Cards: {cards_count}"
            f"\n😀 Emotes: {emotes_count}"
            f"\n🖼 Backgrounds: {backgrounds_count}"
            f"\n💎 Gems: {gems_count}")
    text = (
        f"📦 {inv_name} Inventory {bot_name}\n"
        f"📄 Страница {page + 1}/{total_pages}\n\n"
        f"{stats}\n\n"
        + "\n".join(lines))
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀", callback_data=f"invpage|{inventory_type}|{bot_name}|{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶", callback_data=f"invpage|{inventory_type}|{bot_name}|{page + 1}"))
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"inventory_{bot_name}")])
    await callback.message.edit_text(text[:4000], reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)) # type: ignore

async def reload_bot(bot_name: str):
    try:
        requests.post("http://127.0.0.1:1242/Api/Command", headers={"Authentication": ASF_PASSWORD}, json={"Command": f"!reload {bot_name}"})
    except:
        pass

async def stop_twofa_task(message_id: int):
    task = twofa_tasks.pop(message_id, None)
    if task:
        task.cancel()
        try:
            await task
        except:
            pass

async def redeem_key(bot_name: str, key: str):
    async with aiohttp.ClientSession() as session:
        async with session.post("http://127.0.0.1:1242/Api/Command", headers={"Authentication": ASF_PASSWORD}, json={"Command": f"!redeem {bot_name} {key}"}) as response: # type: ignore
            if response.status != 200:
                return False, f"HTTP_ERROR_{response.status}"
            data = await response.json()
            if not data.get("Success"):
                return False, "ASF_ERROR"
            return True, str(data.get("Result", ""))

@dp.callback_query(lambda c: c.data == "bot_loading", AdminCallbackFilter())
async def bot_loading_handler(callback: CallbackQuery):
    await callback.answer("Аккаунт ещё загружается. Попробуйте через несколько секунд.", show_alert=True)

async def auto_update_2fa(message, bot_name):
    last_code = None
    message_id = message.message_id
    try:
        while True:
            code = await get_2fa_code(bot_name)
            if code != last_code:
                confirmations = await get_confirmations(bot_name)
                keyboard = []
                if confirmations:
                    keyboard.append([InlineKeyboardButton(text="Подтверждения", callback_data=f"confirm_list_{bot_name}")])
                keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"bot_{bot_name}")])
                text = (
                    f"🔐 {bot_name}\n\n"
                    f"<code>{code}</code>")
                try:
                    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
                    last_code = code
                except:
                    break
            await asyncio.sleep(15)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"2FA updater error: {e}")
    finally:
        twofa_tasks.pop(message_id, None)

@dp.message(Command("start"), AdminFilter())
async def start_handler(message: Message):
    try:
        await message.delete()
    except:
        pass
    try:
        text = get_asf_status_text()
        await message.answer(text, reply_markup=main_keyboard())
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.callback_query(lambda c: c.data == "console", AdminCallbackFilter())
async def console_enter(callback: CallbackQuery):
    await callback.answer()
    console_users.add(callback.from_user.id)
    await callback.message.edit_text("💻 Консоль ASF\n\nОтправь команду (без !)", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="console_exit")]])) # type: ignore

@dp.callback_query(lambda c: c.data == "console_exit", AdminCallbackFilter())
async def console_exit(callback: CallbackQuery):
    await callback.answer()
    console_users.discard(callback.from_user.id)
    text = get_asf_status_text()
    await callback.message.edit_text(text, reply_markup=main_keyboard()) # type: ignore

@dp.callback_query(lambda c: c.data == "delete_msg", AdminCallbackFilter())
async def delete_message(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete() # type: ignore
    except:
        pass

@dp.callback_query(lambda c: c.data == "bots", AdminCallbackFilter())
async def bots_handler(callback: CallbackQuery):
    await stop_twofa_task(callback.message.message_id) # type: ignore
    await callback.answer()
    try:
        response = requests.get("http://127.0.0.1:1242/Api/Bot/ASF", headers={"Authentication": ASF_PASSWORD})
        if response.status_code != 200:
            await callback.message.edit_text("Ошибка API") # type: ignore
            return
        data = response.json()
        if not data.get("Success"):
            await callback.message.edit_text("ASF вернул ошибку") # type: ignore
            return
        bots = data.get("Result", {})
        count = len(bots)
        summary = get_farm_summary(bots)
        text = (
            f"<b>🤖 Ботов всего:</b> {count}\n\n"
            f"{summary}")
        await callback.message.edit_text(text, reply_markup=bots_keyboard(bots)) # type: ignore
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data and c.data.startswith("bot_"), AdminCallbackFilter())
async def bot_selected(callback: CallbackQuery):
    await stop_twofa_task(callback.message.message_id) # type: ignore
    await callback.answer()
    if not callback.data:
        return
    bot_name = callback.data.replace("bot_", "")
    try:
        response = asf_get("/Api/Bot/ASF")
        data = response.json()
        bots = data.get("Result", {})
        bot = bots.get(bot_name)
        if not bot or not bot.get("BotName") or not bot.get("SteamID"):
            await callback.answer("Аккаунт ещё загружается. Попробуйте через несколько секунд.", show_alert=True)
            return
        if not bot:
            await callback.message.edit_text("Бот не найден") # type: ignore
            return
        text = format_bot_ui(bot)
        keyboard = []
        if bot.get("HasMobileAuthenticator"):
            keyboard.append([InlineKeyboardButton(text="🔐 2FA", callback_data=f"2fa_{bot_name}")])
        keyboard.append([InlineKeyboardButton(text="⌚ Накрутка часов", callback_data=f"games_{bot_name}")])
        keyboard.append([InlineKeyboardButton(text="🔑 Активировать ключ", callback_data=f"redeem_bot_{bot_name}")])
        keyboard.append([InlineKeyboardButton(text="📦 Инвентарь", callback_data=f"inventory_{bot_name}")])
        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="bots")])

        await callback.message.edit_text(text, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)) # type: ignore
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data and c.data.startswith("games_"), AdminCallbackFilter())
async def games(callback: CallbackQuery):
    await callback.answer()
    if not callback.data:
        return
    bot_name = callback.data.replace("games_", "")
    idle_enabled = is_idle_enabled(bot_name, 730)
    await callback.message.edit_text("⌚ Выберите игру для накрутки часов", reply_markup=games_keyboard(bot_name, idle_enabled)) # type: ignore

@dp.callback_query(lambda c: c.data == "back", AdminCallbackFilter())
async def back_button(callback: CallbackQuery):
    redeem_users.discard(callback.from_user.id)
    redeem_messages.pop(callback.from_user.id, None)
    console_users.discard(callback.from_user.id)
    bot_redeem_users.pop(callback.from_user.id, None)
    bot_redeem_messages.pop(callback.from_user.id, None)
    await stop_twofa_task(callback.message.message_id) # type: ignore
    await callback.answer()
    try:
        text = get_asf_status_text()
        await callback.message.edit_text(text, reply_markup=main_keyboard()) # type: ignore
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data == "refresh", AdminCallbackFilter())
async def refresh_handler(callback: CallbackQuery):
    await callback.answer()
    try:
        text = get_asf_status_text()
        await callback.message.edit_text(text, reply_markup=main_keyboard()) # type: ignore
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data == "restart_asf_confirm", AdminCallbackFilter())
async def restart_asf_confirm(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text( # type: ignore
        "♻ Точно перезапустить ASF?\n\n"
        "Во время перезапуска IPC будет недоступен несколько секунд.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Да", callback_data="restart_asf")],
                [InlineKeyboardButton(text="Нет", callback_data="back")]]))

@dp.callback_query(lambda c: c.data == "restart_asf", AdminCallbackFilter())
async def restart_asf(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text("♻ ASF перезапускается...") # type: ignore
        response = requests.post("http://127.0.0.1:1242/Api/Command", headers={"Authentication": ASF_PASSWORD}, json={"Command": "!restart"})
        if response.status_code != 200:
            await callback.message.edit_text(f"Ошибка HTTP {response.status_code}", reply_markup=main_keyboard()) # type: ignore
            return
        await asyncio.sleep(6)
        text = get_asf_status_text()
        await callback.message.edit_text(f"ASF успешно перезапущен\n\n{text}", reply_markup=main_keyboard()) # type: ignore
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}", reply_markup=main_keyboard()) # type: ignore

@dp.callback_query(lambda c: c.data and c.data.startswith("2fa_") and not c.data.startswith("2fa_refresh_"), AdminCallbackFilter())
async def twofa_handler(callback: CallbackQuery):
    await callback.answer()
    if not callback.data:
        return
    bot_name = callback.data.replace("2fa_", "")
    message_id = callback.message.message_id # type: ignore
    old_task = twofa_tasks.pop(message_id, None)
    if old_task:
        old_task.cancel()
        try:
            await old_task
        except:
            pass
    await callback.message.edit_text( # type: ignore
        f"🔐 {bot_name}\n\nЗагрузка 2FA...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"bot_{bot_name}")]]))
    task = asyncio.create_task(auto_update_2fa(callback.message, bot_name))
    twofa_tasks[message_id] = task

@dp.callback_query(lambda c: c.data and c.data.startswith("confirm_") and not c.data.startswith("confirm_list_") and not c.data.startswith("confirm_all_"), AdminCallbackFilter())
async def confirm_trades(callback: CallbackQuery):
    await callback.answer()
    bot_name = callback.data.replace("confirm_", "") # type: ignore
    try:
        response = requests.post(f"http://127.0.0.1:1242/Api/Bot/{bot_name}/TwoFactorAuthentication/Confirmations/Accept", headers={"Authentication": ASF_PASSWORD})
        if response.status_code != 200:
            await callback.answer("Ошибка HTTP", show_alert=True)
            return
        await callback.answer("Подтверждено", show_alert=True)
        await twofa_handler(callback)
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data == "plugins", AdminCallbackFilter())
async def plugins_handler(callback: CallbackQuery):
    await stop_twofa_task(callback.message.message_id) # type: ignore
    await callback.answer()
    try:
        response = requests.get("http://127.0.0.1:1242/Api/Plugins", headers={"Authentication": ASF_PASSWORD})
        if response.status_code != 200:
            await callback.message.edit_text("Ошибка API") # type: ignore
            return
        data = response.json()
        if not data.get("Success"):
            await callback.message.edit_text("ASF вернул ошибку") # type: ignore
            return
        plugins = data.get("Result", [])
        if not plugins:
            text = "Плагины не установлены"
        else:
            text = "<b>📁 Плагины ASF:</b>\n\n"
            for plugin in plugins:
                name = plugin.get("Name", "???")
                version = plugin.get("Version", "???")
                text += f"{name} ({version})\n"
        await callback.message.edit_text(text.strip(), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back")]])) # type: ignore
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data and c.data.startswith("confirm_list_"), AdminCallbackFilter())
async def confirm_list(callback: CallbackQuery):
    await stop_twofa_task(callback.message.message_id) # type: ignore
    await callback.answer()
    if not callback.data:
        return
    bot_name = callback.data.replace("confirm_list_", "")
    try:
        confirmations = await get_confirmations(bot_name)
        if not confirmations:
            text = "Подтверждений нет"
        else:
            text = f" {bot_name}\n\nПодтверждения:\n\n"
            for conf in confirmations:
                text += (
                    f"- {conf['type_name']}\n"
                    f"ID: <code>{conf['id']}</code>\n\n")
        await callback.message.edit_text(text, # type: ignore
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Подтвердить всё", callback_data=f"confirm_all_{bot_name}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"2fa_{bot_name}")]]))
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data and c.data.startswith("confirm_all_"), AdminCallbackFilter())
async def confirm_all(callback: CallbackQuery):
    await stop_twofa_task(callback.message.message_id) # type: ignore
    await callback.answer()
    if not callback.data:
        return
    bot_name = callback.data.replace("confirm_all_", "")
    try:
        response = requests.post(f"http://127.0.0.1:1242/Api/Bot/{bot_name}/TwoFactorAuthentication/Confirmations/Accept", headers={"Authentication": ASF_PASSWORD})
        if response.status_code != 200:
            await callback.answer("Ошибка HTTP", show_alert=True)
            return
        # заново получаем список
        confirmations = await get_confirmations(bot_name)
        if not confirmations:
            text = f" {bot_name}\n\nПодтверждений больше нет"
        else:
            text = f" {bot_name}\n\nПодтверждения:\n\n"
            for conf in confirmations:
                text += (
                    f"- {conf['type_name']}\n"
                    f"ID: <code>{conf['id']}</code>\n\n")
        await callback.message.edit_text( # type: ignore
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Подтвердить всё", callback_data=f"confirm_all_{bot_name}")],
                [InlineKeyboardButton(text="Назад", callback_data=f"2fa_{bot_name}")]]))
        await callback.answer(" Все подтверждено", show_alert=True)
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}") # type: ignore

@dp.callback_query(lambda c: c.data and c.data.startswith("farm|"), AdminCallbackFilter())
async def farm_game(callback: CallbackQuery):
    await callback.answer()
    if not callback.data:
        return
    _, bot_name, app_id = callback.data.split("|")
    app_id = int(app_id)
    try:
        # получаем текущий конфиг
        response = requests.get(f"http://127.0.0.1:1242/Api/Bot/{bot_name}", headers={"Authentication": ASF_PASSWORD})
        data = response.json()
        bot_data = data.get("Result", {}).get(bot_name, {})
        config = bot_data.get("BotConfig", {})
        idle_games = config.get("GamesPlayedWhileIdle", [])
        if app_id in idle_games:
            idle_games.remove(app_id)
            action = "Idle выключен"
        else:
            idle_games.append(app_id)
            action = "Idle включен"
        config["GamesPlayedWhileIdle"] = idle_games
        save = requests.post(
            f"http://127.0.0.1:1242/Api/Bot/{bot_name}", headers={"Authentication": ASF_PASSWORD}, json={"BotConfig": config})
        if save.status_code != 200:
            await callback.answer("Ошибка сохранения", show_alert=True)
            return
        asyncio.create_task(reload_bot(bot_name))
        await callback.answer(action, show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=games_keyboard(bot_name, app_id in idle_games)) # type: ignore
        except:
            pass
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith("inventory_"), AdminCallbackFilter())
async def inventory_menu(callback: CallbackQuery):
    await callback.answer()
    bot_name = callback.data.replace("inventory_", "") # type: ignore
    await callback.message.edit_text("Проверка inventory...") # type: ignore
    cs2_inventory = await get_inventory(bot_name, 730, 2)
    steam_inventory = await get_inventory(bot_name, 753, 6)
    cs2_assets = []
    steam_assets = []
    try:
        cs2_assets = (cs2_inventory.get(bot_name, {}).get("Assets", [])) # type: ignore
    except:
        pass
    try:
        steam_assets = (steam_inventory.get(bot_name, {}).get("Assets", [])) # type: ignore
    except:
        pass
    if not cs2_assets and not steam_assets:
        await callback.message.edit_text(f"📦 Инвентарь {bot_name} пуст", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"bot_{bot_name}")]])) # type: ignore
        return
    keyboard = []
    if cs2_assets:
        keyboard.append([InlineKeyboardButton(text=f"CS2 ({len(cs2_assets)})", callback_data=f"inv_cs2_{bot_name}")])
    if steam_assets:
        keyboard.append([InlineKeyboardButton(text=f"Steam ({len(steam_assets)})", callback_data=f"inv_steam_{bot_name}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"bot_{bot_name}")])
    await callback.message.edit_text( # type: ignore
        (
            f"📦 Инвентарь {bot_name}\n\n"
            "🔄 — можно трейдить\n"
            "💰 — можно продавать\n"
            "🔒 — нельзя продавать\n"
            "❌ — нельзя трейдить"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(lambda c: c.data and c.data.startswith("inv_cs2_"), AdminCallbackFilter())
async def cs2_inventory(callback: CallbackQuery):
    await callback.answer()
    bot_name = callback.data.replace("inv_cs2_", "") # type: ignore
    await render_inventory_page(callback, bot_name, "cs2", 730, 2, 0)

@dp.callback_query(lambda c: c.data and c.data.startswith("inv_steam_"), AdminCallbackFilter())
async def steam_inventory(callback: CallbackQuery):
    await callback.answer()
    bot_name = callback.data.replace("inv_steam_", "") # type: ignore
    await render_inventory_page(callback, bot_name, "steam", 753, 6, 0)

@dp.callback_query(lambda c: c.data and c.data.startswith("invpage|"), AdminCallbackFilter())
async def inventory_page(callback: CallbackQuery):
    await callback.answer()
    _, inv_type, bot_name, page = callback.data.split("|") # type: ignore
    page = int(page)
    if inv_type == "cs2":
        await render_inventory_page(callback, bot_name, "cs2", 730, 2, page)
    else:
        await render_inventory_page(callback, bot_name, "steam", 753, 6, page)

@dp.callback_query(lambda c: c.data == "redeem_keys", AdminCallbackFilter())
async def redeem_keys_menu(callback: CallbackQuery):
    await callback.answer()
    redeem_users.add(callback.from_user.id)
    redeem_messages[callback.from_user.id] = callback.message
    await callback.message.edit_text( # type: ignore
        "Отправьте ключ Steam для активации\n\n"
        "Можно отправить сразу несколько ключей.\n\n"
        "Пример:\n"
        "<code>AAAAA-BBBBB-CCCCC\nDDDDD-EEEEE-FFFFF</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back")]]))

@dp.callback_query(lambda c: c.data and c.data.startswith("redeem_bot_"), AdminCallbackFilter())
async def redeem_bot_menu(callback: CallbackQuery):
    await callback.answer()
    bot_name = callback.data.replace("redeem_bot_", "") # type: ignore
    bot_redeem_users[callback.from_user.id] = bot_name
    bot_redeem_messages[callback.from_user.id] = callback.message
    await callback.message.edit_text( # type: ignore
        f"Отправьте ключ Steam для активации на аккаунте:\n"
        f"<code>{bot_name}</code>\n\n"
        f"Можно отправить сразу несколько ключей.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"bot_{bot_name}")]]))

@dp.message(AdminFilter())
async def text_router(message: Message):
    # console mode
    if message.from_user.id in console_users: # type: ignore
        command = message.text.strip() # type: ignore
        try:
            await message.delete()
        except:
            pass
        try:
            response = requests.post("http://127.0.0.1:1242/Api/Command", headers={"Authentication": ASF_PASSWORD}, json={"Command": f"!{command}"})
            if response.status_code != 200:
                text = f"Ошибка HTTP {response.status_code}"
            else:
                data = response.json()
                if not data.get("Success"):
                    text = "Ошибка ASF"
                else:
                    result = html.escape(str(data.get("Result", "Нет ответа")))
                    text = (
                        f"<b>Команда:</b> <code>{command}</code>\n\n"
                        f"<b>Ответ:</b>\n<code>{result}</code>"
                    )
            await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Удалить", callback_data="delete_msg")]]))
        except Exception as e:
            await message.answer(f"Ошибка: {e}")
        return
    # single bot redeem mode
    if message.from_user.id in bot_redeem_users: # type: ignore
        bot_name = bot_redeem_users.pop(message.from_user.id) # type: ignore
        menu_message = bot_redeem_messages.pop(message.from_user.id, None) # type: ignore
        if menu_message:
            try:
                response = requests.get("http://127.0.0.1:1242/Api/Bot/ASF",headers={"Authentication": ASF_PASSWORD})
                data = response.json()
                bot_data = data.get("Result", {}).get(bot_name)
                if bot_data:
                    await menu_message.edit_text(
                        format_bot_ui(bot_data),
                        disable_web_page_preview=True,
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="🔐 2FA", callback_data=f"2fa_{bot_name}")]
                                if bot_data.get("HasMobileAuthenticator") else [],
                                [InlineKeyboardButton(text="⌚ Накрутка часов", callback_data=f"games_{bot_name}")],
                                [InlineKeyboardButton(text="🔑 Активировать ключ", callback_data=f"redeem_bot_{bot_name}")],
                                [InlineKeyboardButton(text="📦 Инвентарь", callback_data=f"inventory_{bot_name}")],
                                [InlineKeyboardButton(text="🔙 Назад", callback_data="bots")]]))
            except:
                pass
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except:
            pass
        raw_text = message.text.upper() # type: ignore
        keys = re.findall(r"[A-Z0-9]{5}(?:-[A-Z0-9]{5}){2}", raw_text)
        keys = list(dict.fromkeys(keys))
        if not keys:
            await message.answer("Ключи не найдены")
            return
        checking = await message.answer(
            f"Аккаунт: <code>{bot_name}</code>\n"
            f"Найдено ключей: {len(keys)}\n"
            f"Начинаю активацию...")
        success_count = 0
        failed_count = 0
        results = []
        for key in keys:
            success, result = await redeem_key(bot_name, key)
            await asyncio.sleep(2)
            if not success or not result:
                failed_count += 1
                results.append(f"❌ {key}: ASF ERROR")
                continue
            result_lower = result.lower()
            if "ok/nodetail" in result_lower or "ok/" in result_lower:
                success_count += 1
                results.append(f"✅ {key}: активировано")
            elif "ratelimited" in result_lower:
                failed_count += 1
                results.append(f"⏳ {key}: rate limit")
            elif "alreadypurchased" in result_lower:
                failed_count += 1
                results.append(f"⚠️ {key}: игра уже есть")
            elif "duplicateactivationcode" in result_lower:
                failed_count += 1
                results.append(f"❌ {key}: ключ уже использован")
            elif "regionlocked" in result_lower:
                failed_count += 1
                results.append(f"🌍 {key}: регион лок")
            elif "invalidactivationcode" in result_lower or "invalid" in result_lower:
                failed_count += 1
                results.append(f"❌ {key}: неверный ключ")
            else:
                failed_count += 1
                results.append(f"❔ {key}: неизвестный ответ")
        text = (
            f"Результат активации для <code>{bot_name}</code>\n\n"
            f"✅ Успешно: {success_count}\n"
            f"❌ Ошибок: {failed_count}\n\n"
            + "\n".join(results[:50]))
        if len(text) > 4000:
            text = text[:4000] + "\n\n...обрезано"
        await checking.edit_text(text)
        return
    if message.from_user.id in redeem_users: # type: ignore
        redeem_users.discard(message.from_user.id) # type: ignore
        menu_message = redeem_messages.pop(message.from_user.id, None) # type: ignore
        if menu_message:
            try:
                await menu_message.edit_text(get_asf_status_text(), reply_markup=main_keyboard())
            except:
                pass
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except:
            pass
        raw_text = message.text.upper() # type: ignore
        keys = re.findall(r"[A-Z0-9]{5}(?:-[A-Z0-9]{5}){2}", raw_text)
        keys = list(dict.fromkeys(keys))
        if not keys:
            await message.answer("Ключи не найдены")
            return
        checking = await message.answer(f"Найдено ключей: {len(keys)}\nНачинаю активацию...")
        try:
            response = asf_get("/Api/Bot/ASF")
            data = response.json()
            bots = list(data.get("Result", {}).keys())
            success_count = 0
            failed_count = 0
            results = []
            for key in keys:
                activated = False
                key_report = []
                for bot_name in bots:
                    success, result = await redeem_key(bot_name, key)
                    await asyncio.sleep(2)
                    if not success or not result:
                        key_report.append(f"❌ {bot_name}: ASF ERROR")
                        continue
                    print(result)
                    result_lower = result.lower()
                    bot_line = ""
                    for line in result.splitlines():
                        if f"<{bot_name.lower()}>" in line.lower():
                            bot_line = line
                            break
                    if bot_line:
                        parsed = bot_line.lower()
                    else:
                        parsed = result_lower
                    if "ok/nodetail" in parsed or "ok/" in parsed:
                        key_report.append(f"✅ {bot_name}: активировано")
                        success_count += 1
                        activated = True
                        break
                    elif "ratelimited" in parsed:
                        key_report.append(f"⏳ {bot_name}: rate limit")
                        continue
                    elif "alreadypurchased" in parsed or "already purchased" in parsed:
                        key_report.append(f"⚠️ {bot_name}: игра уже есть")
                        continue
                    elif "duplicateactivationcode" in parsed:
                        key_report.append(f"❌ {bot_name}: ключ уже использован")
                        break
                    elif "regionlocked" in parsed:
                        key_report.append(f"🌍 {bot_name}: регион лок")
                        continue
                    elif "invalidactivationcode" in parsed or "invalid" in parsed:
                        key_report.append(f"❌ {bot_name}: неверный ключ")
                        break
                    else:
                        key_report.append(f"❔ {bot_name}: неизвестный ответ")
                        continue
                if not activated:
                    failed_count += 1
                results.append(f"\n🔑 {key}\n" + "\n".join(key_report))
            text = (
                f"Результат активации\n\n"
                f"✅ Успешно: {success_count}\n"
                f"❌ Ошибок: {failed_count}\n\n"
                + "\n".join(results[:50]))
            if len(text) > 4000:
                text = text[:4000] + "\n\n...обрезано"
            await checking.edit_text(text)

        except Exception as e:
            await checking.edit_text(f"Ошибка: {e}")
        return

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
