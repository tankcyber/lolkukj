#!/usr/bin/env python3
# Country Bot - Political RPG for Telegram (single file)

import asyncio, logging, sys, time, re, os, random
from datetime import datetime
import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = "8751175922:AAFQz3Cqelelj871SoiH99ljL7aLv4iaOGs"  # <-- ВСТАВЬТЕ СВОЙ ТОКЕН СЮДА
ADMIN_IDS = [5439940299]

START_GOLD = 1000
START_POPULATION = 0
START_CURRENCY_VALUE = 1.0

INCOME_INTERVAL = 3600
MINE_BASE_INCOME = 80
FARM_BASE_INCOME = 40
MINE_COST = 300
FARM_COST = 200

ARMY_LEVEL_COST = 500
DEFENSE_COST = 350
RECRUIT_COST = 15
UNIT_PRODUCE_COST = 500

ATTACK_COST = 200
ATTACK_COOLDOWN = 300

CRYSTAL_TO_GOLD = 100
ALLIANCE_CREATE_COST = 1000

CITIZEN_TAX_RATE = 0.05
CITIZEN_WORK_GOLD = 50
CITIZEN_MAX_PER_COUNTRY = 50

CURRENCY_TRADE_FEE = 0.02
CURRENCY_FLUCTUATION_MAX = 0.05


DB_PATH = os.path.join(os.path.dirname(__file__), "game.db")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS countries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            name TEXT UNIQUE NOT NULL,
            leader_title TEXT NOT NULL DEFAULT 'Президент',
            gold INTEGER NOT NULL DEFAULT 1000,
            crystals INTEGER NOT NULL DEFAULT 0,
            population INTEGER NOT NULL DEFAULT 0,
            mine_level INTEGER NOT NULL DEFAULT 1,
            farm_level INTEGER NOT NULL DEFAULT 1,
            regions INTEGER NOT NULL DEFAULT 1,
            army_level INTEGER NOT NULL DEFAULT 1,
            defense_level INTEGER NOT NULL DEFAULT 1,
            currency_name TEXT NOT NULL DEFAULT 'Кредит',
            currency_code TEXT NOT NULL DEFAULT 'CRD',
            currency_value REAL NOT NULL DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_collect TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_attack TIMESTAMP DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            wars_won INTEGER DEFAULT 0,
            wars_lost INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS military_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            unit_type TEXT NOT NULL,
            name TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            cost_gold INTEGER NOT NULL DEFAULT 500,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (country_id) REFERENCES countries(id)
        );

        CREATE TABLE IF NOT EXISTS citizens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            country_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'citizen',
            gold INTEGER NOT NULL DEFAULT 200,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, country_id),
            FOREIGN KEY (country_id) REFERENCES countries(id)
        );

        CREATE TABLE IF NOT EXISTS currency_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            target_code TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            UNIQUE(country_id, target_code),
            FOREIGN KEY (country_id) REFERENCES countries(id)
        );

        CREATE TABLE IF NOT EXISTS alliances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            tag TEXT UNIQUE NOT NULL,
            owner_id INTEGER NOT NULL,
            level INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES countries(id)
        );

        CREATE TABLE IF NOT EXISTS alliance_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alliance_id INTEGER NOT NULL,
            country_id INTEGER NOT NULL UNIQUE,
            role TEXT DEFAULT 'member',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (alliance_id) REFERENCES alliances(id),
            FOREIGN KEY (country_id) REFERENCES countries(id)
        );

        CREATE TABLE IF NOT EXISTS wars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attacker_id INTEGER NOT NULL,
            defender_id INTEGER NOT NULL,
            status TEXT DEFAULT 'finished',
            winner_id INTEGER,
            gold_stolen INTEGER DEFAULT 0,
            regions_stolen INTEGER DEFAULT 0,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (attacker_id) REFERENCES countries(id),
            FOREIGN KEY (defender_id) REFERENCES countries(id)
        );
        """)
        await db.commit()
    finally:
        await db.close()


async def register_country(user_id: int, name: str, leader: str, cur_name: str, cur_code: str) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO countries (user_id, name, leader_title, currency_name, currency_code) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, leader, cur_name, cur_code)
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
    finally:
        await db.close()


async def update_country(user_id: int, **kwargs):
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [user_id]
        await db.execute(f"UPDATE countries SET {sets} WHERE user_id = ?", vals)
        await db.commit()
    finally:
        await db.close()


async def get_country(user_id: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM countries WHERE user_id = ?", (user_id,))
        return await cur.fetchone()
    finally:
        await db.close()


async def get_country_by_id(cid: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM countries WHERE id = ?", (cid,))
        return await cur.fetchone()
    finally:
        await db.close()


async def get_country_by_name(name: str):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM countries WHERE name LIKE ?", (name,))
        return await cur.fetchone()
    finally:
        await db.close()


async def get_all_countries(order_by: str = "gold DESC", limit: int = 20):
    db = await get_db()
    try:
        allowed = {"gold", "army_level", "regions", "wars_won", "total_earned", "population", "currency_value"}
        col = order_by.split()[0]
        if col not in allowed:
            col = "gold"
        cur = await db.execute(
            f"SELECT * FROM countries ORDER BY {col} DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def get_all_countries_full(limit: int = 200):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM countries ORDER BY gold DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    finally:
        await db.close()


# ===== MILITARY UNITS =====

async def create_unit(country_id: int, unit_type: str, name: str, cost: int) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO military_units (country_id, unit_type, name, count, cost_gold) VALUES (?, ?, ?, 0, ?)",
            (country_id, unit_type, name, cost)
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
    finally:
        await db.close()


async def get_units(country_id: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM military_units WHERE country_id = ?", (country_id,))
        return await cur.fetchall()
    finally:
        await db.close()


async def get_unit(unit_id: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM military_units WHERE id = ?", (unit_id,))
        return await cur.fetchone()
    finally:
        await db.close()


async def update_unit(unit_id: int, **kwargs):
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [unit_id]
        await db.execute(f"UPDATE military_units SET {sets} WHERE id = ?", vals)
        await db.commit()
    finally:
        await db.close()


async def delete_unit(unit_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM military_units WHERE id = ?", (unit_id,))
        await db.commit()
    finally:
        await db.close()


# ===== CITIZENS =====

async def register_citizen(user_id: int, username: str, country_id: int) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO citizens (user_id, username, country_id) VALUES (?, ?, ?)",
            (user_id, username, country_id)
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
    finally:
        await db.close()


async def get_citizen(user_id: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM citizens WHERE user_id = ?", (user_id,))
        return await cur.fetchone()
    finally:
        await db.close()


async def get_citizens_of(country_id: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM citizens WHERE country_id = ?", (country_id,))
        return await cur.fetchall()
    finally:
        await db.close()


async def leave_citizen(user_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM citizens WHERE user_id = ?", (user_id,))
        await db.commit()
    finally:
        await db.close()


async def kick_citizen(user_id: int, country_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM citizens WHERE user_id = ? AND country_id = ?", (user_id, country_id))
        await db.commit()
    finally:
        await db.close()


async def set_citizen_role(user_id: int, country_id: int, role: str):
    db = await get_db()
    try:
        await db.execute("UPDATE citizens SET role = ? WHERE user_id = ? AND country_id = ?", (role, user_id, country_id))
        await db.commit()
    finally:
        await db.close()


async def update_citizen_gold(user_id: int, gold: int):
    db = await get_db()
    try:
        await db.execute("UPDATE citizens SET gold = ? WHERE user_id = ?", (gold, user_id))
        await db.commit()
    finally:
        await db.close()


async def get_citizen_count(country_id: int) -> int:
    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) as cnt FROM citizens WHERE country_id = ?", (country_id,))
        row = await cur.fetchone()
        return row["cnt"] if row else 0
    finally:
        await db.close()


# ===== CURRENCY HOLDINGS =====

async def get_holdings(country_id: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM currency_holdings WHERE country_id = ?", (country_id,))
        return await cur.fetchall()
    finally:
        await db.close()


async def get_holding(country_id: int, target_code: str):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM currency_holdings WHERE country_id = ? AND target_code = ?", (country_id, target_code))
        return await cur.fetchone()
    finally:
        await db.close()


async def add_holding(country_id: int, target_code: str, amount: float):
    db = await get_db()
    try:
        cur = await db.execute("SELECT amount FROM currency_holdings WHERE country_id = ? AND target_code = ?", (country_id, target_code))
        row = await cur.fetchone()
        if row:
            new_amt = row["amount"] + amount
            await db.execute("UPDATE currency_holdings SET amount = ? WHERE country_id = ? AND target_code = ?", (new_amt, country_id, target_code))
        else:
            await db.execute("INSERT INTO currency_holdings (country_id, target_code, amount) VALUES (?, ?, ?)", (country_id, target_code, amount))
        await db.commit()
    finally:
        await db.close()


async def remove_holding(country_id: int, target_code: str, amount: float):
    db = await get_db()
    try:
        cur = await db.execute("SELECT amount FROM currency_holdings WHERE country_id = ? AND target_code = ?", (country_id, target_code))
        row = await cur.fetchone()
        if row:
            new_amt = row["amount"] - amount
            if new_amt <= 0:
                await db.execute("DELETE FROM currency_holdings WHERE country_id = ? AND target_code = ?", (country_id, target_code))
            else:
                await db.execute("UPDATE currency_holdings SET amount = ? WHERE country_id = ? AND target_code = ?", (new_amt, country_id, target_code))
        await db.commit()
    finally:
        await db.close()


# ===== ALLIANCES (unchanged) =====

async def create_alliance(name: str, tag: str, owner_id: int) -> bool:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO alliances (name, tag, owner_id) VALUES (?, ?, ?)",
            (name, tag, owner_id)
        )
        aid = cur.lastrowid
        await db.execute(
            "INSERT INTO alliance_members (alliance_id, country_id, role) VALUES (?, ?, 'owner')",
            (aid, owner_id)
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
    finally:
        await db.close()


async def get_alliance(aid: int):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM alliances WHERE id = ?", (aid,))
        return await cur.fetchone()
    finally:
        await db.close()


async def get_alliance_by_country(cid: int):
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT a.* FROM alliances a
            JOIN alliance_members m ON a.id = m.alliance_id
            WHERE m.country_id = ?
        """, (cid,))
        return await cur.fetchone()
    finally:
        await db.close()


async def get_alliance_members(aid: int):
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT c.*, m.role FROM alliance_members m
            JOIN countries c ON c.id = m.country_id
            WHERE m.alliance_id = ?
        """, (aid,))
        return await cur.fetchall()
    finally:
        await db.close()


async def get_alliances_list():
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT a.*, (SELECT COUNT(*) FROM alliance_members m WHERE m.alliance_id = a.id) as members
            FROM alliances a ORDER BY members DESC
        """)
        return await cur.fetchall()
    finally:
        await db.close()


async def join_alliance(alliance_id: int, country_id: int) -> bool:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO alliance_members (alliance_id, country_id) VALUES (?, ?)",
            (alliance_id, country_id)
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
    finally:
        await db.close()


async def leave_alliance(country_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM alliance_members WHERE country_id = ?", (country_id,))
        await db.commit()
    finally:
        await db.close()


async def disband_alliance(aid: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM alliance_members WHERE alliance_id = ?", (aid,))
        await db.execute("DELETE FROM alliances WHERE id = ?", (aid,))
        await db.commit()
    finally:
        await db.close()


async def is_in_alliance(country_id: int) -> bool:
    db = await get_db()
    try:
        cur = await db.execute("SELECT 1 FROM alliance_members WHERE country_id = ?", (country_id,))
        return await cur.fetchone() is not None
    finally:
        await db.close()


async def log_war(atk_id: int, def_id: int, winner_id: int, gold: int, regions: int):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO wars (attacker_id, defender_id, winner_id, gold_stolen, regions_stolen) VALUES (?, ?, ?, ?, ?)",
            (atk_id, def_id, winner_id, gold, regions)
        )
        await db.commit()
    finally:
        await db.close()


async def get_war_history(cid: int, limit: int = 10):
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT * FROM wars
            WHERE attacker_id = ? OR defender_id = ?
            ORDER BY started_at DESC LIMIT ?
        """, (cid, cid, limit))
        return await cur.fetchall()
    finally:
        await db.close()



def parse_time(val):
    if val is None:
        return 0
    try:
        return float(val)
    except (ValueError, TypeError):
        pass
    try:
        dt = datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0


def calc_income(country, citizen_count=0):
    regions = country.get("regions", 1)
    mine_lvl = country.get("mine_level", 1)
    farm_lvl = country.get("farm_level", 1)
    region_income = regions * 40
    mine_income = mine_lvl * config.MINE_BASE_INCOME
    farm_income = farm_lvl * config.FARM_BASE_INCOME
    citizen_tax = citizen_count * 10
    total = region_income + mine_income + farm_income + citizen_tax
    return {
        "total": total,
        "region": region_income,
        "mine": mine_income,
        "farm": farm_income,
        "citizen_tax": citizen_tax,
        "per_hour": total,
    }


def calc_collectable(country, citizen_count=0):
    now = time.time()
    last = parse_time(country.get("last_collect", 0))
    elapsed = now - last
    if elapsed <= 0:
        return 0
    income = calc_income(country, citizen_count)
    rate = income["per_hour"] / 3600
    earned = int(rate * elapsed)
    return min(earned, income["per_hour"] * 24)


def calc_mine_cost(level: int) -> int:
    return config.MINE_COST * level


def calc_farm_cost(level: int) -> int:
    return config.FARM_COST * level


def calc_defense_cost(level: int) -> int:
    return config.DEFENSE_COST * level


def calc_army_level_cost(level: int) -> int:
    return config.ARMY_LEVEL_COST * level


def calc_currency_value(country, citizen_count=0, units=None):
    base = 1.0
    income = calc_income(country, citizen_count)
    gdp_bonus = min(income["per_hour"] / 2000, 0.5)
    unit_power = 0
    if units:
        for u in units:
            unit_power += u["count"] * 2
    military_bonus = min(unit_power / 5000, 0.3)
    pop_bonus = min(citizen_count / 20, 0.2)
    val = base + gdp_bonus + military_bonus + pop_bonus
    val += random.uniform(-config.CURRENCY_FLUCTUATION_MAX, config.CURRENCY_FLUCTUATION_MAX)
    return round(max(0.1, val), 4)


def calc_battle(attacker, defender, atk_bonus=1.0, def_bonus=1.0, atk_units=None, def_units=None):
    atk_power = calc_power(attacker, atk_units) * random.uniform(0.98, 1.02) * atk_bonus
    def_power = calc_power(defender, def_units) * random.uniform(0.98, 1.02) * 1.15 * def_bonus
    if atk_units:
        for u in atk_units:
            atk_power += u["count"] * 5
    if def_units:
        for u in def_units:
            def_power += u["count"] * 5

    if atk_power > def_power:
        ratio = def_power / atk_power if atk_power > 0 else 0
        atk_loss = int(attacker["army_level"] * 10 * (1 + ratio))
        def_loss = int(defender["defense_level"] * 15 * (2 - ratio))
        gold_stolen = int(defender["gold"] * 0.15)
        gold_stolen = min(gold_stolen, attacker["gold"] * 2)
        regions_stolen = 1 if defender["regions"] > 1 else 0
        return {
            "winner": "attacker",
            "atk_loss": min(atk_loss, max(1, attacker["army_level"] * 5)),
            "def_loss": min(def_loss, max(1, defender["defense_level"] * 5)),
            "gold_stolen": max(0, gold_stolen),
            "regions_stolen": regions_stolen,
        }
    else:
        ratio = atk_power / def_power if def_power > 0 else 0
        atk_loss = int(attacker["army_level"] * 15 * (2 - ratio))
        def_loss = int(defender["defense_level"] * 5 * (1 + ratio))
        return {
            "winner": "defender",
            "atk_loss": min(atk_loss, max(1, attacker["army_level"] * 10)),
            "def_loss": min(def_loss, max(1, defender["defense_level"] * 3)),
            "gold_stolen": 0,
            "regions_stolen": 0,
        }


def can_attack(country):
    now = time.time()
    last = parse_time(country.get("last_attack", 0))
    elapsed = now - last
    if elapsed >= config.ATTACK_COOLDOWN:
        return True, 0
    return False, int(config.ATTACK_COOLDOWN - elapsed)


UNIT_TYPES = {
    "tank": {"name": "Танк", "default": "Основной танк"},
    "aircraft": {"name": "Самолёт", "default": "Истребитель"},
    "helicopter": {"name": "Вертолёт", "default": "Ударный вертолёт"},
    "ship": {"name": "Корабль", "default": "Фрегат"},
    "bpla": {"name": "БПЛА", "default": "Разведывательный дрон"},
    "mlrs": {"name": "РСЗО", "default": "Реактивная система"},
    "air_defense": {"name": "ПВО", "default": "ЗРК"},
    "missile": {"name": "Ракета", "default": "Баллистическая ракета"},
    "special": {"name": "Спецназ", "default": "Отряд спецназа"},
}


def calc_power(country, units=None) -> int:
    power = country["army_level"] * 100
    if units:
        for u in units:
            power += u["count"] * 5
    return power


def calc_battle_odds(atk_power, def_power):
    total = atk_power + def_power
    atk_chance = round((atk_power / total) * 100, 1) if total > 0 else 50
    def_chance = round((def_power / total) * 100, 1) if total > 0 else 50
    return atk_chance, def_chance


def format_number(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def format_duration(secs: int) -> str:
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}ч {m}мин"
    if m > 0:
        return f"{m}мин {s}сек"
    return f"{s}сек"


def start_choice():
    b = InlineKeyboardBuilder()
    b.button(text="👑 Создать страну", callback_data="create_country")
    b.button(text="🏠 Стать гражданином", callback_data="become_citizen")
    b.adjust(1)
    return b.as_markup()

def main_menu():
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика", callback_data="stats")
    b.button(text="💰 Экономика", callback_data="economy")
    b.button(text="⚔️ Армия", callback_data="army")
    b.button(text="🏗️ Развитие", callback_data="build")
    b.button(text="💱 Валюта", callback_data="currency")
    b.button(text="🏭 Техника", callback_data="units")
    b.button(text="👥 Граждане", callback_data="citizens")
    b.button(text="🌍 Карта", callback_data="map")
    b.button(text="🤝 Дипломатия", callback_data="diplomacy")
    b.button(text="🏆 Рейтинг", callback_data="top")
    b.adjust(2)
    return b.as_markup()

def citizen_menu():
    b = InlineKeyboardBuilder()
    b.button(text="💼 Работать", callback_data="work")
    b.button(text="🏛 Моя страна", callback_data="my_country")
    b.button(text="🌍 Другие страны", callback_data="map_citizen")
    b.button(text="🚪 Покинуть страну", callback_data="leave_country_confirm")
    b.adjust(1)
    return b.as_markup()

def stats_kb():
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data="stats")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(2)
    return b.as_markup()

def economy_kb():
    b = InlineKeyboardBuilder()
    b.button(text="⛏ Улучшить шахту", callback_data="upgrade_mine")
    b.button(text="🌾 Улучшить ферму", callback_data="upgrade_farm")
    b.button(text="💰 Собрать доход", callback_data="collect")
    b.button(text="💎 Купить золото", callback_data="buy_gold")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def army_kb():
    b = InlineKeyboardBuilder()
    b.button(text="⚔️ Улучшить вооружение", callback_data="upgrade_army")
    b.button(text="🛡️ Улучшить оборону", callback_data="upgrade_defense")
    b.button(text="🔥 Атаковать", callback_data="attack")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def build_kb():
    b = InlineKeyboardBuilder()
    b.button(text="⛏ Шахта", callback_data="upgrade_mine")
    b.button(text="🌾 Ферма", callback_data="upgrade_farm")
    b.button(text="🛡️ Укрепления", callback_data="upgrade_defense")
    b.button(text="🔥 Вооружение", callback_data="upgrade_army")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(2)
    return b.as_markup()

def currency_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📈 Курсы валют", callback_data="currency_rates")
    b.button(text="💱 Купить валюту", callback_data="currency_buy_list")
    b.button(text="💰 Продать валюту", callback_data="currency_sell_list")
    b.button(text="📦 Мои резервы", callback_data="currency_holdings")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def units_kb(in_list=True):
    b = InlineKeyboardBuilder()
    if in_list:
        b.button(text="🔧 Создать технику", callback_data="unit_create")
    b.button(text="🏭 Произвести", callback_data="unit_produce_list")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def citizens_kb(can_kick=False, is_owner=False):
    b = InlineKeyboardBuilder()
    b.button(text="📋 Список граждан", callback_data="citizen_list")
    if is_owner:
        b.button(text="👑 Назначить министром", callback_data="citizen_promote_list")
        b.button(text="🚫 Исключить", callback_data="citizen_kick_list")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def diplomacy_kb(in_alliance: bool, is_owner: bool = False):
    b = InlineKeyboardBuilder()
    if in_alliance:
        b.button(text="📋 Мой альянс", callback_data="my_alliance")
        if is_owner:
            b.button(text="💔 Распустить", callback_data="alliance_disband_confirm")
        else:
            b.button(text="🚪 Покинуть", callback_data="alliance_leave_confirm")
    else:
        b.button(text="📋 Список альянсов", callback_data="alliance_list")
        b.button(text="✨ Создать альянс", callback_data="alliance_create_start")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def top_kb():
    b = InlineKeyboardBuilder()
    b.button(text="👑 По золоту", callback_data="top_gold")
    b.button(text="💰 По курсу валюты", callback_data="top_currency")
    b.button(text="👥 По населению", callback_data="top_population")
    b.button(text="🏆 По победам", callback_data="top_wins")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def attack_target_kb(countries, page=0, per_page=5):
    b = InlineKeyboardBuilder()
    start = page * per_page
    for c in countries[start:start + per_page]:
        b.button(text=f"⚔ {c['name']}", callback_data=f"attack_confirm:{c['id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"attack_page:{page - 1}"))
    if start + per_page < len(countries):
        nav.append(InlineKeyboardButton(text="Вперед ▶", callback_data=f"attack_page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.button(text="🏠 Главная", callback_data="menu")
    return b.as_markup()

def currency_rates_kb(countries, page=0, per_page=5):
    b = InlineKeyboardBuilder()
    start = page * per_page
    for c in countries[start:start + per_page]:
        b.button(text=f"{c['name']} ({c['currency_code']})", callback_data=f"currency_view:{c['id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"crates_page:{page - 1}"))
    if start + per_page < len(countries):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"crates_page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.button(text="🏠 Главная", callback_data="menu")
    return b.as_markup()

def currency_buy_kb(countries, page=0, per_page=5):
    b = InlineKeyboardBuilder()
    start = page * per_page
    for c in countries[start:start + per_page]:
        b.button(text=f"💱 {c['name']} ({c['currency_code']})", callback_data=f"currency_buy:{c['id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"cbuy_page:{page - 1}"))
    if start + per_page < len(countries):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"cbuy_page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.button(text="🏠 Главная", callback_data="menu")
    return b.as_markup()

def holdings_kb(holdings):
    b = InlineKeyboardBuilder()
    for h in holdings:
        b.button(text=f"💰 {h['target_code']} ({h['amount']})", callback_data=f"holding_sell:{h['target_code']}")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def unit_create_kb():
    b = InlineKeyboardBuilder()
    b.button(text="Танк", callback_data="unit_type:tank")
    b.button(text="Самолёт", callback_data="unit_type:aircraft")
    b.button(text="Вертолёт", callback_data="unit_type:helicopter")
    b.button(text="Корабль", callback_data="unit_type:ship")
    b.button(text="БПЛА", callback_data="unit_type:bpla")
    b.button(text="РСЗО", callback_data="unit_type:mlrs")
    b.button(text="ПВО", callback_data="unit_type:air_defense")
    b.button(text="Ракета", callback_data="unit_type:missile")
    b.button(text="Спецназ", callback_data="unit_type:special")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(2)
    return b.as_markup()

def units_list_kb(units):
    b = InlineKeyboardBuilder()
    for u in units:
        b.button(text=f"{u['name']} ({u['count']} ед.)", callback_data=f"unit_view:{u['id']}")
    b.button(text="🔧 Создать новую", callback_data="unit_create")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def unit_view_kb(uid):
    b = InlineKeyboardBuilder()
    b.button(text="🏭 Произвести 1", callback_data=f"unit_produce:{uid}")
    b.button(text="❌ Удалить", callback_data=f"unit_delete:{uid}")
    b.button(text="↩ Назад", callback_data="units")
    b.adjust(1)
    return b.as_markup()

def unit_produce_kb(units, page=0, per_page=5):
    b = InlineKeyboardBuilder()
    start = page * per_page
    for u in units[start:start + per_page]:
        b.button(text=f"🏭 {u['name']} ({u['cost_gold']}👑)", callback_data=f"unit_produce:{u['id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"produce_page:{page - 1}"))
    if start + per_page < len(units):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"produce_page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.button(text="🏠 Главная", callback_data="menu")
    return b.as_markup()

def confirm_kb(action: str, cid: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить", callback_data=f"{action}:{cid}")
    b.button(text="❌ Отмена", callback_data="menu")
    b.adjust(2)
    return b.as_markup()

def alliance_list_kb(alliances, page=0, per_page=5):
    b = InlineKeyboardBuilder()
    start = page * per_page
    for a in alliances[start:start + per_page]:
        b.button(text=f"{a['tag']} {a['name']} ({a['members']} уч.)", callback_data=f"alliance_view:{a['id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"alliance_page:{page - 1}"))
    if start + per_page < len(alliances):
        nav.append(InlineKeyboardButton(text="Вперед ▶", callback_data=f"alliance_page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.button(text="🏠 Главная", callback_data="menu")
    return b.as_markup()

def country_list_kb(countries, action_prefix, page=0, per_page=5):
    b = InlineKeyboardBuilder()
    start = page * per_page
    for c in countries[start:start + per_page]:
        b.button(text=f"{c['name']}", callback_data=f"{action_prefix}:{c['id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"{action_prefix}_page:{page - 1}"))
    if start + per_page < len(countries):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"{action_prefix}_page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.button(text="🏠 Главная", callback_data="menu")
    return b.as_markup()

def simple_kb(*buttons):
    b = InlineKeyboardBuilder()
    for text, cb in buttons:
        b.button(text=text, callback_data=cb)
    b.adjust(1)
    return b.as_markup()

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


router = Router()


class Register(StatesGroup):
    name = State()
    leader = State()
    currency_name = State()
    currency_code = State()


class CreateUnit(StatesGroup):
    unit_type = State()
    name = State()


class BecomeCitizen(StatesGroup):
    country_select = State()


class CreateAlliance(StatesGroup):
    name = State()
    tag = State()


# ===================== START =====================

@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    c = await db.get_country(msg.from_user.id)
    cit = await db.get_citizen(msg.from_user.id)
    if c:
        await msg.answer(
            f"🇺🇳 С возвращением, {c['name']}!\nВаша страна ждёт вас.",
            reply_markup=main_menu()
        )
    elif cit:
        host = await db.get_country_by_id(cit["country_id"])
        hname = host["name"] if host else "?"
        await msg.answer(
            f"🏠 С возвращением! Вы гражданин {hname}.\n"
            "Зарабатывайте золото и помогайте своей стране!",
            reply_markup=citizen_menu()
        )
    else:
        await msg.answer(
            "🏛 ДОБРО ПОЖАЛОВАТЬ В МИРОВУЮ АРЕНУ!\n\n"
            "Выберите свой путь:",
            reply_markup=start_choice()
        )


@router.message(Command("menu"))
async def cmd_menu(msg: Message):
    c = await db.get_country(msg.from_user.id)
    cit = await db.get_citizen(msg.from_user.id)
    if c:
        await msg.answer("🏛 Главное меню:", reply_markup=main_menu())
    elif cit:
        await msg.answer("🏠 Меню гражданина:", reply_markup=citizen_menu())
    else:
        await msg.answer("Сначала создайте страну или станьте гражданином — /start")


# ===================== CREATE COUNTRY FLOW =====================

@router.callback_query(F.data == "create_country")
async def cb_create_country(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(Register.name)
    await cq.message.edit_text(
        "👑 СОЗДАНИЕ СТРАНЫ\n\n"
        "Придумайте название своей страны:"
    )


@router.message(Register.name)
async def reg_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if len(name) < 2 or len(name) > 30:
        await msg.answer("Название должно быть от 2 до 30 символов.")
        return
    if not re.match(r'^[a-zA-Zа-яА-ЯёЁ0-9\- ]+$', name):
        await msg.answer("Только буквы, цифры, пробелы и дефис.")
        return
    existing = await db.get_country_by_name(name)
    if existing:
        await msg.answer("Такая страна уже существует! Придумайте другое название:")
        return
    await state.update_data(name=name)
    await state.set_state(Register.leader)
    await msg.answer(f"Отлично, {name}!\n\nКак к вам обращаться? (Президент, Король, Император...):")


@router.message(Register.leader)
async def reg_leader(msg: Message, state: FSMContext):
    leader = msg.text.strip()
    if len(leader) < 2 or len(leader) > 20:
        await msg.answer("Титул от 2 до 20 символов.")
        return
    await state.update_data(leader=leader)
    await state.set_state(Register.currency_name)
    await msg.answer("Придумайте название валюты (например, Рубль, Кредит, Марка):")


@router.message(Register.currency_name)
async def reg_cur_name(msg: Message, state: FSMContext):
    cname = msg.text.strip()
    if len(cname) < 2 or len(cname) > 20:
        await msg.answer("Название валюты от 2 до 20 символов.")
        return
    await state.update_data(currency_name=cname)
    await state.set_state(Register.currency_code)
    await msg.answer("Придумайте код валюты (2-5 букв, например RUB, USD, CRD):")


@router.message(Register.currency_code)
async def reg_cur_code(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    if len(code) < 2 or len(code) > 5:
        await msg.answer("Код от 2 до 5 букв.")
        return
    if not re.match(r'^[A-Z]+$', code):
        await msg.answer("Только латинские буквы.")
        return
    if code.upper() == "GOLD":
        await msg.answer("Нельзя использовать GOLD как код валюты.")
        return
    data = await state.get_data()
    ok = await db.register_country(
        msg.from_user.id, data["name"], data["leader"],
        data["currency_name"], code
    )
    if not ok:
        await msg.answer("Ошибка. Попробуйте /start")
        await state.clear()
        return
    await state.clear()
    await db.update_country(msg.from_user.id, last_collect=int(time.time()))
    await msg.answer(
        "🎉 ПОЗДРАВЛЯЕМ!\n\n"
        f"Страна {data['name']} основана!\n"
        f"Титул: {data['leader']}\n"
        f"Валюта: {data['currency_name']} ({code})\n"
        f"Столица: {data['name']}град\n\n"
        f"Вам начислено: {config.START_GOLD} 👑 Золота\n\n"
        "Удачи в развитии своей империи!",
        reply_markup=main_menu()
    )


# ===================== BECOME CITIZEN =====================

@router.callback_query(F.data == "become_citizen")
async def cb_become_citizen(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    countries = await db.get_all_countries(order_by="gold DESC", limit=50)
    if not countries:
        await cq.message.edit_text("Пока нет стран для вступления. Создайте свою!", reply_markup=start_choice())
        return
    await state.set_state(BecomeCitizen.country_select)
    await cq.message.edit_text(
        "🏠 ВЫБЕРИТЕ СТРАНУ\n\nВ какой стране хотите стать гражданином?",
        reply_markup=country_list_kb(countries, "citizen_join")
    )


@router.callback_query(F.data.startswith("citizen_join:"))
async def cb_citizen_join(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    cid = int(cq.data.split(":")[1])
    target = await db.get_country_by_id(cid)
    if not target:
        await cq.answer("Страна не найдена!", show_alert=True)
        return
    count = await db.get_citizen_count(cid)
    if count >= config.CITIZEN_MAX_PER_COUNTRY:
        await cq.answer("В этой стране уже максимум граждан!", show_alert=True)
        return
    username = cq.from_user.username or cq.from_user.full_name or "Гражданин"
    ok = await db.register_citizen(cq.from_user.id, username, cid)
    if not ok:
        await cq.answer("Ошибка! Возможно, вы уже гражданин другой страны.", show_alert=True)
        return
    await state.clear()
    await cq.message.edit_text(
        f"✅ Вы стали гражданином {target['name']}!\n\n"
        f"Работайте, зарабатывайте золото и помогайте стране расти.\n"
        f"5% вашего дохода автоматически уходит в казну страны.",
        reply_markup=citizen_menu()
    )


@router.callback_query(F.data.startswith("citizen_join_page:"))
async def cb_citizen_join_page(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    page = int(cq.data.split(":")[1])
    countries = await db.get_all_countries(order_by="gold DESC", limit=50)
    await cq.message.edit_text(
        "🏠 ВЫБЕРИТЕ СТРАНУ",
        reply_markup=country_list_kb(countries, "citizen_join", page)
    )


# ===================== CITIZEN ACTIONS =====================

@router.callback_query(F.data == "work")
async def cb_work(cq: CallbackQuery):
    await cq.answer()
    cit = await db.get_citizen(cq.from_user.id)
    if not cit:
        await cq.message.edit_text("Вы не гражданин. /start", reply_markup=start_choice())
        return
    gold_earn = config.CITIZEN_WORK_GOLD
    tax = int(gold_earn * config.CITIZEN_TAX_RATE)
    net = gold_earn - tax
    new_gold = cit["gold"] + net
    await db.update_citizen_gold(cq.from_user.id, new_gold)
    host = await db.get_country_by_id(cit["country_id"])
    if host:
        await db.update_country(host["user_id"], gold=host["gold"] + tax)
    await cq.message.edit_text(
        f"💼 Вы поработали!\n\n"
        f"💰 Заработано: {gold_earn} золота\n"
        f"💸 Налог (5%): {tax} золота\n"
        f"✅ Чистыми: {net} золота\n"
        f"💰 Ваш баланс: {new_gold} золота",
        reply_markup=citizen_menu()
    )


@router.callback_query(F.data == "my_country")
async def cb_my_country_cit(cq: CallbackQuery):
    await cq.answer()
    cit = await db.get_citizen(cq.from_user.id)
    if not cit:
        return
    host = await db.get_country_by_id(cit["country_id"])
    if not host:
        return
    role_icon = {"citizen": "🔹", "minister": "⭐", "vice_president": "👑"}
    role_name = {"citizen": "Гражданин", "minister": "Министр", "vice_president": "Вице-президент"}
    count = await db.get_citizen_count(host["id"])
    await cq.message.edit_text(
        f"🏛 <b>{host['name']}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👑 Лидер: {host['leader_title']}\n"
        f"💰 Золото: {game.format_number(host['gold'])}\n"
        f"💱 Валюта: {host['currency_name']} ({host['currency_code']})\n"
        f"   Курс: {host['currency_value']} 👑 за 1 {host['currency_code']}\n"
        f"👥 Граждан: {count}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{role_icon.get(cit['role'], '🔹')} Ваша роль: {role_name.get(cit['role'], 'Гражданин')}\n"
        f"💰 Ваше золото: {cit['gold']}",
        reply_markup=simple_kb(("🏠 Назад", "menu")), parse_mode="HTML"
    )


@router.callback_query(F.data == "leave_country_confirm")
async def cb_leave_country(cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        "❓ Вы уверены, что хотите покинуть страну?",
        reply_markup=confirm_kb("citizen_leave", cq.from_user.id)
    )


@router.callback_query(F.data.startswith("citizen_leave:"))
async def cb_citizen_leave(cq: CallbackQuery):
    await cq.answer()
    await db.leave_citizen(cq.from_user.id)
    await cq.message.edit_text(
        "✅ Вы покинули страну.\n"
        "Можете вступить в другую или создать свою!",
        reply_markup=start_choice()
    )


@router.callback_query(F.data == "map_citizen")
async def cb_map_citizen(cq: CallbackQuery):
    await cq.answer()
    countries = await db.get_all_countries(order_by="gold DESC", limit=50)
    lines = ["🌍 <b>СТРАНЫ МИРА</b>\n━━━━━━━━━━━━━━━\n"]
    for i, c in enumerate(countries, 1):
        lines.append(f"{i}. <b>{c['name']}</b> | 💰 {game.format_number(c['gold'])} | 👥 {c['regions']} рег.")
        if i >= 20:
            lines.append("\n... и другие")
            break
    await cq.message.edit_text(
        "\n".join(lines),
        reply_markup=simple_kb(("🏠 Назад", "menu")), parse_mode="HTML"
    )


# ===================== MAIN MENU =====================

@router.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    cit = await db.get_citizen(cq.from_user.id)
    if c:
        await cq.message.edit_text(
            f"🏛 <b>ГЛАВНОЕ МЕНЮ</b>\n\n"
            f"<b>{c['name']}</b>\n"
            f"👑 Лидер: {c['leader_title']}\n\n"
            f"💰 Золото: {game.format_number(c['gold'])} | 💎 Кристаллы: {c['crystals']}\n"
            f"💱 Валюта: {c['currency_name']} ({c['currency_code']}) — курс: {c['currency_value']}\n"
            f"⚔️ Армия ур.: {c['army_level']} | 🛡 Оборона: {c['defense_level']}",
            reply_markup=main_menu(), parse_mode="HTML"
        )
    elif cit:
        host = await db.get_country_by_id(cit["country_id"])
        hname = host["name"] if host else "?"
        await cq.message.edit_text(
            f"🏠 Вы гражданин {hname}\n💰 Ваше золото: {cit['gold']}",
            reply_markup=citizen_menu()
        )


# ===================== STATS =====================

@router.callback_query(F.data == "stats")
async def cb_stats(cq: CallbackQuery):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    citizens = await db.get_citizen_count(c["id"])
    units = await db.get_units(c["id"])
    total_units = sum(u["count"] for u in units)
    inc = game.calc_income(c, citizens)
    await cq.message.edit_text(
        "📊 <b>СТАТИСТИКА</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🇺🇳 Страна: {c['name']}\n"
        f"👑 Лидер: {c['leader_title']}\n"
        f"💱 Валюта: {c['currency_name']} ({c['currency_code']})\n"
        f"   Курс: {c['currency_value']} 👑 за 1 {c['currency_code']}\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Золото: {game.format_number(c['gold'])}\n"
        f"💎 Кристаллы: {c['crystals']}\n"
        "━━━━━━━━━━━━━━━\n"
        f"⚔️ Армия ур.: {c['army_level']} | 🛡 Оборона: {c['defense_level']}\n"
        f"🏭 Единиц техники: {total_units}\n"
        "━━━━━━━━━━━━━━━\n"
        f"⛏ Шахта: {c['mine_level']} ур. | 🌾 Ферма: {c['farm_level']} ур.\n"
        f"🌍 Регионы: {c['regions']}\n"
        f"👥 Граждан: {citizens}\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Доход в час: {game.format_number(inc['per_hour'])} золота\n"
        f"   ├ Регионы: +{game.format_number(inc['region'])}\n"
        f"   ├ Шахта: +{game.format_number(inc['mine'])}\n"
        f"   ├ Ферма: +{game.format_number(inc['farm'])}\n"
        f"   └ Налоги: +{game.format_number(inc['citizen_tax'])}\n"
        "━━━━━━━━━━━━━━━\n"
        f"🏆 Побед: {c['wars_won']} | 💔 Поражений: {c['wars_lost']}",
        reply_markup=stats_kb(), parse_mode="HTML"
    )


# ===================== ECONOMY =====================

@router.callback_query(F.data == "economy")
async def cb_economy(cq: CallbackQuery):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    citizens = await db.get_citizen_count(c["id"])
    inc = game.calc_income(c, citizens)
    collectable = game.calc_collectable(c, citizens)
    await cq.message.edit_text(
        "💰 <b>ЭКОНОМИКА</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"⛏ Шахта: {c['mine_level']} ур. (+{inc['mine']}/ч)\n"
        f"🌾 Ферма: {c['farm_level']} ур. (+{inc['farm']}/ч)\n"
        f"🌍 Регионы: {c['regions']} (+{inc['region']}/ч)\n"
        f"👥 Налоги: +{inc['citizen_tax']}/ч\n"
        "━━━━━━━━━━━━━━━\n"
        f"📈 Доход в час: {game.format_number(inc['per_hour'])}\n"
        f"📦 Накоплено: {game.format_number(collectable)}\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Золото: {game.format_number(c['gold'])}\n"
        f"💎 Кристаллы: {c['crystals']}",
        reply_markup=economy_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "collect")
async def cb_collect(cq: CallbackQuery):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    citizens = await db.get_citizen_count(c["id"])
    collectable = game.calc_collectable(c, citizens)
    if collectable <= 0:
        await cq.answer("Нечего собирать!", show_alert=True)
        return
    new_gold = c["gold"] + collectable
    await db.update_country(cq.from_user.id, gold=new_gold, last_collect=int(time.time()))
    inc = game.calc_income(c, citizens)
    await cq.message.edit_text(
        "✅ <b>ДОХОД СОБРАН!</b>\n\n"
        f"💰 +{game.format_number(collectable)} золота\n\n"
        f"Баланс: {game.format_number(new_gold)}\n"
        f"📈 Доход в час: {game.format_number(inc['per_hour'])}",
        reply_markup=economy_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "buy_gold")
async def cb_buy_gold(cq: CallbackQuery):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    await cq.message.edit_text(
        "💎 <b>ОБМЕН КРИСТАЛЛОВ</b>\n\n"
        f"Курс: 1 💎 = {config.CRYSTAL_TO_GOLD} 👑\n\n"
        f"Ваши кристаллы: {c['crystals']}\n"
        f"Ваше золото: {game.format_number(c['gold'])}\n\n"
        "Напишите <b>buy N</b> (где N — количество кристаллов):",
        reply_markup=simple_kb(("🏠 Главная", "menu")), parse_mode="HTML"
    )


# ===================== BUILD / UPGRADES =====================

@router.callback_query(F.data == "build")
async def cb_build(cq: CallbackQuery):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    await cq.message.edit_text(
        "🏗️ <b>РАЗВИТИЕ</b>\n\n"
        f"⛏ Шахта: {c['mine_level']} ур. — {game.format_number(game.calc_mine_cost(c['mine_level']+1))} 👑\n"
        f"🌾 Ферма: {c['farm_level']} ур. — {game.format_number(game.calc_farm_cost(c['farm_level']+1))} 👑\n"
        f"🛡 Укрепления: {c['defense_level']} ур. — {game.format_number(game.calc_defense_cost(c['defense_level']+1))} 👑\n"
        f"🔥 Вооружение: {c['army_level']} ур. — {game.format_number(game.calc_army_level_cost(c['army_level']+1))} 👑\n\n"
        f"💰 Золото: {game.format_number(c['gold'])}",
        reply_markup=build_kb(), parse_mode="HTML"
    )


async def upgrade_action(cq, field, cost_func, level_field, name):
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    level = c[level_field]
    cost = cost_func(level + 1)
    if c["gold"] < cost:
        await cq.answer(f"❌ Нужно {game.format_number(cost)} золота", show_alert=True)
        return
    new_gold = c["gold"] - cost
    await db.update_country(cq.from_user.id, gold=new_gold, **{field: level + 1})
    await cq.answer(f"✅ {name} улучшен до {level + 1} ур.", show_alert=True)
    await cb_build(cq)


@router.callback_query(F.data == "upgrade_mine")
async def cb_upgrade_mine(cq):
    await upgrade_action(cq, "mine_level", game.calc_mine_cost, "mine_level", "⛏ Шахта")


@router.callback_query(F.data == "upgrade_farm")
async def cb_upgrade_farm(cq):
    await upgrade_action(cq, "farm_level", game.calc_farm_cost, "farm_level", "🌾 Ферма")


@router.callback_query(F.data == "upgrade_defense")
async def cb_upgrade_defense(cq):
    await upgrade_action(cq, "defense_level", game.calc_defense_cost, "defense_level", "🛡 Укрепления")


@router.callback_query(F.data == "upgrade_army")
async def cb_upgrade_army(cq):
    await upgrade_action(cq, "army_level", game.calc_army_level_cost, "army_level", "🔥 Вооружение")


# ===================== ARMY / ATTACK =====================

@router.callback_query(F.data == "army")
async def cb_army(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    units = await db.get_units(c["id"])
    total = sum(u["count"] for u in units)
    await cq.message.edit_text(
        f"⚔️ <b>ВОЕННОЕ ДЕЛО</b>\n\n"
        f"🔥 Уровень войск: {c['army_level']}\n"
        f"🛡 Уровень обороны: {c['defense_level']}\n"
        f"🏭 Единиц техники: {total}\n\n"
        f"Стоимость атаки: {config.ATTACK_COST} 👑\n"
        f"Кулдаун: 5 минут",
        reply_markup=army_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "attack")
async def cb_attack(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    can, cd = game.can_attack(c)
    if not can:
        await cq.answer(f"⏳ Подождите {game.format_duration(cd)}", show_alert=True)
        return
    targets = await db.get_all_countries_full(limit=100)
    targets = [t for t in targets if t["id"] != c["id"]]
    if not targets:
        await cq.answer("Нет целей!", show_alert=True)
        return
    await cq.message.edit_text("🔥 <b>ВЫБЕРИТЕ ЦЕЛЬ</b>", reply_markup=attack_target_kb(targets), parse_mode="HTML")


@router.callback_query(F.data.startswith("attack_page:"))
async def cb_attack_page(cq):
    await cq.answer()
    page = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    targets = await db.get_all_countries_full(limit=100)
    targets = [t for t in targets if t["id"] != c["id"]]
    await cq.message.edit_text("🔥 <b>ВЫБЕРИТЕ ЦЕЛЬ</b>", reply_markup=attack_target_kb(targets, page=page), parse_mode="HTML")


@router.callback_query(F.data.startswith("attack_confirm:"))
async def cb_attack_confirm(cq):
    await cq.answer()
    target_id = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c: return
    target = await db.get_country_by_id(target_id)
    if not target or target["id"] == c["id"]: return
    can, cd = game.can_attack(c)
    if not can:
        await cq.answer(f"⏳ {game.format_duration(cd)}", show_alert=True)
        return
    if c["gold"] < config.ATTACK_COST:
        await cq.answer(f"❌ Нужно {config.ATTACK_COST} золота", show_alert=True)
        return

    atk_units = await db.get_units(c["id"])
    def_units = await db.get_units(target["id"])
    atk_power = game.calc_power(c, atk_units)
    def_power = game.calc_power(target, def_units) * 1.15
    atk_chance, def_chance = game.calc_battle_odds(atk_power, def_power)

    b = InlineKeyboardBuilder()
    b.button(text="🔥 АТАКОВАТЬ", callback_data=f"attack_execute:{target_id}")
    b.button(text="❌ Отмена", callback_data="menu")
    b.adjust(1)

    await cq.message.edit_text(
        f"⚔️ <b>ПОДТВЕРЖДЕНИЕ АТАКИ</b>\n\n"
        f"Цель: <b>{target['name']}</b>\n"
        f"Лидер: {target['leader_title']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🟢 Ваша сила: {game.format_number(atk_power)}\n"
        f"🔴 Сила врага: {game.format_number(int(def_power))}\n"
        f"📊 Шанс победы: <b>{atk_chance}%</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 Стоимость: {config.ATTACK_COST} 👑\n"
        f"При победе: захват золота (15%) и 1 региона",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("attack_execute:"))
async def cb_attack_execute(cq):
    await cq.answer()
    target_id = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c: return
    target = await db.get_country_by_id(target_id)
    if not target or target["id"] == c["id"]: return
    can, cd = game.can_attack(c)
    if not can:
        await cq.answer(f"⏳ {game.format_duration(cd)}", show_alert=True)
        return
    if c["gold"] < config.ATTACK_COST:
        await cq.answer(f"❌ Нужно {config.ATTACK_COST} золота", show_alert=True)
        return

    atk_bonus = def_bonus = 1.0
    atk_al = await db.get_alliance_by_country(c["id"])
    def_al = await db.get_alliance_by_country(target["id"])
    if atk_al:
        members = await db.get_alliance_members(atk_al["id"])
        atk_bonus = 1.0 + len(members) * 0.02
    if def_al:
        members = await db.get_alliance_members(def_al["id"])
        def_bonus = 1.0 + len(members) * 0.02

    atk_units = await db.get_units(c["id"])
    def_units = await db.get_units(target["id"])
    result = game.calc_battle(c, target, atk_bonus, def_bonus, atk_units, def_units)
    new_gold = c["gold"] - config.ATTACK_COST

    if result["winner"] == "attacker":
        new_gold += result["gold_stolen"]
        def_gold = target["gold"] - result["gold_stolen"]
        def_regions = max(1, target["regions"] - result["regions_stolen"])
        atk_regions = c["regions"] + result["regions_stolen"]
        await db.update_country(cq.from_user.id, gold=new_gold, regions=atk_regions, wars_won=c["wars_won"]+1, last_attack=int(time.time()))
        await db.update_country(target["user_id"], gold=max(0, def_gold), regions=def_regions, wars_lost=target["wars_lost"]+1)
        await db.log_war(c["id"], target["id"], c["id"], result["gold_stolen"], result["regions_stolen"])
        await cq.message.edit_text(
            "🎉 <b>ПОБЕДА!</b>\n\n"
            f"⚔️ {c['name']} разгромил {target['name']}!\n\n"
            f"📊 Потери: {result['atk_loss']} / {result['def_loss']}\n"
            f"💰 Захвачено: {result['gold_stolen']} золота\n"
            f"🌍 Захвачено: {result['regions_stolen']} регионов",
            reply_markup=main_menu(), parse_mode="HTML"
        )
    else:
        await db.update_country(cq.from_user.id, gold=max(0, new_gold), wars_lost=c["wars_lost"]+1, last_attack=int(time.time()))
        def_gold = target["gold"] + int(config.ATTACK_COST * 0.5)
        await db.update_country(target["user_id"], gold=def_gold, wars_won=target["wars_won"]+1)
        await db.log_war(c["id"], target["id"], target["id"], 0, 0)
        await cq.message.edit_text(
            "😔 <b>ПОРАЖЕНИЕ!</b>\n\n"
            f"⚔️ {c['name']} проиграл {target['name']}!\n\n"
            f"📊 Потери: {result['atk_loss']}",
            reply_markup=main_menu(), parse_mode="HTML"
        )


# ===================== CURRENCY =====================

@router.callback_query(F.data == "currency")
async def cb_currency(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    await cq.message.edit_text(
        f"💱 <b>ВАЛЮТНЫЙ РЫНОК</b>\n\n"
        f"Ваша валюта: {c['currency_name']} ({c['currency_code']})\n"
        f"Текущий курс: 1 {c['currency_code']} = {c['currency_value']} 👑\n\n"
        "Покупайте и продавайте валюту других стран!\n"
        "Курсы меняются от экономики, армии и населения.",
        reply_markup=currency_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "currency_rates")
async def cb_currency_rates(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    countries = await db.get_all_countries(order_by="currency_value DESC", limit=50)
    await cq.message.edit_text(
        "📈 <b>КУРСЫ ВАЛЮТ</b>\n\nКурс к золоту (👑):",
        reply_markup=currency_rates_kb(countries), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("crates_page:"))
async def cb_crates_page(cq):
    await cq.answer()
    page = int(cq.data.split(":")[1])
    countries = await db.get_all_countries(order_by="currency_value DESC", limit=50)
    await cq.message.edit_text("📈 <b>КУРСЫ ВАЛЮТ</b>", reply_markup=currency_rates_kb(countries, page=page), parse_mode="HTML")


@router.callback_query(F.data.startswith("currency_view:"))
async def cb_currency_view(cq):
    await cq.answer()
    cid = int(cq.data.split(":")[1])
    target = await db.get_country_by_id(cid)
    if not target:
        return
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    holdings = await db.get_holding(c["id"], target["currency_code"])
    held = holdings["amount"] if holdings else 0
    b = InlineKeyboardBuilder()
    if target["id"] != c["id"]:
        b.button(text="💱 Купить", callback_data=f"currency_buy:{cid}")
    if held > 0:
        b.button(text="💰 Продать", callback_data=f"holding_sell:{target['currency_code']}")
    b.button(text="↩ Назад", callback_data="currency_rates")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    await cq.message.edit_text(
        f"💱 <b>{target['currency_name']} ({target['currency_code']})</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Страна: {target['name']}\n"
        f"Курс: 1 {target['currency_code']} = {target['currency_value']} 👑\n"
        f"━━━━━━━━━━━━━━━\n"
        f"У вас: {held:.2f} {target['currency_code']}\n\n"
        f"Курс покупки: {target['currency_value'] * (1+config.CURRENCY_TRADE_FEE):.4f} 👑\n"
        f"Курс продажи: {target['currency_value'] * (1-config.CURRENCY_TRADE_FEE):.4f} 👑",
        parse_mode="HTML", reply_markup=b.as_markup()
    )


@router.callback_query(F.data == "currency_buy_list")
async def cb_currency_buy_list(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c:
        return
    countries = await db.get_all_countries_full(limit=50)
    countries = [t for t in countries if t["id"] != c["id"]]
    await cq.message.edit_text(
        "💱 <b>КУПИТЬ ВАЛЮТУ</b>\n\nВыберите страну:",
        reply_markup=currency_buy_kb(countries), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("cbuy_page:"))
async def cb_cbuy_page(cq):
    await cq.answer()
    page = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c: return
    countries = await db.get_all_countries_full(limit=50)
    countries = [t for t in countries if t["id"] != c["id"]]
    await cq.message.edit_text("💱 <b>КУПИТЬ ВАЛЮТУ</b>", reply_markup=currency_buy_kb(countries, page=page), parse_mode="HTML")


@router.callback_query(F.data.startswith("currency_buy:"))
async def cb_currency_buy(cq):
    await cq.answer()
    cid = int(cq.data.split(":")[1])
    target = await db.get_country_by_id(cid)
    if not target: return
    c = await db.get_country(cq.from_user.id)
    if not c: return
    rate = target["currency_value"] * (1 + config.CURRENCY_TRADE_FEE)
    max_can_buy = c["gold"] / rate if rate > 0 else 0
    await cq.message.edit_text(
        f"💱 <b>ПОКУПКА {target['currency_code']}</b>\n\n"
        f"Курс: 1 {target['currency_code']} = {rate:.4f} 👑\n"
        f"Ваше золото: {game.format_number(c['gold'])}\n"
        f"Максимум: {max_can_buy:.2f} {target['currency_code']}\n\n"
        f"Напишите <b>buy_currency {target['currency_code']} N</b>\n"
        f"где N — сколько купить:",
        reply_markup=simple_kb(("↩ Назад", "currency")), parse_mode="HTML"
    )


@router.callback_query(F.data == "currency_sell_list")
async def cb_currency_sell(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    holdings = await db.get_holdings(c["id"])
    if not holdings:
        await cq.answer("У вас нет валютных резервов!", show_alert=True)
        return
    await cq.message.edit_text(
        "💰 <b>ПРОДАТЬ ВАЛЮТУ</b>\n\nВыберите валюту для продажи:",
        reply_markup=holdings_kb(holdings), parse_mode="HTML"
    )


@router.callback_query(F.data == "currency_holdings")
async def cb_currency_holdings(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    holdings = await db.get_holdings(c["id"])
    if not holdings:
        await cq.message.edit_text(
            "📦 У вас нет валютных резервов.",
            reply_markup=currency_kb()
        )
        return
    lines = ["📦 <b>ВАЛЮТНЫЕ РЕЗЕРВЫ</b>\n━━━━━━━━━━━━━━━\n"]
    total_gold_value = 0
    for h in holdings:
        # find current rate from country with this currency
        lines.append(f"💰 {h['target_code']}: {h['amount']:.2f}")
    val = sum(h["amount"] for h in holdings)
    lines.append(f"\nВсего единиц: {val:.2f}")
    await cq.message.edit_text(
        "\n".join(lines),
        reply_markup=currency_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("holding_sell:"))
async def cb_holding_sell(cq):
    await cq.answer()
    code = cq.data.split(":")[1]
    c = await db.get_country(cq.from_user.id)
    if not c: return
    holding = await db.get_holding(c["id"], code)
    if not holding or holding["amount"] <= 0:
        await cq.answer("Нет этой валюты!", show_alert=True)
        return
    await cq.message.edit_text(
        f"💰 <b>ПРОДАТЬ {code}</b>\n\n"
        f"У вас: {holding['amount']:.2f} {code}\n\n"
        f"Напишите <b>sell_currency {code} N</b>\n"
        f"где N — сколько продать:",
        reply_markup=simple_kb(("↩ Назад", "currency")), parse_mode="HTML"
    )


# ===================== MILITARY UNITS =====================

@router.callback_query(F.data == "units")
async def cb_units(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    units = await db.get_units(c["id"])
    if not units:
        await cq.message.edit_text(
            "🏭 <b>ВОЕННАЯ ТЕХНИКА</b>\n\n"
            "У вас пока нет техники. Создайте свою первую единицу!",
            reply_markup=units_kb(False), parse_mode="HTML"
        )
    else:
        lines = ["🏭 <b>ВОЕННАЯ ТЕХНИКА</b>\n━━━━━━━━━━━━━━━\n"]
        for u in units:
            tname = game.UNIT_TYPES.get(u["unit_type"], {}).get("name", u["unit_type"])
            lines.append(f"• <b>{u['name']}</b> ({tname}) — {u['count']} ед.")
        lines.append(f"\nВсего: {sum(u['count'] for u in units)} единиц")
        await cq.message.edit_text(
            "\n".join(lines),
            reply_markup=units_list_kb(units), parse_mode="HTML"
        )


@router.callback_query(F.data == "unit_create")
async def cb_unit_create(cq, state: FSMContext):
    await cq.answer()
    await state.set_state(CreateUnit.unit_type)
    await cq.message.edit_text(
        "🔧 <b>СОЗДАНИЕ ТЕХНИКИ</b>\n\n"
        "Выберите тип техники:",
        reply_markup=unit_create_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("unit_type:"))
async def cb_unit_type(cq, state: FSMContext):
    await cq.answer()
    utype = cq.data.split(":")[1]
    await state.update_data(unit_type=utype)
    await state.set_state(CreateUnit.name)
    tname = game.UNIT_TYPES.get(utype, {}).get("name", utype)
    default = game.UNIT_TYPES.get(utype, {}).get("default", "Техника")
    await cq.message.edit_text(
        f"🔧 <b>{tname}</b>\n\n"
        f"Придумайте название для вашего {tname.lower()}а\n"
        f"(например: {default}):"
    )


@router.message(CreateUnit.name)
async def unit_create_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if len(name) < 2 or len(name) > 40:
        await msg.answer("Название от 2 до 40 символов.")
        return
    data = await state.get_data()
    c = await db.get_country(msg.from_user.id)
    if not c:
        await state.clear()
        return
    ok = await db.create_unit(c["id"], data["unit_type"], name, config.UNIT_PRODUCE_COST)
    if not ok:
        await msg.answer("Ошибка создания.")
        await state.clear()
        return
    await state.clear()
    tname = game.UNIT_TYPES.get(data["unit_type"], {}).get("name", data["unit_type"])
    await msg.answer(
        f"✅ Создана новая техника: <b>{name}</b> ({tname})\n"
        f"Стоимость производства: {config.UNIT_PRODUCE_COST} 👑 за единицу",
        reply_markup=main_menu(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("unit_view:"))
async def cb_unit_view(cq):
    await cq.answer()
    uid = int(cq.data.split(":")[1])
    u = await db.get_unit(uid)
    if not u:
        return
    tname = game.UNIT_TYPES.get(u["unit_type"], {}).get("name", u["unit_type"])
    await cq.message.edit_text(
        f"🏭 <b>{u['name']}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Тип: {tname}\n"
        f"Количество: {u['count']} ед.\n"
        f"Стоимость производства: {u['cost_gold']} 👑\n\n"
        "Каждая единица техники даёт +5 к силе атаки в бою.",
        reply_markup=unit_view_kb(uid), parse_mode="HTML"
    )


@router.callback_query(F.data == "unit_produce_list")
async def cb_unit_produce_list(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    units = await db.get_units(c["id"])
    if not units:
        await cq.answer("Сначала создайте технику!", show_alert=True)
        return
    await cq.message.edit_text(
        "🏭 <b>ПРОИЗВОДСТВО</b>\n\nВыберите, что производить:",
        reply_markup=unit_produce_kb(units), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("unit_produce:"))
async def cb_unit_produce(cq):
    await cq.answer()
    uid = int(cq.data.split(":")[1])
    u = await db.get_unit(uid)
    if not u: return
    c = await db.get_country(cq.from_user.id)
    if not c: return
    if c["gold"] < u["cost_gold"]:
        await cq.answer(f"❌ Нужно {u['cost_gold']} золота", show_alert=True)
        return
    new_gold = c["gold"] - u["cost_gold"]
    await db.update_country(cq.from_user.id, gold=new_gold)
    await db.update_unit(uid, count=u["count"] + 1)
    await cq.answer(f"✅ Произведена 1 единица {u['name']}", show_alert=True)
    await cb_units(cq)


@router.callback_query(F.data.startswith("unit_delete:"))
async def cb_unit_delete(cq):
    await cq.answer()
    uid = int(cq.data.split(":")[1])
    await db.delete_unit(uid)
    await cq.answer("✅ Техника удалена", show_alert=True)
    await cb_units(cq)


@router.callback_query(F.data.startswith("produce_page:"))
async def cb_produce_page(cq):
    await cq.answer()
    page = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c: return
    units = await db.get_units(c["id"])
    await cq.message.edit_text("🏭 <b>ПРОИЗВОДСТВО</b>", reply_markup=unit_produce_kb(units, page=page), parse_mode="HTML")


# ===================== CITIZENS (LEADER VIEW) =====================

@router.callback_query(F.data == "citizens")
async def cb_citizens(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    count = await db.get_citizen_count(c["id"])
    await cq.message.edit_text(
        f"👥 <b>ГРАЖДАНЕ</b>\n\n"
        f"Население вашей страны: {count} чел.\n"
        f"Максимум: {config.CITIZEN_MAX_PER_COUNTRY}\n\n"
        f"Каждый гражданин приносит +10 к доходу в час\n"
        f"и 5% его заработка уходит в казну.",
        reply_markup=citizens_kb(can_kick=count > 0, is_owner=True), parse_mode="HTML"
    )


@router.callback_query(F.data == "citizen_list")
async def cb_citizen_list(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    citizens = await db.get_citizens_of(c["id"])
    if not citizens:
        await cq.answer("Нет граждан!", show_alert=True)
        return
    role_name = {"citizen": "🔹 Гражданин", "minister": "⭐ Министр", "vice_president": "👑 Вице-президент"}
    lines = ["👥 <b>ГРАЖДАНЕ</b>\n━━━━━━━━━━━━━━━\n"]
    for i, cit in enumerate(citizens, 1):
        r = role_name.get(cit["role"], "🔹 Гражданин")
        name = cit["username"] or f"ID{cit['user_id']}"
        lines.append(f"{i}. {name} — {r} (💰 {cit['gold']})")
    await cq.message.edit_text("\n".join(lines), reply_markup=citizens_kb(True, True), parse_mode="HTML")


@router.callback_query(F.data == "citizen_promote_list")
async def cb_citizen_promote_list(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    citizens = await db.get_citizens_of(c["id"])
    citizens = [ct for ct in citizens if ct["role"] == "citizen"]
    if not citizens:
        await cq.answer("Нет граждан для повышения!", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for ct in citizens:
        name = ct["username"] or f"ID{ct['user_id']}"
        b.button(text=f"⭐ {name}", callback_data=f"citizen_promote:{ct['user_id']}")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    await cq.message.edit_text("Выберите гражданина для повышения:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("citizen_promote:"))
async def cb_citizen_promote(cq):
    await cq.answer()
    uid = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c: return
    await db.set_citizen_role(uid, c["id"], "minister")
    await cq.answer("✅ Гражданин повышен до Министра!", show_alert=True)
    await cb_citizens(cq)


@router.callback_query(F.data == "citizen_kick_list")
async def cb_citizen_kick_list(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    citizens = await db.get_citizens_of(c["id"])
    if not citizens:
        await cq.answer("Нет граждан!", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for ct in citizens:
        name = ct["username"] or f"ID{ct['user_id']}"
        b.button(text=f"🚫 {name}", callback_data=f"citizen_kick:{ct['user_id']}")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    await cq.message.edit_text("Выберите гражданина для исключения:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("citizen_kick:"))
async def cb_citizen_kick(cq):
    await cq.answer()
    uid = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c: return
    await db.kick_citizen(uid, c["id"])
    await cq.answer("✅ Гражданин исключён!", show_alert=True)
    await cb_citizens(cq)


# ===================== MAP =====================

@router.callback_query(F.data == "map")
async def cb_map(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    countries = await db.get_all_countries(order_by="army_level DESC", limit=50)
    lines = [f"🌍 <b>КАРТА МИРА</b> ({len(countries)} стран)\n━━━━━━━━━━━━━━━\n"]
    for i, cc in enumerate(countries, 1):
        marker = "⭐" if cc["id"] == c["id"] else "🏳"
        lines.append(f"{marker} {i}. <b>{cc['name']}</b> | 💰 {game.format_number(cc['gold'])} | 👥 {cc.get('population',0)}")
        if i >= 20:
            lines.append("\n... и другие")
            break
    await cq.message.edit_text("\n".join(lines), reply_markup=simple_kb(("🏠 Главная", "menu")), parse_mode="HTML")


# ===================== DIPLOMACY =====================

@router.callback_query(F.data == "diplomacy")
async def cb_diplomacy(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    alliance = await db.get_alliance_by_country(c["id"])
    in_all = alliance is not None
    is_owner = alliance is not None and alliance["owner_id"] == c["id"]
    if alliance:
        members = await db.get_alliance_members(alliance["id"])
        info = (
            "🤝 <b>ДИПЛОМАТИЯ</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"🏳 Альянс: <b>{alliance['name']}</b> [{alliance['tag']}]\n"
            f"👤 Участников: {len(members)}\n"
            f"📊 Бонус: +{len(members)*2}% к атаке/обороне"
        )
    else:
        info = (
            "🤝 <b>ДИПЛОМАТИЯ</b>\n"
            "━━━━━━━━━━━━━━━\n"
            "Вы не в альянсе.\n"
            "Создайте или вступите в альянс для бонусов!"
        )
    await cq.message.edit_text(info, reply_markup=diplomacy_kb(in_all, is_owner), parse_mode="HTML")


@router.callback_query(F.data == "my_alliance")
async def cb_my_alliance(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    alliance = await db.get_alliance_by_country(c["id"])
    if not alliance:
        await cq.message.edit_text("Вы не в альянсе.", reply_markup=diplomacy_kb(False))
        return
    members = await db.get_alliance_members(alliance["id"])
    lines = [f"🏳 <b>{alliance['name']}</b> [{alliance['tag']}]\n"]
    for m in members:
        ri = "👑" if m["role"] == "owner" else "⭐" if m["role"] == "admin" else "🔹"
        lines.append(f"{ri} <b>{m['name']}</b> — {game.format_number(m['gold'])} 👑")
    lines.append(f"\n👤 Всего: {len(members)}")
    is_owner = alliance["owner_id"] == c["id"]
    await cq.message.edit_text("\n".join(lines), reply_markup=diplomacy_kb(True, is_owner), parse_mode="HTML")


@router.callback_query(F.data == "alliance_list")
async def cb_alliance_list(cq):
    await cq.answer()
    alliances = await db.get_alliances_list()
    if not alliances:
        await cq.message.edit_text("Нет альянсов.", reply_markup=diplomacy_kb(False))
        return
    await cq.message.edit_text("📋 <b>СПИСОК АЛЬЯНСОВ</b>", reply_markup=alliance_list_kb(alliances), parse_mode="HTML")


@router.callback_query(F.data.startswith("alliance_page:"))
async def cb_alliance_page(cq):
    await cq.answer()
    page = int(cq.data.split(":")[1])
    alliances = await db.get_alliances_list()
    await cq.message.edit_text("📋 <b>СПИСОК АЛЬЯНСОВ</b>", reply_markup=alliance_list_kb(alliances, page=page), parse_mode="HTML")


@router.callback_query(F.data.startswith("alliance_view:"))
async def cb_alliance_view(cq):
    await cq.answer()
    aid = int(cq.data.split(":")[1])
    alliance = await db.get_alliance(aid)
    if not alliance: return
    members = await db.get_alliance_members(aid)
    c = await db.get_country(cq.from_user.id)
    in_this = any(m["id"] == c["id"] for m in members) if c else False
    lines = [f"🏳 <b>{alliance['name']}</b> [{alliance['tag']}]\n"]
    for m in members:
        ri = "👑" if m["role"] == "owner" else "🔹"
        lines.append(f"{ri} <b>{m['name']}</b>")
    b = InlineKeyboardBuilder()
    if c and not in_this:
        b.button(text="✅ Вступить", callback_data=f"alliance_join:{aid}")
    b.button(text="🏠 Главная", callback_data="menu")
    b.adjust(1)
    await cq.message.edit_text("\n".join(lines), reply_markup=b.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("alliance_join:"))
async def cb_alliance_join(cq):
    await cq.answer()
    aid = int(cq.data.split(":")[1])
    c = await db.get_country(cq.from_user.id)
    if not c: return
    if await db.is_in_alliance(c["id"]):
        await cq.answer("❌ Вы уже в альянсе!", show_alert=True)
        return
    ok = await db.join_alliance(aid, c["id"])
    if ok:
        await cq.answer("✅ Вы вступили в альянс!", show_alert=True)
        await cb_diplomacy(cq)
    else:
        await cq.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data == "alliance_leave_confirm")
async def cb_alliance_leave_confirm(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    alliance = await db.get_alliance_by_country(c["id"])
    if not alliance: return
    if alliance["owner_id"] == c["id"]:
        await cq.answer("👑 Владелец не может покинуть. Распустите альянс.", show_alert=True)
        return
    await cq.message.edit_text("❓ Покинуть альянс?", reply_markup=confirm_kb("alliance_leave", c["id"]))


@router.callback_query(F.data.startswith("alliance_leave:"))
async def cb_alliance_leave(cq):
    await cq.answer()
    await db.leave_alliance(int(cq.data.split(":")[1]))
    await cq.answer("✅ Вы покинули альянс", show_alert=True)
    await cb_diplomacy(cq)


@router.callback_query(F.data == "alliance_disband_confirm")
async def cb_alliance_disband_confirm(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    await cq.message.edit_text("❓ Распустить альянс?", reply_markup=confirm_kb("alliance_disband", c["id"]))


@router.callback_query(F.data.startswith("alliance_disband:"))
async def cb_alliance_disband(cq):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    alliance = await db.get_alliance_by_country(c["id"])
    if not alliance or alliance["owner_id"] != c["id"]:
        await cq.answer("❌ Только владелец", show_alert=True)
        return
    await db.disband_alliance(alliance["id"])
    await cq.answer("💔 Альянс распущен", show_alert=True)
    await cb_diplomacy(cq)


@router.callback_query(F.data == "alliance_create_start")
async def cb_alliance_create_start(cq, state: FSMContext):
    await cq.answer()
    c = await db.get_country(cq.from_user.id)
    if not c: return
    if await db.is_in_alliance(c["id"]):
        await cq.answer("❌ Вы уже в альянсе!", show_alert=True)
        return
    if c["gold"] < config.ALLIANCE_CREATE_COST:
        await cq.answer(f"❌ Нужно {game.format_number(config.ALLIANCE_CREATE_COST)} золота", show_alert=True)
        return
    await state.set_state(CreateAlliance.name)
    await state.update_data(alliance_name=None)
    await cq.message.edit_text(
        f"✨ <b>СОЗДАНИЕ АЛЬЯНСА</b>\n\n"
        f"Стоимость: {game.format_number(config.ALLIANCE_CREATE_COST)} 👑\n\n"
        "Название альянса:"
    )


@router.message(CreateAlliance.name)
async def ca_name(msg: Message, state: FSMContext):
    name = msg.text.strip()
    if len(name) < 2 or len(name) > 25:
        await msg.answer("Название от 2 до 25 символов.")
        return
    await state.update_data(alliance_name=name)
    await state.set_state(CreateAlliance.tag)
    await msg.answer("Тег альянса (2-5 букв, например ABC):")


@router.message(CreateAlliance.tag)
async def ca_tag(msg: Message, state: FSMContext):
    tag = msg.text.strip().upper()
    if len(tag) < 2 or len(tag) > 5:
        await msg.answer("Тег от 2 до 5 букв.")
        return
    if not re.match(r'^[A-Z]+$', tag):
        await msg.answer("Только латинские буквы.")
        return
    c = await db.get_country(msg.from_user.id)
    if not c or c["gold"] < config.ALLIANCE_CREATE_COST:
        await msg.answer("Недостаточно золота!")
        await state.clear()
        return
    data = await state.get_data()
    name = data.get("alliance_name")
    if not name:
        await msg.answer("Ошибка. Попробуйте снова.")
        await state.clear()
        return
    ok = await db.create_alliance(name, tag, c["id"])
    if not ok:
        await msg.answer("Альянс с таким названием или тегом уже существует!")
        await state.clear()
        return
    await db.update_country(msg.from_user.id, gold=c["gold"] - config.ALLIANCE_CREATE_COST)
    await state.clear()
    await msg.answer(
        f"🎉 Альянс <b>{name}</b> [{tag}] создан!",
        reply_markup=main_menu(), parse_mode="HTML"
    )


# ===================== TOP =====================

@router.callback_query(F.data == "top")
async def cb_top(cq):
    await cq.answer()
    await cq.message.edit_text("🏆 <b>РЕЙТИНГ</b>", reply_markup=top_kb(), parse_mode="HTML")


async def show_top(cq, order_by, label, val_label="💰"):
    await cq.answer()
    countries = await db.get_all_countries(order_by=order_by, limit=20)
    if not countries:
        return
    lines = [f"🏆 <b>ТОП ПО {label}</b>\n━━━━━━━━━━━━━━━\n"]
    for i, c in enumerate(countries, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        col = order_by.split()[0]
        val = c[col]
        if col == "currency_value":
            val = f"{val:.4f}"
        else:
            val = game.format_number(val)
        lines.append(f"{medal} <b>{c['name']}</b> — {val_label} {val}")
    await cq.message.edit_text("\n".join(lines), reply_markup=top_kb(), parse_mode="HTML")


@router.callback_query(F.data == "top_gold")
async def cb_top_gold(cq):
    await show_top(cq, "gold DESC", "ЗОЛОТУ", "💰")


@router.callback_query(F.data == "top_currency")
async def cb_top_currency(cq):
    await show_top(cq, "currency_value DESC", "КУРСУ ВАЛЮТЫ", "💱")


@router.callback_query(F.data == "top_population")
async def cb_top_pop(cq):
    await show_top(cq, "population DESC", "НАСЕЛЕНИЮ", "👥")


@router.callback_query(F.data == "top_wins")
async def cb_top_wins(cq):
    await show_top(cq, "wars_won DESC", "ПОБЕДАМ", "🏆")


# ===================== HELP =====================

@router.message(Command("help"))
@router.message(F.text.lower().in_(["помощь", "help", "команды"]))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 <b>ПОМОЩЬ ПО ИГРЕ</b>\n\n"
        "<b>КОМАНДЫ (можно без /):</b>\n"
        "🚀 <b>старт</b> — начать игру (создать страну или стать гражданином)\n"
        "🏠 <b>меню</b> — главное меню\n"
        "📊 <b>статистика</b> — статистика страны\n"
        "💱 <b>валюта</b> — валютный рынок\n"
        "🏭 <b>техника</b> — военная техника\n"
        "👥 <b>граждане</b> — управление гражданами\n"
        "🌍 <b>карта</b> — карта мира\n"
        "🏆 <b>рейтинг</b> — топ игроков\n"
        "📖 <b>помощь</b> — это сообщение\n\n"
        "<b>ВАЛЮТА:</b>\n"
        "• Каждая страна имеет свою валюту\n"
        "• <code>buy_currency USD 100</code> — купить валюту\n"
        "• <code>sell_currency USD 50</code> — продать валюту\n"
        "• Курс меняется от экономики и армии\n\n"
        "<b>ТЕХНИКА:</b>\n"
        "• Создайте свою технику с уникальным названием\n"
        "• Типы: Танк, Самолёт, Вертолёт, Корабль, БПЛА, РСЗО, ПВО, Ракета, Спецназ\n"
        "• Производите единицы техники за золото\n\n"
        "<b>ВОЙНА:</b>\n"
        "• Перед атакой показываются шансы на победу\n"
        "• Сила зависит от уровня войск и количества техники\n"
        "• Победитель забирает золото и регионы\n\n"
        "<b>ГРАЖДАНЕ:</b>\n"
        "• Игроки могут стать гражданами вашей страны\n"
        "• Граждане платят налоги (5% дохода)\n"
        "• Назначайте министров, исключайте нарушителей\n\n"
        "<b>АЛЬЯНСЫ:</b>\n"
        "• Создайте альянс за 1000 золота\n"
        "• Каждый участник даёт +2% к силе атаки и обороны",
        parse_mode="HTML", reply_markup=simple_kb(("🏠 Главная", "menu"))
    )


# ===================== TEXT COMMANDS (без слеша) =====================

@router.message(F.text.lower().in_(["старт", "start", "начать"]))
async def text_start(msg: Message, state: FSMContext):
    await state.clear()
    c = await db.get_country(msg.from_user.id)
    cit = await db.get_citizen(msg.from_user.id)
    if c:
        await msg.answer(f"🇺🇳 С возвращением, {c['name']}!", reply_markup=main_menu())
    elif cit:
        host = await db.get_country_by_id(cit["country_id"])
        hname = host["name"] if host else "?"
        await msg.answer(f"🏠 Вы гражданин {hname}", reply_markup=citizen_menu())
    else:
        await msg.answer("🏛 ДОБРО ПОЖАЛОВАТЬ!\nВыберите путь:", reply_markup=start_choice())


@router.message(F.text.lower().in_(["меню", "menu", "главная"]))
async def text_menu(msg: Message):
    c = await db.get_country(msg.from_user.id)
    cit = await db.get_citizen(msg.from_user.id)
    if c:
        await msg.answer("🏛 Главное меню:", reply_markup=main_menu())
    elif cit:
        await msg.answer("🏠 Меню:", reply_markup=citizen_menu())
    else:
        await msg.answer("Сначала /start", reply_markup=start_choice())


@router.message(F.text.lower().in_(["статистика", "stats", "stat"]))
async def text_stats(msg: Message):
    c = await db.get_country(msg.from_user.id)
    if not c:
        await msg.answer("Сначала создайте страну — /start")
        return
    citizens = await db.get_citizen_count(c["id"])
    units = await db.get_units(c["id"])
    total_units = sum(u["count"] for u in units)
    inc = game.calc_income(c, citizens)
    await msg.answer(
        "📊 <b>СТАТИСТИКА</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🇺🇳 Страна: {c['name']}\n"
        f"👑 Лидер: {c['leader_title']}\n"
        f"💱 Валюта: {c['currency_name']} ({c['currency_code']}) — {c['currency_value']}\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Золото: {game.format_number(c['gold'])} | 💎 Кристаллы: {c['crystals']}\n"
        f"⚔️ Вооружение: {c['army_level']} ур. | 🛡 Оборона: {c['defense_level']} ур.\n"
        f"🏭 Техники: {total_units} ед.\n"
        f"⛏ Шахта: {c['mine_level']} ур. | 🌾 Ферма: {c['farm_level']} ур.\n"
        f"🌍 Регионы: {c['regions']} | 👥 Граждан: {citizens}\n"
        f"📈 Доход/ч: {game.format_number(inc['per_hour'])}\n"
        f"🏆 Побед: {c['wars_won']} | 💔 Поражений: {c['wars_lost']}",
        parse_mode="HTML", reply_markup=stats_kb()
    )


@router.message(F.text.lower().in_(["валюта", "currency", "курс"]))
async def text_currency(msg: Message):
    c = await db.get_country(msg.from_user.id)
    if not c:
        await msg.answer("Сначала создайте страну — /start")
        return
    await msg.answer(
        f"💱 <b>ВАЛЮТНЫЙ РЫНОК</b>\n\n"
        f"Ваша валюта: {c['currency_name']} ({c['currency_code']})\n"
        f"Курс: 1 {c['currency_code']} = {c['currency_value']} 👑\n\n"
        f"<code>buy_currency USD 100</code> — купить\n"
        f"<code>sell_currency USD 50</code> — продать",
        parse_mode="HTML", reply_markup=currency_kb()
    )


@router.message(F.text.lower().in_(["техника", "армия", "войско"]))
async def text_units(msg: Message):
    c = await db.get_country(msg.from_user.id)
    if not c:
        await msg.answer("Сначала создайте страну — /start")
        return
    units = await db.get_units(c["id"])
    if not units:
        await msg.answer("🏭 У вас пока нет техники. Создайте в меню → Техника", reply_markup=main_menu())
    else:
        lines = ["🏭 <b>ВОЕННАЯ ТЕХНИКА</b>\n━━━━━━━━━━━━━━━\n"]
        for u in units:
            tname = game.UNIT_TYPES.get(u["unit_type"], {}).get("name", u["unit_type"])
            lines.append(f"• <b>{u['name']}</b> ({tname}) — {u['count']} ед.")
        await msg.answer("\n".join(lines), parse_mode="HTML", reply_markup=main_menu())


@router.message(F.text.lower().in_(["карта", "map", "мир"]))
async def text_map(msg: Message):
    c = await db.get_country(msg.from_user.id)
    if not c:
        await msg.answer("Сначала создайте страну — /start")
        return
    countries = await db.get_all_countries(order_by="gold DESC", limit=30)
    lines = [f"🌍 <b>КАРТА МИРА</b> ({len(countries)} стран)\n━━━━━━━━━━━━━━━\n"]
    for i, cc in enumerate(countries, 1):
        marker = "⭐" if cc["id"] == c["id"] else "🏳"
        lines.append(f"{marker} {i}. <b>{cc['name']}</b> — {game.format_number(cc['gold'])} 👑")
        if i >= 20:
            lines.append("\n... и другие")
            break
    await msg.answer("\n".join(lines), parse_mode="HTML", reply_markup=simple_kb(("🏠 Главная", "menu")))


@router.message(F.text.lower().in_(["рейтинг", "топ", "top", "rating"]))
async def text_top(msg: Message):
    await msg.answer("🏆 <b>РЕЙТИНГ</b>\nВыберите категорию:", reply_markup=top_kb(), parse_mode="HTML")


@router.message(F.text.lower().in_(["работа", "work", "зарплата"]))
async def text_work(msg: Message):
    cit = await db.get_citizen(msg.from_user.id)
    if not cit:
        await msg.answer("Вы не гражданин. /start")
        return
    gold_earn = config.CITIZEN_WORK_GOLD
    tax = int(gold_earn * config.CITIZEN_TAX_RATE)
    net = gold_earn - tax
    await db.update_citizen_gold(msg.from_user.id, cit["gold"] + net)
    host = await db.get_country_by_id(cit["country_id"])
    if host:
        await db.update_country(host["user_id"], gold=host["gold"] + tax)
    await msg.answer(
        f"💼 Вы поработали!\n💰 +{net} золота (налог {tax})",
        reply_markup=citizen_menu()
    )


# ===================== CATCH TEXT =====================

@router.message()
async def catch_text(msg: Message, state: FSMContext):
    st = await state.get_data()
    if st:
        return
    c = await db.get_country(msg.from_user.id)
    cit = await db.get_citizen(msg.from_user.id)
    text = msg.text.strip()

    if not c and not cit:
        await msg.answer("Создайте страну или станьте гражданином — /start")
        return

    if text.lower().startswith("buy "):
        try:
            amt = int(text.split()[1])
            if amt <= 0: return
            c = await db.get_country(msg.from_user.id)
            if not c: return
            if c["crystals"] < amt:
                await msg.answer(f"У вас только {c['crystals']} 💎")
                return
            gold = amt * config.CRYSTAL_TO_GOLD
            await db.update_country(msg.from_user.id, crystals=c["crystals"] - amt, gold=c["gold"] + gold)
            await msg.answer(f"💎 Обменяно {amt} кристаллов на {game.format_number(gold)} золота!", reply_markup=main_menu())
        except (ValueError, IndexError):
            await msg.answer("Формат: buy N")

    elif text.lower().startswith("buy_currency "):
        parts = text.split()
        if len(parts) < 3:
            await msg.answer("Формат: buy_currency CODE N")
            return
        try:
            code = parts[1].upper()
            amt = float(parts[2])
            if amt <= 0:
                await msg.answer("Положительное число")
                return
            c = await db.get_country(msg.from_user.id)
            if not c: return
            # find country with this currency code
            all_c = await db.get_all_countries_full(limit=200)
            target = None
            for cc in all_c:
                if cc["currency_code"] == code and cc["id"] != c["id"]:
                    target = cc
                    break
            if not target:
                await msg.answer(f"Валюта {code} не найдена!")
                return
            rate = target["currency_value"] * (1 + config.CURRENCY_TRADE_FEE)
            cost = int(amt * rate)
            if c["gold"] < cost:
                await msg.answer(f"Недостаточно золота! Нужно {cost}, у вас {c['gold']}")
                return
            new_gold = c["gold"] - cost
            await db.update_country(msg.from_user.id, gold=new_gold)
            await db.add_holding(c["id"], code, amt)
            await msg.answer(
                f"💱 Куплено {amt:.2f} {code} за {cost} 👑\n"
                f"Курс: {rate:.4f}",
                reply_markup=main_menu()
            )
        except (ValueError, IndexError):
            await msg.answer("Формат: buy_currency CODE N")

    elif text.lower().startswith("sell_currency "):
        parts = text.split()
        if len(parts) < 3:
            await msg.answer("Формат: sell_currency CODE N")
            return
        try:
            code = parts[1].upper()
            amt = float(parts[2])
            if amt <= 0:
                await msg.answer("Положительное число")
                return
            c = await db.get_country(msg.from_user.id)
            if not c: return
            holding = await db.get_holding(c["id"], code)
            if not holding or holding["amount"] < amt:
                await msg.answer(f"У вас только {holding['amount'] if holding else 0:.2f} {code}")
                return
            all_c = await db.get_all_countries_full(limit=200)
            target = None
            for cc in all_c:
                if cc["currency_code"] == code and cc["id"] != c["id"]:
                    target = cc
                    break
            rate = (target["currency_value"] if target else 1.0) * (1 - config.CURRENCY_TRADE_FEE)
            gold_gain = int(amt * rate)
            new_gold = c["gold"] + gold_gain
            await db.update_country(msg.from_user.id, gold=new_gold)
            await db.remove_holding(c["id"], code, amt)
            await msg.answer(
                f"💰 Продано {amt:.2f} {code} за {gold_gain} 👑\n"
                f"Курс: {rate:.4f}",
                reply_markup=main_menu()
            )
        except (ValueError, IndexError):
            await msg.answer("Формат: sell_currency CODE N")

    else:
        await msg.answer("Используйте кнопки меню.", reply_markup=main_menu() if c else citizen_menu())



async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    await init_db()
    if not BOT_TOKEN:
        print("ERROR: Insert your bot token in BOT_TOKEN at the top of this file")
        return
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    logging.info("Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
