import functools
import logging
import asyncio
import math
from datetime import datetime, timedelta
from typing import Callable, Any, Optional
import discord

from bot import config

logger = logging.getLogger(__name__)


def format_number(number: int) -> str:
    """Format large numbers with appropriate suffixes"""
    if number < 1000:
        return str(number)
    elif number < 1000000:
        return f"{number/1000:.1f}K"
    elif number < 1000000000:
        return f"{number/1000000:.1f}M"
    else:
        return f"{number/1000000000:.1f}B"


def create_embed(title: str, description: str, color: discord.Color = None) -> discord.Embed:
    """Create a standardized embed for bot responses"""
    if color is None:
        color = discord.Color.blue()
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now()
    )
    return embed


async def run_in_executor(func: Callable, *args, **kwargs) -> Any:
    """Run a blocking function in a threadpool and return the result."""
    return await asyncio.to_thread(func, *args, **kwargs)


def check_cooldown_decorator(minutes: int = 5):
    """Decorator for prefix + slash commands with database-backed cooldowns."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, ctx_or_interaction, *args, **kwargs):
            is_interaction = isinstance(ctx_or_interaction, discord.Interaction)
            if is_interaction:
                user_id = str(ctx_or_interaction.user.id)
            else:
                user_id = str(getattr(ctx_or_interaction, "author").id)

            command_name = func.__name__

            try:
                last_used = await run_in_executor(self.db.get_command_cooldown, user_id, command_name)
            except Exception:
                logger.exception("Failed to fetch cooldown from DB")
                last_used = None

            if last_used:
                cooldown_expiry = last_used + timedelta(minutes=minutes)
                time_left = cooldown_expiry - datetime.utcnow()
                if time_left.total_seconds() > 0:
                    time_str = format_time_duration(time_left)
                    embed = create_embed(
                        "⏰ Command on Cooldown",
                        f"You must wait **{time_str}** before using this command again.",
                        discord.Color.orange()
                    )
                    try:
                        if is_interaction:
                            try:
                                if not ctx_or_interaction.response.is_done():
                                    await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
                                else:
                                    await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
                            except Exception:
                                try:
                                    channel = await run_in_executor(self.bot.fetch_channel, ctx_or_interaction.channel_id)
                                    if channel:
                                        await channel.send(embed=embed)
                                except Exception:
                                    logger.exception("Failed to deliver cooldown message for interaction")
                        else:
                            await ctx_or_interaction.send(embed=embed)
                    except Exception:
                        logger.exception("Failed to send cooldown message")
                    return

            try:
                result = await func(self, ctx_or_interaction, *args, **kwargs)
                try:
                    await run_in_executor(self.db.set_command_cooldown, user_id, command_name, datetime.utcnow())
                except Exception:
                    logger.exception("Failed to set cooldown in DB")
                return result
            except Exception as e:
                logger.exception(f"Error in command {command_name}: {e}")
                embed = create_embed(
                    "❌ Command Error",
                    "An error occurred while executing this command. Please try again or contact an admin.",
                    discord.Color.red()
                )
                try:
                    if is_interaction:
                        try:
                            if not ctx_or_interaction.response.is_done():
                                await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
                            else:
                                await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
                        except Exception:
                            try:
                                await ctx_or_interaction.user.send(embed=embed)
                            except Exception:
                                logger.exception("Failed to deliver error message to interaction user")
                    else:
                        await ctx_or_interaction.send(embed=embed)
                except Exception:
                    logger.exception("Failed to send command error message")
        return wrapper
    return decorator


def format_time_duration(delta: timedelta) -> str:
    """Format a timedelta into a readable string"""
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds} seconds"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        if seconds > 0:
            return f"{minutes} minutes, {seconds} seconds"
        return f"{minutes} minutes"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if minutes > 0:
            return f"{hours} hours, {minutes} minutes"
        return f"{hours} hours"


def get_ascii_art(art_type: str) -> str:
    """Get ASCII art for various occasions"""
    art_collection = {
        "civilization_start": """
    ╔══════════════════════════════════════╗
    ║        🏛️  CIVILIZATION BORN  🏛️        ║
    ║    From humble beginnings arise      ║
    ║       great civilizations...        ║
    ║         ⚡ ⭐ DESTINY AWAITS ⭐ ⚡        ║
    ╚══════════════════════════════════════╝
        """,
        "war_declaration": """
    ⚔️ ═══════════════════════════════════ ⚔️
       🔥 THE DRUMS OF WAR THUNDER 🔥
         Armies march to battle!
         Steel clashes with steel!
    ⚔️ ═══════════════════════════════════ ⚔️
        """,
        "victory": """
    🏆 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 🏆
         ⭐ GLORIOUS VICTORY! ⭐
    🏆 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 🏆
        """,
        "nuclear_blast": """
    ☢️ ████████████████████████████████ ☢️
       💥 NUCLEAR DEVASTATION 💥
    ☢️ ████████████████████████████████ ☢️
        """,
        "black_market": """
    🕴️ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 🕴️
        💀 BLACK MARKET DEALINGS 💀
          💰 Gold for Power 💰
    🕴️ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 🕴️
        """,
        "alliance": """
    🤝 ╭─────────────────────────────────╮ 🤝
      │    ⚖️ DIPLOMATIC ALLIANCE ⚖️     │
      │     "United we stand"           │
    🤝 ╰─────────────────────────────────╯ 🤝
        """,
        "technology": """
    🔬 ┌───────────────────────────────┐ 🔬
      │    ⚡ TECHNOLOGICAL LEAP ⚡     │
    🔬 └───────────────────────────────┘ 🔬
        """
    }
    return art_collection.get(art_type, "")


def calculate_percentage_change(old_value: int, new_value: int) -> str:
    if old_value == 0:
        return "+∞%" if new_value > 0 else "0%"
    change = ((new_value - old_value) / old_value) * 100
    if change > 0:
        return f"+{change:.1f}%"
    return f"{change:.1f}%"


def get_civilization_rank(power_score: int) -> tuple[str, str]:
    if power_score < 500:
        return "Hamlet", "🏘️"
    elif power_score < 1500:
        return "Village", "🏡"
    elif power_score < 3000:
        return "Town", "🏘️"
    elif power_score < 6000:
        return "City", "🏙️"
    elif power_score < 12000:
        return "City-State", "🏛️"
    elif power_score < 25000:
        return "Kingdom", "👑"
    elif power_score < 50000:
        return "Empire", "⚜️"
    elif power_score < 100000:
        return "Superpower", "🌟"
    else:
        return "Galactic Empire", "🌌"


def get_happiness_status(happiness: int) -> tuple[str, str]:
    if happiness >= 90:
        return "Ecstatic", "🤩"
    elif happiness >= 80:
        return "Very Happy", "😄"
    elif happiness >= 70:
        return "Happy", "😊"
    elif happiness >= 60:
        return "Content", "😐"
    elif happiness >= 50:
        return "Neutral", "😑"
    elif happiness >= 40:
        return "Unhappy", "😞"
    elif happiness >= 30:
        return "Very Unhappy", "😢"
    elif happiness >= 20:
        return "Miserable", "😭"
    elif happiness >= 0:
        return "Revolt Risk", "😡"
    else:
        return "Collapse Imminent", "💀"


def get_hunger_status(hunger: int) -> tuple[str, str]:
    if hunger <= 10:
        return "Well Fed", "😋"
    elif hunger <= 25:
        return "Satisfied", "🙂"
    elif hunger <= 50:
        return "Hungry", "😕"
    elif hunger <= 75:
        return "Very Hungry", "😰"
    else:
        return "Starving", "💀"


def get_military_strength_description(soldiers: int, spies: int, tech_level: int) -> str:
    total_strength = soldiers + (spies * 2) + (tech_level * 50)
    if total_strength < 100:
        return "Defenseless"
    elif total_strength < 300:
        return "Weak"
    elif total_strength < 600:
        return "Modest"
    elif total_strength < 1200:
        return "Strong"
    elif total_strength < 2500:
        return "Formidable"
    elif total_strength < 5000:
        return "Mighty"
    else:
        return "Legendary"


def validate_user_mention(mention: str) -> Optional[str]:
    if mention.startswith('<@') and mention.endswith('>'):
        user_id = mention[2:-1]
        if user_id.startswith('!'):
            user_id = user_id[1:]
        return user_id
    return None


def get_resource_efficiency_bonus(ideology: str, action_type: str) -> float:
    ideology_bonuses = {
        "fascism": {"military": 1.15, "resource_extraction": 1.05},
        "democracy": {"trade": 1.20, "happiness": 1.15, "taxation": 1.10},
        "communism": {"production": 1.15, "citizen_efficiency": 1.10},
        "theocracy": {"happiness": 1.10, "propaganda": 1.15},
        "anarchy": {"chaos_resistance": 1.25, "unpredictability": 2.0}
    }
    return ideology_bonuses.get(ideology, {}).get(action_type, 1.0)


def format_civilization_summary(civ_data: dict) -> str:
    resources = civ_data.get('resources', {})
    population = civ_data.get('population', {})
    military = civ_data.get('military', {})
    gold = resources.get('gold', 0)
    citizens = population.get('citizens', 0)
    happiness = population.get('happiness', 50)
    soldiers = military.get('soldiers', 0)
    tech_level = military.get('tech_level', 0)
    power_score = sum(resources.values()) + citizens * 2 + soldiers * 5 + tech_level * 100
    rank, rank_emoji = get_civilization_rank(power_score)
    happiness_status, happiness_emoji = get_happiness_status(happiness)
    return (
        f"{rank_emoji} **{civ_data.get('name','Unknown')}** ({rank})\n"
        f"💰 {format_number(gold)} Gold | 👤 {format_number(citizens)} Citizens | {happiness_emoji} {happiness_status}\n"
        f"⚔️ Soldiers: {format_number(soldiers)} | 🔬 Tech Level: {tech_level} | Power: {format_number(power_score)}"
    )


def create_progress_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "▓" * length
    filled = int((current / maximum) * length)
    filled = max(0, min(length, filled))
    bar = "▓" * filled + "░" * (length - filled)
    return f"[{bar}] {current}/{maximum}"


def get_random_flavor_text(category: str) -> str:
    flavor_texts = {
        "victory": ["Victory belongs to the bold!", "Another triumph for the history books!", "Glory to the victorious!"],
        "defeat": ["Even the mighty can fall...", "A temporary setback!", "Rise again, stronger than before!"],
        "trade": ["Commerce is the lifeblood of civilization!", "A deal beneficial to all!", "The market is pleased!"],
        "diplomacy": ["The pen truly is mightier than the sword.", "Diplomacy opens new possibilities!", "Peace through understanding!"]
    }
    import random
    return random.choice(flavor_texts.get(category, ["Fortune favors the prepared!"]))


class CooldownManager:
    def __init__(self, db):
        self.db = db

    def set_dynamic_cooldown(self, user_id: str, command: str, base_minutes: int, modifiers: dict = None):
        final_minutes = base_minutes
        if modifiers:
            if modifiers.get('ideology') == 'fascism' and 'military' in command:
                final_minutes = int(final_minutes * 0.8)
            elif modifiers.get('ideology') == 'democracy' and 'trade' in command:
                final_minutes = int(final_minutes * 0.9)
            tech_level = modifiers.get('tech_level', 1)
            if tech_level >= 5:
                final_minutes = int(final_minutes * 0.9)
        self.db.set_cooldown(user_id, command, final_minutes)

    def get_cooldown_with_context(self, user_id: str, command: str) -> dict:
        expiry = self.db.check_cooldown(user_id, command)
        if not expiry:
            return {"on_cooldown": False}
        time_left = expiry - datetime.now()
        if time_left.total_seconds() <= 0:
            return {"on_cooldown": False}
        return {
            "on_cooldown": True,
            "time_left": time_left,
            "formatted_time": format_time_duration(time_left),
            "expires_at": expiry
        }


# ================================================================
#           POWER CURVE: THE CLIMB (not the spike)
# ================================================================
# Territory gives diminishing returns. The cap was 3.0x (spike);
# now it's 1.5x (climb). At 1M km² you get 1.75x instead of 2.6x.
def get_territory_modifier(land_size: int) -> float:
    """
    Diminishing returns on land size for resource generation.
    NERFED: coefficient 0.8 -> 0.25, cap 3.0 -> 1.5.
    """
    if land_size <= 0:
        return 1.0
    coeff = config.POWER_CURVE.get("territory_coefficient", 0.25)
    cap = config.POWER_CURVE.get("territory_cap", 1.5)
    factor = coeff * math.log10(land_size / 1000 + 1)
    return min(1.0 + factor, cap)


# ================================================================
#                     FACTION HELPERS
# ================================================================
def get_faction_emoji(faction: str) -> str:
    return config.FACTIONS.get(faction, {}).get("emoji", "❓")


def get_faction_status_emoji(value: int) -> str:
    """Return an emoji describing faction health."""
    if value <= 10:
        return "🔴"  # danger
    elif value <= 20:
        return "🟠"  # warning
    elif value >= 80:
        return "🟢"  # blessing
    elif value >= 60:
        return "🟩"  # healthy
    else:
        return "🟡"  # neutral


def format_faction_line(faction: str, value: int) -> str:
    """One-line display: '⚔️ Military: 45/100 🟡'"""
    meta = config.FACTIONS.get(faction, {})
    name = meta.get("name", faction.capitalize())
    emoji = meta.get("emoji", "❓")
    status = get_faction_status_emoji(value)
    return f"{emoji} **{name}**: {value}/100 {status}"


def format_faction_summary(factions: dict) -> str:
    """Multi-line display of all three factions."""
    lines = []
    for fkey in ("military", "merchant", "people"):
        lines.append(format_faction_line(fkey, factions.get(fkey, 50)))
    return "\n".join(lines)


def get_faction_warning(faction: str, value: int) -> Optional[str]:
    """Return a warning string if a faction is dangerously low."""
    meta = config.FACTIONS.get(faction, {})
    name = meta.get("name", faction.capitalize())
    danger = meta.get("danger_threshold", 10)
    warning = meta.get("warning_threshold", 20)
    if value <= danger:
        return f"🔴 **{name} is in open revolt!** (value {value})"
    elif value <= warning:
        return f"🟠 **{name} unrest is rising.** (value {value})"
    return None


def get_all_faction_warnings(factions: dict) -> list:
    """Return warnings for every low faction."""
    warnings = []
    for fkey in ("military", "merchant", "people"):
        w = get_faction_warning(fkey, factions.get(fkey, 50))
        if w:
            warnings.append(w)
    return warnings


# ================================================================
#                     DAILY LIMIT (DISABLED)
# ================================================================
# No-op decorator kept for import compatibility. Does NOT enforce any limit.
def daily_limit_decorator(command_name: str = None):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator
