import logging
import re
import requests
import uuid
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
import os
from dotenv import load_dotenv
from skins import CATEGORIES, SUBCATEGORIES

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
API_URL = os.getenv('API_URL')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set")
    exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

player_cache = {}

@dp.message(Command("start"))
async def start_command(message: types.Message) -> None:
    try:
        await message.answer(
            "Привет! Отправь мне UID или ID игрока, и я покажу его статистику.\n\n"
            "UID - это 6 цифр (например: 175609)\n"
            "ID - это длинный хэш (например: 687fee95aaa6ecf2b9198bc3)"
        )
    except Exception as e:
        logger.error(f"Error in start_command: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")

@dp.message(F.text)
async def get_player_data(message: types.Message) -> None:
    try:
        text = message.text.strip()

        if is_uid(text):
            endpoint = f"{API_URL}/getUserByUid"
            payload = {"Uid": text}
        elif is_id(text):
            endpoint = f"{API_URL}/getUserById"
            payload = {"userId": text}
        else:
            if len(text) < 24:
                endpoint = f"{API_URL}/getUserByUid"
                payload = {"Uid": text}
            else:
                await message.answer(
                    "❌ Неверный формат. Введите:\n"
                    "- UID (6 цифр) или\n"
                    "- ID (24 символа)"
                )
                return
        
        msg = await message.answer("🔄 Запрашиваю данные...")
        
        response = requests.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            verify=False
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                if not data.get("success"):
                    await msg.edit_text("❌ Сервер вернул ошибку")
                    return
                
                if data.get("Data") is None:
                    await msg.edit_text("❌ Игрок не найден")
                    return
                
                player = data["Data"]
                player_cache[player['_id']] = player
                
                message_text = format_player_info(player)

                message_parts = []
                current_part = ""
                for line in message_text.split("\n"):
                    if len(current_part) + len(line) < 4000:
                        current_part += line + "\n"
                    else:
                        message_parts.append(current_part)
                        current_part = line + "\n"
                if current_part:
                    message_parts.append(current_part)
                
                keyboard = InlineKeyboardBuilder()
                keyboard.add(InlineKeyboardButton(text="🎒 Инвентарь", callback_data=f"inventory_{player['_id']}"))

                if message_parts:
                    await msg.edit_text(message_parts[0], parse_mode=ParseMode.HTML, reply_markup=keyboard.as_markup())

                    for part in message_parts[1:]:
                        await message.answer(part, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Error parsing response: {e}", exc_info=True)
                await msg.edit_text("❌ Проверьте правильность введенных данных")
        else:
            await msg.edit_text(f"❌ Ошибка API: {response.status_code}")

    except Exception as e:
        logger.error(f"Error in get_player_data: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке запроса")

@dp.callback_query(F.data.startswith("inventory_"))
async def inventory_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    try:
        player_id = query.data.split('_')[1]
        
        player = player_cache.get(player_id)
        if not player:
            logger.warning(f"Player not found in cache for ID: {player_id}")
            await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
            return
        
        inventory = player.get("Inventory", {}).get("Items", [])

        inventory_list = []
        for i, item in enumerate(inventory[:100], 1):
            item_name = item.get('Name', 'N/A')
            stattrack = "✓" if item.get("StatTrack", {}).get("IsEnable", False) else "✗"
            inventory_list.append(f"{i}. {item_name} (ST: {stattrack})")
        
        inventory_text = '\n'.join(inventory_list) if inventory_list else "Инвентарь пуст"
        message = f"<b>🎒 Инвентарь ({len(inventory)} предметов):</b>\n{inventory_text}" + \
                 ("\n..." if len(inventory) > 100 else "")

        keyboard = InlineKeyboardBuilder()
        keyboard.row(InlineKeyboardButton(text="➕ Добавить предмет", callback_data=f"add_item_{player_id}"))
        keyboard.row(InlineKeyboardButton(text="➖ Удалить предмет", callback_data=f"remove_item_{player_id}"))
        keyboard.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_main_{player_id}"))
        
        await query.message.edit_text(message, parse_mode=ParseMode.HTML, reply_markup=keyboard.as_markup())
        
    except Exception as e:
        logger.error(f"Error in inventory_callback: {e}", exc_info=True)
        await query.message.edit_text("❌ Произошла ошибка при отображении инвентаря")

@dp.callback_query(F.data.startswith("back_main_"))
async def back_main_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    player_id = query.data.split('_')[2]

    player = player_cache.get(player_id)
    if not player:
        await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
        return
    
    message_text = format_player_info(player)

    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🎒 Инвентарь", callback_data=f"inventory_{player_id}"))
    
    await query.message.edit_text(message_text, parse_mode=ParseMode.HTML, reply_markup=keyboard.as_markup())

@dp.callback_query(F.data.startswith("remove_item_"))
async def remove_item_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    player_id = query.data.split('_')[2]
    
    player = player_cache.get(player_id)
    if not player:
        await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
        return
    
    inventory = player.get("Inventory", {}).get("Items", [])
    
    if not inventory:
        await query.message.edit_text("❌ Инвентарь пуст")
        return

    builder = InlineKeyboardBuilder()
    items_per_page = 50
    
    for i, item in enumerate(inventory[:items_per_page]):
        item_name = item.get('Name', 'N/A')
        if len(item_name) > 25:
            item_name = item_name[:22] + "..."
        item_uid = str(item.get('uid', ''))
        builder.add(InlineKeyboardButton(text=f"{i+1}. {item_name}", callback_data=f"confirm_{item_uid}_{player_id}"))

    builder.adjust(1)
    
    if len(inventory) > items_per_page:
        builder.row(
            InlineKeyboardButton(text="➡️ Вперед", callback_data=f"remove_next_page_{player_id}_1")
        )
    
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"inventory_{player_id}"))
    
    await query.message.edit_text("Выберите предмет для удаления:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("remove_next_page_"))
async def remove_next_page_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    player_id = data[3]
    current_page = int(data[4])
    
    player = player_cache.get(player_id)
    if not player:
        await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
        return
    
    inventory = player.get("Inventory", {}).get("Items", [])
    items_per_page = 50
    start_index = current_page * items_per_page
    end_index = (current_page + 1) * items_per_page
    
    builder = InlineKeyboardBuilder()
    
    for i, item in enumerate(inventory[start_index:end_index], start=start_index + 1):
        item_name = item.get('Name', 'N/A')
        if len(item_name) > 25:
            item_name = item_name[:22] + "..."
        item_uid = str(item.get('uid', ''))
        builder.add(InlineKeyboardButton(text=f"{i}. {item_name}", callback_data=f"confirm_{item_uid}_{player_id}"))

    builder.adjust(1)
    
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"remove_prev_page_{player_id}_{current_page-1}"))
    if len(inventory) > end_index:
        nav_buttons.append(InlineKeyboardButton(text="➡️ Вперед", callback_data=f"remove_next_page_{player_id}_{current_page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"inventory_{player_id}"))
    
    await query.message.edit_text("Выберите предмет для удаления:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("remove_prev_page_"))
async def remove_prev_page_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    player_id = data[3]
    current_page = int(data[4])
    
    player = player_cache.get(player_id)
    if not player:
        await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
        return
    
    inventory = player.get("Inventory", {}).get("Items", [])
    items_per_page = 50
    start_index = current_page * items_per_page
    end_index = (current_page + 1) * items_per_page
    
    builder = InlineKeyboardBuilder()
    
    for i, item in enumerate(inventory[start_index:end_index], start=start_index + 1):
        item_name = item.get('Name', 'N/A')
        if len(item_name) > 25:
            item_name = item_name[:22] + "..."
        item_uid = str(item.get('uid', ''))
        builder.add(InlineKeyboardButton(text=f"{i}. {item_name}", callback_data=f"confirm_{item_uid}_{player_id}"))

    builder.adjust(1)
    
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"remove_prev_page_{player_id}_{current_page-1}"))
    if len(inventory) > end_index:
        nav_buttons.append(InlineKeyboardButton(text="➡️ Вперед", callback_data=f"remove_next_page_{player_id}_{current_page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"inventory_{player_id}"))
    
    await query.message.edit_text("Выберите предмет для удаления:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_remove_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    item_uid = data[1]
    player_id = data[2]
    
    player = player_cache.get(player_id)
    if not player:
        await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
        return
    
    item = next((i for i in player.get("Inventory", {}).get("Items", []) if i.get("uid") == item_uid), None)
    if not item:
        await query.message.edit_text("❌ Предмет не найден в инвентаре")
        return
    
    item_name = item.get('Name', 'N/A')
    
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"do_remove_{item_uid}_{player_id}"))
    keyboard.row(InlineKeyboardButton(text="❌ Нет, отменить", callback_data=f"remove_item_{player_id}"))
    
    await query.message.edit_text(
        f"Вы уверены, что хотите удалить предмет:\n{item_name}?",
        reply_markup=keyboard.as_markup()
    )

@dp.callback_query(F.data.startswith("do_remove_"))
async def do_remove_item_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    item_uid = data[2]
    player_id = data[3]

    player = player_cache.get(player_id)
    if not player:
        await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
        return
    
    if not player.get("Inventory") or not player.get("Inventory", {}).get("Items"):
        await query.message.edit_text("❌ Инвентарь игрока пуст или не найден.")
        return
    
    item = next((i for i in player["Inventory"]["Items"] if i.get("uid") == item_uid), None)
    if not item:
        await query.message.edit_text("❌ Предмет не найден в инвентаре.")
        return
    
    stattrack_data = item.get("StatTrack", {}) or item.get("Stattrack", {})
    payload = {
        "userId": player_id,
        "Item": {
            "Name": item.get("Name", ""),
            "uid": item_uid,
            "StatTrack": {
                "IsEnable": stattrack_data.get("IsEnable", False),
                "Kills": 0
            },
            "isEquip": False,
            "isNew": True
        }
    }
    
    response = requests.post(
        f"{API_URL}/removeInventoryItem",
        json=payload,
        headers={"Content-Type": "application/json"},
        verify=False
    )
    
    if response.status_code == 200 and response.json().get("success"):
        if player_id in player_cache:
            player_cache[player_id]["Inventory"]["Items"] = [
                item for item in player_cache[player_id]["Inventory"]["Items"] 
                if item.get("uid") != item_uid
            ]
        
        await query.message.edit_text("✅ Предмет успешно удален из инвентаря!")
    else:
        error_msg = f"❌ Ошибка при удалении предмета: {response.status_code}"
        error_details = response.json().get("message", "")
        if error_details:
            error_msg += f"\n{error_details}"
        await query.message.edit_text(error_msg)

@dp.callback_query(F.data.startswith("add_item_"))
async def add_item_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    player_id = query.data.split('_')[2]
    
    builder = InlineKeyboardBuilder()
    for key, name in CATEGORIES.items():
        builder.add(InlineKeyboardButton(text=name, callback_data=f"category_{key}_{player_id}"))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"inventory_{player_id}"))
    
    await query.message.edit_text("Выберите категорию предмета:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("category_"))
async def category_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    category = data[1]
    player_id = data[2]
    
    items = SUBCATEGORIES.get(category, {})
        
    if category in ["weapon", "knife", "medal"]:
        builder = InlineKeyboardBuilder()
        for subcategory in items.keys():
            builder.add(InlineKeyboardButton(text=subcategory, callback_data=f"subcategory_{subcategory}_{player_id}"))
    else:
        builder = InlineKeyboardBuilder()
        for item in items:
            display_name = format_item_name(item, category)
            builder.add(InlineKeyboardButton(text=display_name, callback_data=f"item_{item}_{player_id}"))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"add_item_{player_id}"))
    
    await query.message.edit_text(f"Выберите подкатегорию для {CATEGORIES[category]}:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("subcategory_"))
async def subcategory_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    subcategory = data[1]
    player_id = data[2]
    
    category = data[0].split('_')[0]
    
    items = SUBCATEGORIES.get(category, {}).get(subcategory, [])
    
    builder = InlineKeyboardBuilder()
    for item in items:
        display_name = format_item_name(item, category)
        builder.add(InlineKeyboardButton(text=display_name, callback_data=f"item_{item}_{player_id}"))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"category_{category}_{player_id}"))
    
    await query.message.edit_text(f"Выберите предмет из категории {subcategory}:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("item_"))
async def item_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    item_name = '_'.join(data[1:-1])
    player_id = data[-1]
    category = data[0].split('_')[0]
    
    if category == "weapon":
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="Да", callback_data=f"stattrack_yes_{item_name}_{player_id}"))
        builder.row(InlineKeyboardButton(text="Нет", callback_data=f"stattrack_no_{item_name}_{player_id}"))
        
        display_name = format_item_name(item_name, category)
        await query.message.edit_text(f"Добавить StatTrack для {display_name}?", reply_markup=builder.as_markup())
    elif category == "medal":
        medal_type = None
        if "service_medal2023" in item_name:
            medal_type = "season1"
        elif "service_medal2020" in item_name:
            medal_type = "season2"
        elif "breakout" in item_name:
            medal_type = "breakout"
        elif "mechanical" in item_name:
            medal_type = "mechanical"
        
        if medal_type:
            level = int(item_name.split('_')[-1].replace('lvl', ''))
            await update_medal_stats(player_id, medal_type, level, query)
        else:
            await add_item_to_inventory(player_id, item_name, False, query)
    else:
        await add_item_to_inventory(player_id, item_name, False, query)

@dp.callback_query(F.data.startswith("stattrack_"))
async def stattrack_callback(query: CallbackQuery) -> None:
    await query.answer()
    
    data = query.data.split('_')
    choice = data[1]
    is_stat = (choice == "yes")
    item_name = '_'.join(data[2:-1])
    player_id = data[-1]
    
    if player_id and item_name:
        await add_item_to_inventory(player_id, item_name, is_stat, query)
    else:
        await query.message.edit_text("❌ Ошибка: данные не найдены")

async def update_medal_stats(player_id: str, medal_type: str, level: int, query: CallbackQuery):
    player = player_cache.get(player_id)
    if not player:
        await query.message.edit_text("❌ Данные игрока устарели. Запросите информацию снова.")
        return
    
    stats = player.get("PlayerStatistics", {})
    
    stats_payload = {
        "BotsKilled": stats.get("BotsKilled", 0),
        "BotsEarned": stats.get("BotsEarned", 0),
        "SellEarned": stats.get("SellEarned", 0),
        "TimeInGame": stats.get("TimeInGame", 0),
        "Kills": stats.get("Kills", 0),
        "Deaths": stats.get("Deaths", 0),
        "Matches": stats.get("Matches", 0),
        "Damage": stats.get("Damage", 0),
        "exp": stats.get("exp", 0),
        "MedalLevel": stats.get("MedalLevel", 0),
        "MedalLevelSeason2": stats.get("MedalLevelSeason2", 0),
        "BreakoutMedalLevel": stats.get("BreakoutMedalLevel", 0),
        "FlameMechanicalMedalLevel": stats.get("FlameMechanicalMedalLevel", 0),
        "DuelStatistic": stats.get("DuelStatistic", {})
    }
    
    if medal_type == "season1":
        stats_payload["MedalLevel"] = level
    elif medal_type == "season2":
        stats_payload["MedalLevelSeason2"] = level
    elif medal_type == "breakout":
        stats_payload["BreakoutMedalLevel"] = level
    elif medal_type == "mechanical":
        stats_payload["FlameMechanicalMedalLevel"] = level
    
    payload = {
        "userId": player_id,
        "statistics": stats_payload
    }
    
    response = requests.post(
        f"{API_URL}/updateUserStatistics",
        json=payload,
        headers={"Content-Type": "application/json"},
        verify=False
    )
    
    if response.status_code == 200 and response.json().get("success"):
        player["PlayerStatistics"] = stats_payload
        player_cache[player_id] = player
        await query.message.edit_text("✅ Уровень медали успешно обновлен!")
    else:
        error_msg = f"❌ Ошибка при обновлении статистики: {response.status_code}"
        error_details = response.json().get("message", "")
        if error_details:
            error_msg += f"\n{error_details}"
        await query.message.edit_text(error_msg)

async def add_item_to_inventory(player_id: str, item_name: str, is_stat: bool, query: CallbackQuery):
    item_uid = str(uuid.uuid4())

    payload = {
        "userId": player_id,
        "Item": {
            "Name": item_name,
            "uid": item_uid,
            "StatTrack": {
                "IsEnable": is_stat,
                "Kills": 0
            },
            "isEquip": False,
            "isNew": True
        }
    }
    
    response = requests.post(
        f"{API_URL}/addInventoryItem",
        json=payload,
        headers={"Content-Type": "application/json"},
        verify=False
    )
    
    if response.status_code == 200 and response.json().get("success"):
        if player_id in player_cache:
            if "Inventory" not in player_cache[player_id]:
                player_cache[player_id]["Inventory"] = {"Items": []}
            player_cache[player_id]["Inventory"]["Items"].append({
                "Name": item_name,
                "uid": item_uid,
                "StatTrack": {
                    "IsEnable": is_stat,
                    "Kills": 0
                },
                "isEquip": False,
                "isNew": True
            })
        
        display_name = ' '.join(word.capitalize() for word in item_name.split('_')[1:])
        await query.message.edit_text(f"✅ Предмет {display_name} успешно добавлен в инвентарь!")
    else:
        error_msg = f"❌ Ошибка при добавлении предмета: {response.json()}"
        error_details = response.json().get("message", "")
        if error_details:
            error_msg += f"\n{error_details}"
        await query.message.edit_text(error_msg)

async def error_handler(update: types.Update, exception: Exception) -> None:
    logger.error("Exception while handling update:", exc_info=exception)
    if update.callback_query:
        await update.callback_query.message.answer("❌ Произошла ошибка при обработке запроса")
    elif update.message:
        await update.message.answer("❌ Произошла ошибка при обработке запроса")

async def main() -> None:
    try:
        dp.errors.register(error_handler)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
        exit(1)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())