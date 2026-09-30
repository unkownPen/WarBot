import random
import asyncio
import math
import json
import os
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, List, Dict, Any

import discord
from discord.ext import commands
from discord import app_commands

from bot.utils import (
    format_number, create_embed, get_territory_modifier, daily_limit_decorator,
)
from bot import config

# Terrain helpers from territory.py
try:
    from bot.commands.territory import (
        aggregate_sector_modifier,
        get_province_climate_data,
        PROVINCE_AREAS,
    )
except Exception:
    def aggregate_sector_modifier(provinces, sector):
        return 1.0
    def get_province_climate_data(province):
        return None
    PROVINCE_AREAS = {}

logger = logging.getLogger(__name__)


# =====================================================================
# HELPERS
# =====================================================================
def _uid(ctx) -> str:
    """Return the invoking user's ID as a string (works for both ctx types)."""
    if isinstance(ctx, discord.Interaction):
        return str(ctx.user.id)
    return str(ctx.author.id)


async def _reply(ctx, content: str = None, embed: discord.Embed = None, **kwargs):
    """Reply to a message or interaction uniformly."""
    try:
        if isinstance(ctx, discord.Interaction):
            if not ctx.response.is_done():
                await ctx.response.send_message(content=content, embed=embed, **kwargs)
            else:
                await ctx.followup.send(content=content, embed=embed, **kwargs)
        else:
            await ctx.send(content=content, embed=embed, **kwargs)
    except Exception:
        logger.exception("Failed to reply")


class CommandUsageError(Exception):
    """Raised when a command has a usage error.

    Commands that raise this will NOT trigger a cooldown or side effects.
    """
    pass


# =====================================================================
# COOLDOWN DECORATOR — respects usage errors
# =====================================================================
def check_cooldown_decorator(command_name: str):
    """Decorator that enforces cooldowns but ONLY on successful execution.

    Rules:
    - Usage errors (CommandUsageError) → no cooldown, no side effects
    - Runtime errors → no cooldown, error logged
    - Success → cooldown set
    - Testing mode → cooldown bypassed entirely
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            # Testing mode bypasses everything
            try:
                if self.db.get_testing_mode():
                    return await func(self, ctx, *args, **kwargs)
            except Exception:
                pass

            minutes = config.COOLDOWNS.get(command_name, 0)
            user_id = _uid(ctx)

            # Cooldown check (only if a cooldown is defined)
            if minutes > 0:
                last_used = self.db.get_command_cooldown(user_id, command_name)
                if last_used:
                    cooldown_end = last_used + timedelta(minutes=minutes)
                    if datetime.utcnow() < cooldown_end:
                        remaining = cooldown_end - datetime.utcnow()
                        mins = int(remaining.total_seconds() // 60)
                        secs = int(remaining.total_seconds() % 60)
                        await _reply(ctx, f"⏳ Please wait **{mins}m {secs}s** before using this command again!")
                        return

            # Execute the command, but DO NOT set cooldown on errors
            try:
                result = await func(self, ctx, *args, **kwargs)
            except CommandUsageError as e:
                # Usage error — clean message, no cooldown
                await _reply(ctx, f"❌ {e}")
                return
            except Exception as e:
                logger.exception(f"Runtime error in {command_name}")
                await _reply(ctx, "❌ Something went wrong while running that command. Please try again.")
                return

            # Success — set cooldown (if the command has one)
            if minutes > 0:
                try:
                    self.db.set_command_cooldown(user_id, command_name, datetime.utcnow())
                except Exception:
                    logger.exception("Failed to set cooldown")
            return result
        return wrapper
    return decorator


# =====================================================================
# ECONOMY COG
# =====================================================================
class EconomyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self._tasks: List[asyncio.Task] = []

    async def cog_load(self):
        self._tasks.append(asyncio.create_task(self._investment_bank_loop()))
        self._tasks.append(asyncio.create_task(self._market_restock_loop()))

    async def cog_unload(self):
        for t in self._tasks:
            try:
                t.cancel()
            except Exception:
                pass

    # =================================================================
    # CORE HELPERS
    # =================================================================
    def _is_sanctioned(self, user_id: str) -> bool:
        try:
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                return False
            now = datetime.utcnow()
            for s in (civ.get('received_sanctions') or []):
                exp = s.get('expires_at')
                if exp:
                    try:
                        if datetime.fromisoformat(exp) > now:
                            return True
                    except Exception:
                        continue
            return False
        except Exception as e:
            logger.error(f"_is_sanctioned error for {user_id}: {e}")
            return False

    def _apply_lucky_strike_gain(self, user_id: str, gains: Dict[str, int]):
        try:
            if not gains:
                return gains, False
            if not self.civ_manager.consume_lucky_strike(user_id):
                return gains, False
            doubled = {k: int(v * 2) for k, v in gains.items()}
            return doubled, True
        except Exception as e:
            logger.error(f"_apply_lucky_strike_gain error for {user_id}: {e}")
            return gains, False

    def _apply_sanction_penalty(self, user_id: str, gains: Dict[str, int]) -> Dict[str, int]:
        try:
            if not gains:
                return gains
            if not self._is_sanctioned(user_id):
                return gains
            return {k: int(v * 0.75) for k, v in gains.items()}
        except Exception as e:
            logger.error(f"_apply_sanction_penalty error for {user_id}: {e}")
            return gains

    def _tech_mult(self, action_key: str, tech_level: int) -> float:
        per_level = config.POWER_CURVE.get(f"tech_{action_key}_per_level", 0.015)
        return 1 + (tech_level * per_level)

    def _faction_mult(self, user_id: str, action_type: str) -> float:
        try:
            bless = self.civ_manager.get_faction_blessing_modifier(user_id, action_type)
            bane = self.civ_manager.get_faction_bane_modifier(user_id, action_type)
            return bless * bane
        except Exception:
            return 1.0

    # =================================================================
    # WORKFORCE HELPERS
    # =================================================================
    def _workforce_state(self, user_id: str) -> Dict[str, int]:
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return {"farming": 0, "mining": 0, "industry": 0, "trade": 0}
        wf = civ.get('workforce') or {}
        return {s: int(wf.get(s, 0)) for s in config.WORKFORCE['sectors'].keys()}

    def _total_assigned(self, wf: Dict[str, int]) -> int:
        return sum(wf.values())

    def _max_assignable(self, civ: Dict[str, Any]) -> int:
        citizens = civ['population']['citizens']
        return max(0, citizens - config.WORKFORCE['min_unassigned'])

    def _sector_yield(self, sector: str, workers: int) -> float:
        """Apply diminishing returns to a sector's raw workforce yield."""
        if workers <= 0:
            return 0.0
        sec_data = config.WORKFORCE['sectors'].get(sector)
        if not sec_data:
            return 0.0
        base = sec_data['base_yield_per_worker']
        total = 0.0
        remaining = workers
        prev_cap = 0
        for tier in config.WORKFORCE['tiers']:
            cap = tier['up_to']
            if cap is None:
                chunk = remaining
            else:
                chunk = min(remaining, max(0, cap - prev_cap))
            if chunk <= 0:
                if cap is not None:
                    prev_cap = cap
                continue
            total += chunk * base * tier['mult']
            remaining -= chunk
            if cap is not None:
                prev_cap = cap
            if remaining <= 0:
                break
        return total

    def _effective_sector_modifier(self, user_id: str, sector: str) -> float:
        """Ideology × terrain modifier for a given sector."""
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return 1.0
        ideology = civ.get('ideology', '') or ''
        ideo_mods = config.WORKFORCE['ideology_mods'].get(ideology, {})
        ideo_mult = ideo_mods.get(sector, 1.0)
        owned = self.db.get_player_territories(user_id)
        terrain_mult = aggregate_sector_modifier(owned, sector)
        return ideo_mult * terrain_mult

    def _tool_bonus(self, user_id: str, command_key: str) -> float:
        """Sum of all owned-tool bonuses that apply to a specific command."""
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return 0.0
        owned_tools = civ.get('tools') or []
        bonus = 0.0
        for tool_key in owned_tools:
            tool = config.TOOLS.get(tool_key)
            if not tool:
                continue
            bonus += tool.get('boosts', {}).get(command_key, 0.0)
        return bonus

    def _compute_sector_output(self, user_id: str, sector: str,
                                command_key: str, civ: Dict[str, Any]) -> Dict[str, Any]:
        """Full sector-based yield for a command.

        Returns: {
            "workers": int,
            "base_yield": float,     # from workforce
            "modifier": float,       # ideology * terrain
            "tool_bonus": float,     # additive
            "final_mult": float,     # modifier * (1 + tool_bonus)
            "tech_mult": float,
            "employment_factor": float,
            "territory_factor": float,
        }
        """
        wf = self._workforce_state(user_id)
        workers = wf.get(sector, 0)
        base_yield = self._sector_yield(sector, workers)
        modifier = self._effective_sector_modifier(user_id, sector)
        tool_bonus = self._tool_bonus(user_id, command_key)
        tech_mult = self._tech_mult(command_key, civ['military']['tech_level'])
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * 0.4
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        final_mult = modifier * (1 + tool_bonus) * tech_mult * employment_factor * territory_factor
        return {
            "workers": workers,
            "base_yield": base_yield,
            "modifier": modifier,
            "tool_bonus": tool_bonus,
            "final_mult": final_mult,
            "tech_mult": tech_mult,
            "employment_factor": employment_factor,
            "territory_factor": territory_factor,
        }

    # =================================================================
    # WORKFORCE COMMANDS
    # =================================================================
    @commands.hybrid_command(name='workforce')
    async def workforce(self, ctx):
        """View your sector-based workforce."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first! Use `.start <name>`")

        wf = self._workforce_state(user_id)
        citizens = civ['population']['citizens']
        assigned = self._total_assigned(wf)
        unemployed = citizens - assigned

        embed = create_embed(
            "👥 Workforce Sectors",
            f"**Citizens:** {format_number(citizens)}\n"
            f"**Assigned:** {format_number(assigned)}\n"
            f"**Unassigned:** {format_number(unemployed)} (min {config.WORKFORCE['min_unassigned']} reserved)\n"
            f"**Ideology:** {civ.get('ideology', 'none').capitalize()}",
            discord.Color.blue(),
        )

        for sector_key, sector_data in config.WORKFORCE['sectors'].items():
            workers = wf.get(sector_key, 0)
            base = self._sector_yield(sector_key, workers)
            mod = self._effective_sector_modifier(user_id, sector_key)
            total = base * mod
            # Tier breakdown
            tier_parts = []
            remaining = workers
            prev_cap = 0
            for tier in config.WORKFORCE['tiers']:
                cap = tier['up_to']
                chunk = remaining if cap is None else min(remaining, max(0, cap - prev_cap))
                if chunk > 0:
                    tier_parts.append(f"{chunk}×{tier['mult']:.2f}")
                    remaining -= chunk
                if cap is not None:
                    prev_cap = cap
                if remaining <= 0:
                    break
            tier_str = " + ".join(tier_parts) if tier_parts else "—"
            embed.add_field(
                name=f"{sector_data['emoji']} {sector_data['name']} — {workers} workers",
                value=(f"*{sector_data['desc']}*\n"
                       f"Base yield: **{format_number(int(base))}**\n"
                       f"× Modifier: **{mod:.2f}** (ideology × terrain)\n"
                       f"**Final: {format_number(int(total))} {sector_data['primary_resource']}/action**\n"
                       f"Tiers: `{tier_str}`"),
                inline=False,
            )

        embed.set_footer(text="Assign workers with .assign <sector> <amount>")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='assign')
    @app_commands.describe(sector="Sector to assign workers to", amount="Number of workers to assign")
    @app_commands.choices(sector=[
        app_commands.Choice(name="farming", value="farming"),
        app_commands.Choice(name="mining", value="mining"),
        app_commands.Choice(name="industry", value="industry"),
        app_commands.Choice(name="trade", value="trade"),
    ])
    async def assign(self, ctx, sector: str = None, amount: int = None):
        """Assign unassigned citizens to a sector."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        if not sector or sector not in config.WORKFORCE['sectors']:
            valid = ", ".join(f"`{s}`" for s in config.WORKFORCE['sectors'].keys())
            raise CommandUsageError(f"Invalid sector. Choose: {valid}")
        if amount is None or amount < 1:
            raise CommandUsageError("Specify an amount ≥ 1.")

        wf = self._workforce_state(user_id)
        assigned = self._total_assigned(wf)
        max_assignable = self._max_assignable(civ)
        available = max_assignable - assigned
        if amount > available:
            raise CommandUsageError(
                f"Only **{available}** workers available. "
                f"(Total {max_assignable} assignable, {assigned} already assigned.)"
            )

        wf[sector] = wf.get(sector, 0) + amount
        self.db.update_civilization(user_id, {"workforce": wf})
        self.civ_manager._invalidate_civ(user_id)

        sector_data = config.WORKFORCE['sectors'][sector]
        # Faction drift for the sector
        try:
            faction_map = {"farming": "assign_farming", "mining": "assign_mining",
                           "industry": "assign_industry", "trade": "assign_trade"}
            self.civ_manager.apply_faction_effects(user_id, faction_map.get(sector, "assign_farming"))
        except Exception:
            pass

        await ctx.send(embed=create_embed(
            f"✅ Assigned {amount} to {sector_data['emoji']} {sector_data['name']}",
            f"New total in sector: **{wf[sector]}**\n"
            f"Unassigned: **{max_assignable - self._total_assigned(wf)}**",
            discord.Color.green(),
        ))

    @commands.hybrid_command(name='unassign')
    @app_commands.describe(sector="Sector to pull workers from", amount="Number of workers to unassign")
    @app_commands.choices(sector=[
        app_commands.Choice(name="farming", value="farming"),
        app_commands.Choice(name="mining", value="mining"),
        app_commands.Choice(name="industry", value="industry"),
        app_commands.Choice(name="trade", value="trade"),
    ])
    async def unassign(self, ctx, sector: str = None, amount: int = None):
        """Pull workers out of a sector."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        if not sector or sector not in config.WORKFORCE['sectors']:
            raise CommandUsageError(f"Invalid sector.")
        if amount is None or amount < 1:
            raise CommandUsageError("Specify an amount ≥ 1.")

        wf = self._workforce_state(user_id)
        current = wf.get(sector, 0)
        if amount > current:
            raise CommandUsageError(f"Only **{current}** workers are in {sector}.")

        wf[sector] = current - amount
        self.db.update_civilization(user_id, {"workforce": wf})
        self.civ_manager._invalidate_civ(user_id)

        sector_data = config.WORKFORCE['sectors'][sector]
        await ctx.send(embed=create_embed(
            f"✅ Unassigned {amount} from {sector_data['emoji']} {sector_data['name']}",
            f"New total in sector: **{wf[sector]}**",
            discord.Color.green(),
        ))

    # =================================================================
    # PASSIVE INCOME — investment bank loop
    # =================================================================
    async def _investment_bank_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(config.BANKING['tick_interval_seconds'])
            try:
                for civ in self.db.get_all_civilizations():
                    uid = civ['user_id']
                    bank = civ.get('bank') or {}
                    deposits = int(bank.get('deposits', 0))
                    loan = int(bank.get('loan', 0))
                    credit = int(bank.get('credit_score', 100))
                    locked = bank.get('locked_until')
                    changed = False

                    if locked:
                        try:
                            if datetime.fromisoformat(locked) <= datetime.utcnow():
                                bank['locked_until'] = None
                                changed = True
                        except Exception:
                            pass

                    if deposits > 0:
                        interest = int(deposits * config.BANKING['deposit_rate'])
                        if interest > 0:
                            bank['deposits'] = deposits + interest
                            changed = True

                    if loan > 0:
                        bank['loan'] = int(loan * (1 + config.BANKING['loan_rate']))
                        changed = True
                        opened = bank.get('loan_opened_at')
                        if opened:
                            try:
                                age_days = (datetime.utcnow() - datetime.fromisoformat(opened)).days
                                if age_days >= config.BANKING['default_days']:
                                    bank['deposits'] = 0
                                    bank['loan'] = 0
                                    bank['loan_opened_at'] = None
                                    bank['credit_score'] = max(0, credit - 50)
                                    bank['locked_until'] = (
                                        datetime.utcnow() + timedelta(days=config.BANKING['bank_ban_days'])
                                    ).isoformat()
                                    changed = True
                                    self.db.log_event(uid, "bank_default", "Bank Default",
                                                      f"Loan unpaid {age_days}d.")
                                    self.civ_manager.apply_faction_effects(uid, "bank_default")
                            except Exception:
                                pass

                    if changed:
                        self.db.update_civilization(uid, {"bank": bank})
                        self.civ_manager._invalidate_civ(uid)
            except Exception as e:
                logger.error(f"Bank loop error: {e}")

    # =================================================================
    # MARKET — NPC shop, 48h restock
    # =================================================================
    async def _market_restock_loop(self):
        await self.bot.wait_until_ready()
        # Initial restock if missing
        try:
            await self._ensure_market_state()
        except Exception as e:
            logger.error(f"Initial market state failed: {e}")

        while not self.bot.is_closed():
            try:
                await asyncio.sleep(300)  # check every 5 min
                await self._check_market_restock()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Market restock loop error: {e}")
                await asyncio.sleep(60)

    async def _ensure_market_state(self):
        ref = self.db.client.collection("config").document("market_state")
        doc = ref.get()
        if not doc.exists:
            await self._restock_market()

    async def _check_market_restock(self):
        ref = self.db.client.collection("config").document("market_state")
        doc = ref.get()
        if not doc.exists:
            await self._restock_market()
            return
        data = doc.to_dict()
        next_at = data.get("next_restock_at")
        if not next_at:
            await self._restock_market()
            return
        try:
            if datetime.utcnow() >= datetime.fromisoformat(next_at):
                await self._restock_market()
        except Exception:
            await self._restock_market()

    async def _restock_market(self):
        now = datetime.utcnow()
        next_at = now + timedelta(hours=config.MARKET['restock_interval_hours'])
        prices = {}
        for res, base in config.MARKET['starting_prices'].items():
            variance = config.MARKET['price_variance']
            prices[res] = {
                "buy": int(base['buy'] * random.uniform(1 - variance, 1 + variance)),
                "sell": int(base['sell'] * random.uniform(1 - variance, 1 + variance)),
            }
        stock = dict(config.MARKET['stock_per_cycle'])
        self.db.client.collection("config").document("market_state").set({
            "next_restock_at": next_at.isoformat(),
            "last_restock_at": now.isoformat(),
            "prices": prices,
            "stock": stock,
        })
        logger.info(f"Market restocked. Next at {next_at.isoformat()}")

    def _get_market_state(self) -> Dict[str, Any]:
        ref = self.db.client.collection("config").document("market_state")
        doc = ref.get()
        if not doc.exists:
            return {}
        return doc.to_dict() or {}

    def _format_restock_time(self, next_at_iso: str) -> str:
        try:
            next_dt = datetime.fromisoformat(next_at_iso)
            delta = next_dt - datetime.utcnow()
            if delta.total_seconds() <= 0:
                return "Now"
            hrs = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            if hrs >= 24:
                days = hrs // 24
                hrs_rem = hrs % 24
                return f"{days}d {hrs_rem}h"
            return f"{hrs}h {mins}m"
        except Exception:
            return "?"

    # =================================================================
    # COMMANDS — workforce-integrated gather/farm/mine/etc.
    # =================================================================
    @commands.hybrid_command(name='gather')
    @check_cooldown_decorator("gather")
    async def gather_resources(self, ctx):
        """Opportunistic scavenge — small universal yield."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first! Use `.start <name>`")

        gains = {}
        icons = {"gold": "🪙", "wood": "🪵", "stone": "🪨", "food": "🌾"}
        for resource in ("gold", "wood", "stone", "food"):
            if random.random() < config.ECONOMY['gather_chance']:
                base = random.randint(config.ECONOMY['gather_base_min'], config.ECONOMY['gather_base_max'])
                tool_bonus = self._tool_bonus(user_id, "gather")
                tech_mult = self._tech_mult("gather", civ['military']['tech_level'])
                amount = int(base * (1 + tool_bonus) * tech_mult)
                amount = min(amount, config.CAPS['gather'])
                gains[resource] = amount

        if not gains:
            await ctx.send("🔍 Your scouts found nothing of value this time.")
            return

        luck_modifier = self.civ_manager.calculate_total_modifier(user_id, "luck")
        if luck_modifier > 1.0:
            gains = {k: int(v * luck_modifier) for k, v in gains.items()}

        gains = self._apply_sanction_penalty(user_id, gains)
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "gather")

        embed = create_embed("🔍 Resource Gathering",
                             "Your scouts return with resources!", discord.Color.green())
        embed.add_field(name="Gathered",
                        value="\n".join(f"{icons[r]} {format_number(a)} {r.capitalize()}"
                                        for r, a in gains.items()),
                        inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='work')
    @check_cooldown_decorator("work")
    @app_commands.describe(amount="Number of citizens to employ for quick gold")
    async def work(self, ctx, amount: int = None):
        """Quick cash — capped and scales poorly past early game."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if amount is None or amount < 1:
            raise CommandUsageError("Usage: `.work <amount>` — amount must be ≥ 1.")

        population = civ['population']
        current_employed = population.get('employed', 0)
        unemployed = population['citizens'] - current_employed
        if amount > unemployed:
            raise CommandUsageError(f"Only {unemployed} unemployed citizens available!")

        self.civ_manager.update_employment(user_id, amount)
        tech_mult = self._tech_mult("work", civ['military']['tech_level'])
        tool_bonus = self._tool_bonus(user_id, "work")
        gold_gain = amount * random.randint(
            config.ECONOMY['work_gold_per_citizen_min'],
            config.ECONOMY['work_gold_per_citizen_max'],
        )
        gold_gain = int(gold_gain * tech_mult * (1 + tool_bonus))
        gold_gain = min(gold_gain, config.CAPS['work'])

        gains = self._apply_sanction_penalty(user_id, {"gold": gold_gain})
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "work")

        new_rate = self.civ_manager.get_employment_rate(user_id)
        embed = create_embed("💼 Citizens Employed",
                             f"Employed {format_number(amount)} citizens for "
                             f"{format_number(gains['gold'])} gold!",
                             discord.Color.green())
        embed.add_field(name="Employment Rate", value=f"{new_rate:.1f}%", inline=True)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled gold.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='farm')
    @check_cooldown_decorator("farm")
    async def farm_food(self, ctx):
        """Farm food — scales hard with workforce in farming sector."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        sector = self._compute_sector_output(user_id, "farming", "farm", civ)
        base = random.randint(config.ECONOMY['farm_base_min'], config.ECONOMY['farm_base_max'])
        citizen_bonus = civ['population']['citizens'] // config.ECONOMY['farm_citizen_divisor']
        total_food = int((base + citizen_bonus + sector['base_yield']) * sector['final_mult'])
        total_food = min(total_food, config.CAPS['farm'])

        event_text = ""
        if random.random() < 0.1:
            mult = random.choice([0.5, 1.5, 2.0])
            total_food = int(total_food * mult)
            event_text = ("🦗 Locust swarm damaged crops!" if mult < 1
                          else "🌈 Perfect weather blessed your harvest!")

        gains = self._apply_sanction_penalty(user_id, {"food": total_food})
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "farm")

        embed = create_embed("🌾 Farming",
                             f"Farmers produced {format_number(gains['food'])} food!",
                             discord.Color.green())
        embed.add_field(
            name="Breakdown",
            value=(f"Base: {format_number(base + citizen_bonus)}\n"
                   f"Workforce: +{format_number(int(sector['base_yield']))}\n"
                   f"Modifier: ×{sector['final_mult']:.2f}"),
            inline=False,
        )
        if event_text:
            embed.add_field(name="Special Event", value=event_text, inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled food.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='mine')
    @check_cooldown_decorator("mine")
    async def mine_resources(self, ctx):
        """Mine stone and wood — scales with mining workforce."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        sector = self._compute_sector_output(user_id, "mining", "mine", civ)
        stone_base = random.randint(config.ECONOMY['mine_stone_base_min'], config.ECONOMY['mine_stone_base_max'])
        wood_base = random.randint(config.ECONOMY['mine_wood_base_min'], config.ECONOMY['mine_wood_base_max'])
        sector_base = sector['base_yield'] / 2  # split between stone and wood

        stone_yield = int((stone_base + sector_base) * sector['final_mult'])
        wood_yield = int((wood_base + sector_base) * sector['final_mult'])
        stone_yield = min(stone_yield, config.CAPS['mine_stone'])
        wood_yield = min(wood_yield, config.CAPS['mine_wood'])

        gains = {"stone": stone_yield, "wood": wood_yield}
        if random.random() < config.ECONOMY['mine_bonus_gold_chance']:
            bonus = random.randint(config.ECONOMY['mine_bonus_gold_min'],
                                   config.ECONOMY['mine_bonus_gold_max'])
            gains["gold"] = min(bonus, config.ECONOMY['mine_bonus_gold_cap'])

        gains = self._apply_sanction_penalty(user_id, gains)
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "mine")

        embed = create_embed("⛏️ Mining Operation", "Miners extracted resources!", discord.Color.blue())
        result_text = f"🪨 {format_number(gains['stone'])} Stone\n🪵 {format_number(gains['wood'])} Wood"
        if "gold" in gains:
            result_text += f"\n🪙 {format_number(gains['gold'])} Gold (Lucky find!)"
        embed.add_field(name="Extracted", value=result_text, inline=False)
        embed.add_field(
            name="Breakdown",
            value=f"Workforce: +{format_number(int(sector['base_yield']))}\n"
                  f"Modifier: ×{sector['final_mult']:.2f}",
            inline=False,
        )
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='harvest')
    @check_cooldown_decorator("harvest")
    async def harvest_food(self, ctx):
        """Large harvest — bonus from farming workforce + happiness."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        sector = self._compute_sector_output(user_id, "farming", "harvest", civ)
        pop = civ['population']['citizens']
        happiness = civ['population']['happiness']
        base = pop * 2 + happiness * 5
        total = int((base + sector['base_yield'] * 2) * sector['final_mult'] * 0.5)
        total = min(total, config.CAPS['harvest'])

        gains = self._apply_sanction_penalty(user_id, {"food": total})
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.update_population(user_id, {"happiness": 3})
        self.civ_manager.apply_faction_effects(user_id, "harvest")

        embed = create_embed("🌽 Great Harvest",
                             f"Bountiful harvest: {format_number(gains['food'])} food!",
                             discord.Color.gold())
        embed.add_field(name="Morale Boost", value="+3 happiness", inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled food.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='drill')
    @check_cooldown_decorator("drill")
    async def drill_minerals(self, ctx):
        """Deep drilling — requires Tech 2 and mining workforce."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if civ['military']['tech_level'] < 2:
            raise CommandUsageError("You need **Tech Level 2** to drill!")

        sector = self._compute_sector_output(user_id, "mining", "drill", civ)
        tech = civ['military']['tech_level']
        pop = civ['population']['citizens']
        base = 200 + (tech * 50) + (pop // 20)

        gold_gain = int((base * 2 + sector['base_yield']) * sector['final_mult'])
        stone_gain = int((base * 1.5 + sector['base_yield']) * sector['final_mult'])
        gold_gain = min(gold_gain, config.CAPS['drill_gold'])
        stone_gain = min(stone_gain, config.CAPS['drill_stone'])

        gains = self._apply_sanction_penalty(user_id, {"gold": gold_gain, "stone": stone_gain})
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "drill")

        embed = create_embed("⛏️ Deep Drilling",
                             f"Extracted {format_number(gains['gold'])} gold and "
                             f"{format_number(gains['stone'])} stone!",
                             discord.Color.purple())
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='labor', aliases=['labour'])
    @check_cooldown_decorator("labor")
    async def forced_labor(self, ctx):
        """Forced labor — good yields, big happiness hit."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if civ['military']['tech_level'] < 3:
            raise CommandUsageError("You need **Tech Level 3** for forced labor!")

        sector = self._compute_sector_output(user_id, "mining", "labor", civ)
        pop = civ['population']['citizens']
        tech = civ['military']['tech_level']
        base = 50 + (pop // 10) + (tech * 20)

        loot = {
            "gold": int(base * 1.2 * sector['final_mult']),
            "food": int(base * 1.0 * sector['final_mult']),
            "wood": int(base * 1.5 * sector['final_mult']),
            "stone": int(base * 1.5 * sector['final_mult']),
        }
        loot = {k: min(v, config.CAPS['labor']) for k, v in loot.items()}

        loot = self._apply_sanction_penalty(user_id, loot)
        loot, lucky_used = self._apply_lucky_strike_gain(user_id, loot)
        self.civ_manager.update_resources(user_id, loot)
        self.civ_manager.update_population(user_id, {"happiness": config.ECONOMY['labor_happiness_cost']})
        self.civ_manager.apply_faction_effects(user_id, "labor")

        icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        embed = create_embed("⛏️ Forced Labor", "Citizens worked tirelessly!", discord.Color.orange())
        embed.add_field(name="Resources",
                        value="\n".join(f"{icons[r]} {format_number(a)} {r.capitalize()}"
                                        for r, a in loot.items()),
                        inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='raidcaravan')
    @check_cooldown_decorator("raidcaravan")
    async def raid_caravan(self, ctx):
        """Raid NPC merchant caravans."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        military = civ['military']
        if military['soldiers'] < config.ECONOMY['raid_min_soldiers']:
            raise CommandUsageError(
                f"You need {config.ECONOMY['raid_min_soldiers']} soldiers to raid caravans!"
            )

        base_success = 0.6
        soldier_bonus = min(0.3, military['soldiers'] / 100)
        spy_bonus = min(0.1, military['spies'] / 50)
        success_chance = base_success + soldier_bonus + spy_bonus
        if civ.get('ideology') == 'anarchy':
            success_chance += 0.1

        if random.random() < success_chance:
            soldier_power = military['soldiers'] * 2
            territory_factor = get_territory_modifier(civ['territory']['land_size']) ** 1.3
            tech_mult = self._tech_mult("raid", civ['military']['tech_level'])
            tool_bonus = self._tool_bonus(user_id, "raidcaravan")
            power_mult = territory_factor * (1 + soldier_power / 500) * tech_mult * (1 + tool_bonus)

            loot = {
                "gold": int(random.randint(config.ECONOMY['raid_gold_min'],
                                           config.ECONOMY['raid_gold_max']) * power_mult),
                "food": int(random.randint(config.ECONOMY['raid_food_min'],
                                           config.ECONOMY['raid_food_max']) * power_mult),
                "wood": int(random.randint(config.ECONOMY['raid_wood_min'],
                                           config.ECONOMY['raid_wood_max']) * power_mult),
                "stone": int(random.randint(config.ECONOMY['raid_stone_min'],
                                            config.ECONOMY['raid_stone_max']) * power_mult),
            }
            for key in loot:
                loot[key] = min(loot[key], config.CAPS['raidcaravan'])

            loot = self._apply_sanction_penalty(user_id, loot)
            loot, lucky_used = self._apply_lucky_strike_gain(user_id, loot)
            self.civ_manager.update_resources(user_id, loot)
            self.civ_manager.apply_faction_effects(user_id, "raidcaravan")

            icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
            embed = create_embed("🏴‍☠️ Caravan Raid — Success!",
                                 "Raiders ambushed a wealthy caravan!",
                                 discord.Color.green())
            embed.add_field(name="Loot",
                            value="\n".join(f"{icons[r]} {format_number(a)} {r.capitalize()}"
                                            for r, a in loot.items() if a > 0),
                            inline=False)
            if lucky_used:
                embed.set_footer(text="🍀 Lucky Strike! Doubled loot.")
        else:
            loss = random.randint(1, 3)
            self.civ_manager.update_military(user_id, {"soldiers": -loss})
            embed = create_embed("🏴‍☠️ Caravan Raid — Failed!",
                                 f"Guards were too strong. Lost {loss} soldiers.",
                                 discord.Color.red())
        await ctx.send(embed=embed)

    # =================================================================
    # REFINERY
    # =================================================================
    @commands.hybrid_command(name='refine')
    @check_cooldown_decorator("refine")
    @app_commands.describe(chain="Which chain to refine", amount="Number of batches")
    @app_commands.choices(chain=[
        app_commands.Choice(name="rations", value="rations"),
        app_commands.Choice(name="tools", value="tools"),
        app_commands.Choice(name="metal", value="metal"),
        app_commands.Choice(name="weapons", value="weapons"),
        app_commands.Choice(name="luxury", value="luxury"),
    ])
    async def refine(self, ctx, chain: str = None, amount: int = 1):
        """Convert raw materials into higher-value goods."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        if not chain or chain not in config.REFINERY['chains']:
            valid = ", ".join(f"`{c}`" for c in config.REFINERY['chains'].keys())
            raise CommandUsageError(f"Invalid chain. Choose: {valid}")
        if amount is None or amount < 1:
            raise CommandUsageError("Amount must be ≥ 1.")

        chain_data = config.REFINERY['chains'][chain]
        tech_req = chain_data.get('tech_required', 1)
        if civ['military']['tech_level'] < tech_req:
            raise CommandUsageError(f"**{chain_data['name']}** requires Tech Level {tech_req}.")

        # Check all inputs
        inputs = {res: amt * amount for res, amt in chain_data['inputs'].items()}
        if not self.civ_manager.can_afford(user_id, inputs):
            cost_str = ", ".join(f"{amt} {res}" for res, amt in inputs.items())
            raise CommandUsageError(f"Need: {cost_str}")

        # Apply sector bonus (industry)
        sector = self._compute_sector_output(user_id, "industry", "refine", civ)
        tool_bonus = self._tool_bonus(user_id, "refine")
        output_per_batch = chain_data['output']
        total_output = int(output_per_batch * amount * sector['final_mult'] * (1 + tool_bonus))
        total_output = max(1, total_output)

        self.civ_manager.spend_resources(user_id, inputs)
        self.civ_manager.update_resources(user_id, {chain: total_output})
        self.civ_manager.apply_faction_effects(user_id, "refine")

        embed = create_embed(
            f"🏭 Refined {chain_data['emoji']} {chain_data['name']}",
            f"Produced **{format_number(total_output)} {chain_data['name']}**",
            discord.Color.teal(),
        )
        embed.add_field(name="Inputs Consumed",
                        value="\n".join(f"{amt} {res}" for res, amt in inputs.items()),
                        inline=True)
        embed.add_field(name="Industry Modifier",
                        value=f"×{sector['final_mult']:.2f}",
                        inline=True)
        await ctx.send(embed=embed)

    # =================================================================
    # MARKET
    # =================================================================
    @commands.hybrid_group(name='market', invoke_without_command=True)
    async def market(self, ctx):
        """View the NPC shop, prices, and restock timer."""
        state = self._get_market_state()
        if not state:
            await ctx.send("❌ Market state unavailable. Please try again shortly.")
            return

        next_at = state.get("next_restock_at", "")
        restock_in = self._format_restock_time(next_at)
        prices = state.get("prices", {})
        stock = state.get("stock", {})

        user_id = _uid(ctx)
        sanctioned = self._is_sanctioned(user_id)

        embed = create_embed(
            "🏪 Global Market",
            f"**Next restock:** in **{restock_in}**\n"
            f"*NPC-run shop. Restocks every {config.MARKET['restock_interval_hours']}h.*",
            discord.Color.dark_teal(),
        )
        if sanctioned:
            embed.add_field(
                name="🚫 Sanctioned",
                value="You cannot use the market. Use `.smuggle` instead.",
                inline=False,
            )

        for res in ["food", "wood", "stone", "gold", "tools", "metal", "luxury", "rations", "weapons"]:
            p = prices.get(res)
            s = stock.get(res)
            if not p:
                continue
            icon = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨",
                    "tools": "🔧", "metal": "🔩", "luxury": "💎",
                    "rations": "🍱", "weapons": "⚔️"}.get(res, "📦")
            embed.add_field(
                name=f"{icon} {res.capitalize()}",
                value=f"Buy: 🪙 {p['buy']}  ·  Sell: 🪙 {p['sell']}\n"
                      f"Stock: **{format_number(s or 0)}**",
                inline=True,
            )

        embed.set_footer(text=".market buy <resource> <amount> · .market sell <resource> <amount>")
        await ctx.send(embed=embed)

    @market.command(name='buy')
    @app_commands.describe(resource="Resource to buy", amount="Amount")
    async def market_buy(self, ctx, resource: str = None, amount: int = None):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if self._is_sanctioned(user_id):
            raise CommandUsageError("You are under sanctions — market access blocked. Try `.smuggle`.")

        if not resource or not amount or amount < 1:
            raise CommandUsageError("Usage: `.market buy <resource> <amount>`")

        resource = resource.lower()
        state = self._get_market_state()
        if not state:
            raise CommandUsageError("Market unavailable.")

        prices = state.get("prices", {})
        stock = state.get("stock", {})
        if resource not in prices:
            raise CommandUsageError(f"Unknown resource: `{resource}`.")
        if amount < config.MARKET['min_buy']:
            raise CommandUsageError(f"Minimum buy: {config.MARKET['min_buy']}.")
        if amount > config.MARKET['max_single_transaction']:
            raise CommandUsageError(f"Maximum per transaction: {config.MARKET['max_single_transaction']}.")

        available = int(stock.get(resource, 0))
        if available < amount:
            raise CommandUsageError(f"Only **{format_number(available)}** {resource} in stock.")

        price_per = prices[resource]['buy']
        tool_bonus = self._tool_bonus(user_id, "market_buy")
        total_cost = int(amount * price_per * (1 - tool_bonus))

        if not self.civ_manager.can_afford(user_id, {"gold": total_cost}):
            raise CommandUsageError(f"Need 🪙 {format_number(total_cost)} gold.")

        # Apply
        self.civ_manager.spend_resources(user_id, {"gold": total_cost})
        if resource == "soldiers":
            self.civ_manager.update_military(user_id, {"soldiers": amount})
        else:
            self.civ_manager.update_resources(user_id, {resource: amount})

        # Update stock
        stock[resource] = available - amount
        self.db.client.collection("config").document("market_state").update({"stock": stock})

        self.civ_manager.apply_faction_effects(user_id, "market_buy")

        await ctx.send(embed=create_embed(
            f"✅ Bought {format_number(amount)} {resource}",
            f"Total: 🪙 {format_number(total_cost)} ({price_per}/unit)",
            discord.Color.green(),
        ))

    @market.command(name='sell')
    @app_commands.describe(resource="Resource to sell", amount="Amount")
    async def market_sell(self, ctx, resource: str = None, amount: int = None):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if self._is_sanctioned(user_id):
            raise CommandUsageError("You are under sanctions — market access blocked. Try `.smuggle`.")

        if not resource or not amount or amount < 1:
            raise CommandUsageError("Usage: `.market sell <resource> <amount>`")

        resource = resource.lower()
        state = self._get_market_state()
        if not state:
            raise CommandUsageError("Market unavailable.")

        prices = state.get("prices", {})
        if resource not in prices:
            raise CommandUsageError(f"Unknown resource: `{resource}`.")

        if not self.civ_manager.can_afford(user_id, {resource: amount}):
            raise CommandUsageError(f"You don't have {amount} {resource}.")

        price_per = prices[resource]['sell']
        tool_bonus = self._tool_bonus(user_id, "market_sell")
        total_gain = int(amount * price_per * (1 + tool_bonus))

        self.civ_manager.spend_resources(user_id, {resource: amount})
        self.civ_manager.update_resources(user_id, {"gold": total_gain})
        self.civ_manager.apply_faction_effects(user_id, "market_sell")

        await ctx.send(embed=create_embed(
            f"✅ Sold {format_number(amount)} {resource}",
            f"Earned: 🪙 {format_number(total_gain)} ({price_per}/unit)",
            discord.Color.gold(),
        ))

    @commands.hybrid_command(name='smuggle')
    @check_cooldown_decorator("smuggle")
    @app_commands.describe(resource="Resource to smuggle", amount="Amount")
    async def smuggle(self, ctx, resource: str = None, amount: int = None):
        """High-risk, high-reward selling. Sanctioned players must use this."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        if not resource or not amount or amount < 1:
            raise CommandUsageError("Usage: `.smuggle <resource> <amount>`")

        resource = resource.lower()
        state = self._get_market_state()
        if not state:
            raise CommandUsageError("Market unavailable.")

        prices = state.get("prices", {})
        if resource not in prices:
            raise CommandUsageError(f"Unknown resource: `{resource}`.")

        if not self.civ_manager.can_afford(user_id, {resource: amount}):
            raise CommandUsageError(f"You don't have {amount} {resource}.")

        base_price = prices[resource]['sell']
        smuggle_data = config.MARKET['smuggle']
        price_mult = smuggle_data['price_mult']
        tool_bonus = self._tool_bonus(user_id, "smuggle")
        tool_detect = self._tool_bonus(user_id, "smuggle_detection")

        total_gain = int(amount * base_price * price_mult * (1 + tool_bonus))
        detection = max(0.05, smuggle_data['detection_chance'] + tool_detect)

        self.civ_manager.spend_resources(user_id, {resource: amount})

        if random.random() < detection:
            # Detected — lose half
            loss_pct = smuggle_data['loss_on_detect']
            recovered = int(total_gain * (1 - loss_pct))
            self.civ_manager.update_resources(user_id, {"gold": recovered})
            # Sanction
            try:
                civ_data = self.civ_manager.get_civilization(user_id) or {}
                received = civ_data.get('received_sanctions') or []
                expires = (datetime.utcnow() +
                           timedelta(hours=smuggle_data['sanction_hours'])).isoformat()
                received.append({
                    "imposer_id": "global_market",
                    "expires_at": expires,
                    "reason": "Smuggling detected",
                })
                self.db.update_civilization(user_id, {"received_sanctions": received})
                self.civ_manager._invalidate_civ(user_id)
            except Exception:
                pass

            embed = create_embed(
                "🚨 SMUGGLING DETECTED!",
                f"Your smuggled goods were seized by authorities.\n\n"
                f"**Goods lost:** {int(amount * loss_pct)} {resource}\n"
                f"**Recovered:** 🪙 {format_number(recovered)}\n"
                f"**Sanctioned for {smuggle_data['sanction_hours']}h**",
                discord.Color.dark_red(),
            )
            await ctx.send(embed=embed)
        else:
            self.civ_manager.update_resources(user_id, {"gold": total_gain})
            self.civ_manager.apply_faction_effects(user_id, "smuggle")
            embed = create_embed(
                "🕶️ Smuggling Successful",
                f"Your goods slipped through customs!\n\n"
                f"**Sold:** {format_number(amount)} {resource}\n"
                f"**Earned:** 🪙 {format_number(total_gain)} ({price_mult}× market price)",
                discord.Color.purple(),
            )
            await ctx.send(embed=embed)

    # =================================================================
    # TOOLS
    # =================================================================
    @commands.hybrid_command(name='tools')
    @app_commands.describe(name="Tool to buy (optional — lists all if empty)")
    async def tools_cmd(self, ctx, name: str = None):
        """View or buy permanent tools. No tech required — gold unlocks them."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        owned = civ.get('tools') or []

        if not name:
            embed = create_embed(
                "🛠️ Tools Shop",
                "Permanent command boosts. **Gold only — no tech unlocks needed.**\n"
                "*Tier 2 tools require their Tier 1 predecessor.*",
                discord.Color.dark_teal(),
            )
            for tool_key, tool in config.TOOLS.items():
                is_owned = tool_key in owned
                req = tool.get('requires')
                req_met = (req is None) or (req in owned)
                marker = "✅ " if is_owned else ("🔒 " if not req_met else "")
                boosts = ", ".join(f"+{int(v*100)}% {k}" for k, v in tool.get('boosts', {}).items())
                status = "OWNED" if is_owned else f"🪙 {format_number(tool['cost'])}"
                req_line = f"\n*Requires: {config.TOOLS[req]['name']}*" if (req and not req_met) else ""
                embed.add_field(
                    name=f"{marker}{tool['emoji']} {tool['name']} — {status}",
                    value=f"*{tool['desc']}*\n{boosts}{req_line}",
                    inline=False,
                )
            embed.set_footer(text="Buy with: .tools buy <name>")
            await ctx.send(embed=embed)
            return

        # Match by key or name
        matched_key = None
        name_lower = name.lower().strip()
        for k, t in config.TOOLS.items():
            if k == name_lower or t['name'].lower() == name_lower or name_lower in t['name'].lower():
                matched_key = k
                break
        if not matched_key:
            raise CommandUsageError(f"No tool matching `{name}`.")

        tool = config.TOOLS[matched_key]
        if matched_key in owned:
            raise CommandUsageError(f"You already own **{tool['name']}**.")
        req = tool.get('requires')
        if req and req not in owned:
            raise CommandUsageError(f"Requires **{config.TOOLS[req]['name']}** first.")

        if not self.civ_manager.can_afford(user_id, {"gold": tool['cost']}):
            raise CommandUsageError(f"Need 🪙 {format_number(tool['cost'])} gold.")

        self.civ_manager.spend_resources(user_id, {"gold": tool['cost']})
        owned.append(matched_key)
        self.db.update_civilization(user_id, {"tools": owned})
        self.civ_manager._invalidate_civ(user_id)
        self.civ_manager.apply_faction_effects(user_id, "tool_purchase")

        boosts = ", ".join(f"+{int(v*100)}% {k}" for k, v in tool['boosts'].items())
        await ctx.send(embed=create_embed(
            f"✅ Bought {tool['emoji']} {tool['name']}",
            f"*{tool['desc']}*\n**Boosts:** {boosts}",
            discord.Color.green(),
        ))

    # =================================================================
    # TAX — reworked with rate system
    # =================================================================
    @commands.hybrid_command(name='tax')
    @check_cooldown_decorator("tax")
    @app_commands.describe(rate="Tax rate tier (low/normal/high/brutal)")
    @app_commands.choices(rate=[
        app_commands.Choice(name="low", value="low"),
        app_commands.Choice(name="normal", value="normal"),
        app_commands.Choice(name="high", value="high"),
        app_commands.Choice(name="brutal", value="brutal"),
    ])
    async def collect_taxes(self, ctx, rate: str = "normal"):
        """Collect taxes. Higher rates = more gold + more unrest."""
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        if rate not in config.ECONOMY['tax_rates']:
            raise CommandUsageError(f"Invalid rate. Choose: low, normal, high, brutal.")

        rate_data = config.ECONOMY['tax_rates'][rate]
        rate_mult = rate_data['mult']
        base_happiness = rate_data['happiness']

        population = civ['population']
        tech = civ['military']['tech_level']
        happiness = population['happiness']

        base_tax = population['citizens'] * (1 + tech * 0.25)
        happiness_modifier = max(0.0, happiness / 100)
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * 0.2

        land = civ['territory']['land_size']
        territory_factor = min(1.0 + 0.15 * math.log10(land / 1000 + 1), 1.5) if land > 0 else 1.0

        trade_sector = self._compute_sector_output(user_id, "trade", "tax", civ)
        tool_bonus = self._tool_bonus(user_id, "tax")

        total_tax = int(
            base_tax * happiness_modifier * employment_factor * territory_factor
            * rate_mult * (1 + tool_bonus) * (1 + trade_sector['base_yield'] / 5000)
        )
        TAX_CAP = 150_000
        capped = total_tax > TAX_CAP
        total_tax = min(total_tax, TAX_CAP)

        ideology = civ.get('ideology', '')
        if ideology == 'democracy':
            total_tax = int(total_tax * 1.05)
        elif ideology == 'fascism':
            total_tax = int(total_tax * 1.1)

        happiness_cost = base_happiness
        if ideology == 'fascism':
            happiness_cost -= 5

        tax_gains = self._apply_sanction_penalty(user_id, {"gold": total_tax})
        tax_gains, lucky_used = self._apply_lucky_strike_gain(user_id, tax_gains)
        self.civ_manager.update_resources(user_id, tax_gains)
        self.civ_manager.apply_faction_effects(user_id, "tax")

        population_loss = 0
        soldier_loss = 0
        riot = False

        if total_tax >= 40_000:
            loss_chance = min(0.75, 0.15 + (total_tax / 300_000))
            if random.random() < loss_chance:
                population_loss = max(1, int(population['citizens'] * random.uniform(0.02, 0.07)))
                riot = True

        if happiness + happiness_cost < 30:
            extra = max(1, int(population['citizens'] * 0.04))
            population_loss += extra
            riot = True

        if total_tax >= 80_000 and happiness + happiness_cost < 50:
            if random.random() < 0.5:
                soldier_loss = max(1, int(civ['military']['soldiers'] * random.uniform(0.05, 0.12)))

        self.civ_manager.update_population(user_id, {
            "happiness": happiness_cost,
            "citizens": -population_loss,
        })
        if soldier_loss > 0:
            self.civ_manager.update_military(user_id, {"soldiers": -soldier_loss})

        embed = create_embed("💰 Tax Collection",
                             f"Collected {format_number(tax_gains['gold'])} gold in taxes ({rate} rate).",
                             discord.Color.gold())
        embed.add_field(name="Social Cost", value=f"😡 Happiness: {happiness_cost}", inline=True)
        if capped:
            embed.add_field(name="⚠️ Hard Cap",
                            value=f"Tax capped at {format_number(TAX_CAP)} per collection.",
                            inline=False)
        if population_loss > 0:
            embed.add_field(name="💀 Population Loss",
                            value=f"{population_loss} citizens emigrated!", inline=False)
        if soldier_loss > 0:
            embed.add_field(name="⚔️ Desertion",
                            value=f"{soldier_loss} soldiers deserted!", inline=False)
        if riot:
            embed.add_field(name="🔥 Tax Revolt", value="Riots broke out!", inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled tax.")
        await ctx.send(embed=embed)

    # =================================================================
    # INVESTMENT, ADVERTISE, IMMIGRATION
    # =================================================================
    @commands.hybrid_command(name='invest')
    @check_cooldown_decorator("invest")
    @app_commands.describe(amount="Gold to invest")
    async def invest_gold(self, ctx, amount: int = None):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if amount is None or amount < 100:
            raise CommandUsageError("Minimum 100 gold.")

        if not self.civ_manager.can_afford(user_id, {"gold": amount}):
            raise CommandUsageError(f"You don't have {format_number(amount)} gold!")

        self.civ_manager.spend_resources(user_id, {"gold": amount})
        self.civ_manager.apply_faction_effects(user_id, "invest")

        await ctx.send(embed=create_embed(
            "💼 Investment Made",
            f"Invested {format_number(amount)} gold. Returns in 2h.",
            discord.Color.blue(),
        ))

        async def investment_return():
            await asyncio.sleep(7200)
            if random.random() < 0.8:
                mult = random.uniform(1.2, 1.8)
                returns = min(int(amount * mult), 10_000_000)
                self.civ_manager.update_resources(user_id, {"gold": returns})
                try:
                    u = await self.bot.fetch_user(int(user_id))
                    await u.send(f"💰 **Investment Return**: {format_number(returns)} gold!")
                except Exception:
                    pass
            else:
                mult = random.uniform(0.3, 0.7)
                returns = int(amount * mult)
                self.civ_manager.update_resources(user_id, {"gold": returns})
                try:
                    u = await self.bot.fetch_user(int(user_id))
                    await u.send(f"📉 **Investment Loss**: only {format_number(returns)} gold returned.")
                except Exception:
                    pass

        asyncio.create_task(investment_return())

    @commands.hybrid_command(name='advertise')
    @check_cooldown_decorator("advertise")
    async def advertise_civilization(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        ad_cost = config.ECONOMY['advertise_cost']
        if not self.civ_manager.can_afford(user_id, {"gold": ad_cost}):
            raise CommandUsageError(f"Need {ad_cost} gold.")

        self.civ_manager.spend_resources(user_id, {"gold": ad_cost})
        tech_multiplier = 1 + (civ['military']['tech_level'] * 0.05)
        base = random.randint(config.ECONOMY['advertise_citizen_min'],
                              config.ECONOMY['advertise_citizen_max'])
        happiness_bonus = civ['population']['happiness'] // 10
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * config.ECONOMY['advertise_employment_coeff']
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        total = int((base + happiness_bonus) * employment_factor * territory_factor * tech_multiplier)
        total = min(total, config.CAPS['advertise'])

        if civ.get('ideology') == 'democracy':
            total = int(total * 1.2)
        elif civ.get('ideology') == 'fascism':
            total = int(total * 0.8)

        self.civ_manager.update_population(user_id, {"citizens": total})
        self.civ_manager.apply_faction_effects(user_id, "advertise")

        await ctx.send(embed=create_embed(
            "📢 Advertising Campaign",
            f"{format_number(total)} people became citizens!",
            discord.Color.green(),
        ))

    @commands.hybrid_command(name='immigration')
    @check_cooldown_decorator("immigration")
    async def open_immigration(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        tech_multiplier = 1 + (civ['military']['tech_level'] * 0.05)
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * config.ECONOMY['immigration_employment_coeff']
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        base = random.randint(config.ECONOMY['immigration_citizen_min'],
                              config.ECONOMY['immigration_citizen_max'])
        gained = int(base * employment_factor * territory_factor * tech_multiplier)
        gained = min(gained, config.CAPS['immigration'])
        self.civ_manager.update_population(user_id, {"citizens": gained})

        happiness_loss = random.randint(config.ECONOMY['immigration_happiness_loss_min'],
                                        config.ECONOMY['immigration_happiness_loss_max'])
        self.civ_manager.update_population(user_id, {"happiness": -happiness_loss})

        riot_triggered = False
        if random.random() < config.ECONOMY['immigration_riot_chance']:
            riot_triggered = True
            extra_h = random.randint(config.ECONOMY['immigration_riot_happiness_loss_min'],
                                     config.ECONOMY['immigration_riot_happiness_loss_max'])
            s_loss = random.randint(config.ECONOMY['immigration_riot_soldier_loss_min'],
                                    config.ECONOMY['immigration_riot_soldier_loss_max'])
            self.civ_manager.update_population(user_id, {"happiness": -extra_h})
            self.civ_manager.update_military(user_id, {"soldiers": -s_loss})
            self.civ_manager.apply_faction_effects(user_id, "immigration_riot")
            self.db.log_event(user_id, "immigration_riot", "Immigration Riot!",
                              f"Anti-immigration protests! Lost {s_loss} soldiers and {extra_h} happiness.")

        self.civ_manager.apply_faction_effects(user_id, "immigration")
        self.db.log_event(user_id, "immigration", "Immigration Opened",
                          f"Gained {gained} citizens, lost {happiness_loss} happiness.")

        embed = create_embed("🛂 Immigration Open!",
                             f"{gained} new citizens arrived!", discord.Color.blue())
        embed.add_field(name="👥 Citizens Gained", value=f"+{format_number(gained)}", inline=True)
        embed.add_field(name="😡 Happiness", value=f"-{happiness_loss}", inline=True)
        if riot_triggered:
            embed.add_field(name="💥 PROTEST RIOT!",
                            value=f"Lost {s_loss} soldiers and {extra_h} more happiness!",
                            inline=False)
            embed.color = discord.Color.red()
        await ctx.send(embed=embed)

    # =================================================================
    # MISC COMMANDS — kept from old economy.py
    # =================================================================
    @commands.hybrid_command(name='recruit')
    @app_commands.describe(number="Number of citizens to recruit as soldiers")
    async def recruit_soldiers(self, ctx, number: int = None):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if number is None or number < 1:
            raise CommandUsageError("Usage: `.recruit <number>`")

        population = civ['population']
        current = population['citizens']
        if number > current:
            raise CommandUsageError(f"Only {format_number(current)} citizens available!")

        base_success = 0.7
        happiness_modifier = population['happiness'] / 100
        ratio = number / current
        ratio_penalty = max(0, (ratio - 0.1) * 2) if ratio > 0.1 else 0
        success_chance = max(0.1, min(0.9, base_success * happiness_modifier - ratio_penalty))

        if random.random() < success_chance:
            self.civ_manager.update_population(user_id, {"citizens": -number})
            self.civ_manager.update_military(user_id, {"soldiers": number})
            embed = create_embed("🎖️ Recruitment Success!",
                                 f"{format_number(number)} citizens enlisted!",
                                 discord.Color.green())
        else:
            lost = min(number * 2, current // 2)
            self.civ_manager.update_population(user_id, {"citizens": -lost, "happiness": -5})
            embed = create_embed("🎖️ Recruitment Failed!",
                                 f"{format_number(lost)} citizens fled.",
                                 discord.Color.red())
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='buysoldiers')
    @app_commands.describe(amount="Number of soldiers to buy")
    async def buy_soldiers(self, ctx, amount: int = None):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if amount is None or amount < 1:
            raise CommandUsageError(f"Usage: `.buysoldiers <amount>` — {config.MILITARY['soldier_buy_cost']}g each.")

        cost = amount * config.MILITARY['soldier_buy_cost']
        if not self.civ_manager.can_afford(user_id, {"gold": cost}):
            raise CommandUsageError(f"Need {format_number(cost)} gold.")

        self.civ_manager.spend_resources(user_id, {"gold": cost})
        self.civ_manager.update_military(user_id, {"soldiers": amount})
        await ctx.send(embed=create_embed("⚔️ Soldiers Bought!",
                                          f"Bought {format_number(amount)} soldiers for {format_number(cost)} gold!",
                                          discord.Color.green()))

    @commands.hybrid_command(name='buytech', aliases=['buylevel'])
    async def buy_tech_level(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        current_level = civ['military']['tech_level']
        if current_level >= 10:
            raise CommandUsageError("Max tech level (10)!")
        if civ['resources']['gold'] < 2000:
            raise CommandUsageError("You need 2000 gold.")

        self.civ_manager.spend_resources(user_id, {"gold": 2000})
        self.civ_manager.update_military(user_id, {"tech_level": 1})
        await ctx.send(embed=create_embed("🔬 Technology Purchased!",
                                          f"Tech level: **{current_level}** → **{current_level + 1}**",
                                          discord.Color.blue()))

    @commands.hybrid_command(name='burn')
    async def burn_resources(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        resources = civ['resources']
        changes = {res: 1000 - resources.get(res, 0)
                   for res in ['gold', 'food', 'wood', 'stone']
                   if resources.get(res, 0) > 1000}
        if not changes:
            await ctx.send("✅ All resources already ≤1000.")
            return
        self.civ_manager.update_resources(user_id, changes)
        embed = create_embed("🔥 Resources Burned!", "Excess reduced to 1000 each.",
                             discord.Color.orange())
        for res, change in changes.items():
            embed.add_field(name=res.capitalize(),
                            value=f"{format_number(resources[res])} → 1000",
                            inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='drive')
    @app_commands.describe(amount="Number of employed citizens to unemploy")
    async def drive_citizens(self, ctx, amount: int = None):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if amount is None or amount < 1:
            raise CommandUsageError("Usage: `.drive <amount>`")

        current_employed = civ['population'].get('employed', 0)
        if amount > current_employed:
            raise CommandUsageError(f"Only {current_employed} employed citizens!")

        self.civ_manager.update_employment(user_id, -amount)
        self.civ_manager.update_population(user_id, {"happiness": -2})
        new_rate = self.civ_manager.get_employment_rate(user_id)
        embed = create_embed("🚗 Citizens Unemployed",
                             f"Unemployed {format_number(amount)} citizens.",
                             discord.Color.red())
        embed.add_field(name="Employment Rate", value=f"{new_rate:.1f}%", inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='festival')
    @check_cooldown_decorator("festival")
    async def hold_festival(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        cost = {"gold": 200, "food": 100}
        if not self.civ_manager.can_afford(user_id, cost):
            raise CommandUsageError("Need 200 gold and 100 food.")

        self.civ_manager.spend_resources(user_id, cost)
        boost = 10
        if civ.get('ideology') == 'theocracy':
            boost = int(boost * 1.2)
        self.civ_manager.update_population(user_id, {"happiness": boost})
        self.civ_manager.apply_faction_effects(user_id, "festival")
        await ctx.send(embed=create_embed("🎉 Grand Festival",
                                          f"+{boost} happiness!",
                                          discord.Color.gold()))

    @commands.hybrid_command(name='cheer')
    @check_cooldown_decorator("cheer")
    async def cheer_citizens(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if not self.civ_manager.can_afford(user_id, {"gold": 50}):
            raise CommandUsageError("Need 50 gold.")

        self.civ_manager.spend_resources(user_id, {"gold": 50})
        boost = 5
        if civ.get('ideology') == 'democracy':
            boost = int(boost * 1.1)
        self.civ_manager.update_population(user_id, {"happiness": boost})
        self.civ_manager.apply_faction_effects(user_id, "cheer")
        await ctx.send(embed=create_embed("😊 Spreading Cheer",
                                          f"+{boost} happiness!",
                                          discord.Color.green()))

    @commands.hybrid_command(name='cheerup')
    @check_cooldown_decorator("cheerup")
    async def cheer_up(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if civ['resources']['gold'] < 2000:
            raise CommandUsageError("You need 2000 gold.")

        self.civ_manager.spend_resources(user_id, {"gold": 2000})
        current = civ['population']['happiness']
        boost = int((100 - current) * 0.5)
        self.civ_manager.update_population(user_id, {"happiness": boost})
        self.civ_manager.apply_faction_effects(user_id, "cheerup")
        await ctx.send(embed=create_embed("😊 Cheer Up!",
                                          f"Citizens are much happier! (+{boost} happiness)",
                                          discord.Color.green()))

    @commands.hybrid_command(name='sell')
    @app_commands.describe(item_name="Item to sell")
    async def sell_hyper_item(self, ctx, item_name: str = None):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if not item_name:
            raise CommandUsageError("Usage: `.sell <item-name>`")

        hyper_items = civ['hyper_items']
        if item_name not in hyper_items:
            raise CommandUsageError(f"You don't have '{item_name}'!")

        prices = {
            "Lucky-Charm": random.randint(config.ECONOMY['sell_common_min'],
                                          config.ECONOMY['sell_common_max']),
            "Ancient-Relic": random.randint(config.ECONOMY['sell_rare_min'],
                                            config.ECONOMY['sell_rare_max']),
            "Crystal-Heart": random.randint(config.ECONOMY['sell_rare_min'],
                                            config.ECONOMY['sell_rare_max']),
            "Dragon-Scale": random.randint(config.ECONOMY['sell_rare_min'] + 50,
                                           config.ECONOMY['sell_rare_max'] + 50),
            "Phoenix-Feather": random.randint(config.ECONOMY['sell_legendary_min'],
                                              config.ECONOMY['sell_legendary_max'])
        }
        gold_value = min(prices.get(item_name, random.randint(50, 150)), config.CAPS['sell'])
        self.civ_manager.use_hyper_item(user_id, item_name)
        self.civ_manager.update_resources(user_id, {"gold": gold_value})
        await ctx.send(embed=create_embed("💰 Item Sold!",
                                          f"Sold '{item_name}' for {format_number(gold_value)} gold!",
                                          discord.Color.gold()))

    @commands.hybrid_command(name='buycard')
    async def buy_card(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        if not self.civ_manager.can_afford(user_id, {"gold": 500}):
            raise CommandUsageError("Need 500 gold.")

        self.civ_manager.spend_resources(user_id, {"gold": 500})
        card = random.choice(config.CARD_POOL)
        purchased = civ.get('purchased_cards', [])
        purchased.append(card)
        self.db.update_civilization(user_id, {"purchased_cards": purchased})
        embed = create_embed("🎴 Card Purchased!",
                             f"You received:\n**{card['name']}** – {card['description']}",
                             discord.Color.gold())
        embed.add_field(name="How to use", value="`.cards use \"Card Name\"`", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='census')
    async def show_census(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        resources = civ['resources']
        population = civ['population']
        employment_rate = self.civ_manager.get_employment_rate(user_id)
        wf = self._workforce_state(user_id)

        embed = create_embed("📊 National Census Report",
                             f"Status of {civ['name']}",
                             discord.Color.blue())
        embed.add_field(name="💰 Resources",
                        value=(f"🪙 Gold: {format_number(resources['gold'])}\n"
                               f"🌾 Food: {format_number(resources['food'])}\n"
                               f"🪵 Wood: {format_number(resources['wood'])}\n"
                               f"🪨 Stone: {format_number(resources['stone'])}"),
                        inline=True)
        embed.add_field(name="👥 Population",
                        value=(f"👥 Citizens: {format_number(population['citizens'])}\n"
                               f"💼 Employed: {format_number(population.get('employed', 0))}\n"
                               f"📈 Rate: {employment_rate:.1f}%\n"
                               f"😊 Happiness: {population['happiness']}%\n"
                               f"🍽️ Hunger: {population['hunger']}%"),
                        inline=True)
        wf_line = " · ".join(f"{s[:4].title()} {n}" for s, n in wf.items())
        embed.add_field(name="🏭 Workforce Sectors", value=wf_line or "None assigned", inline=False)
        await ctx.send(embed=embed)

    # =================================================================
    # MEGAPROJECTS
    # =================================================================
    @commands.hybrid_group(name='megaproject', invoke_without_command=True)
    async def megaproject(self, ctx):
        embed = create_embed("🏗️ Megaprojects",
                             "**Custom:** `.megaproject build <description>`\n"
                             "**Presets:** `.megaproject preset <name>`\n"
                             "**List presets:** `.megaproject presets`",
                             discord.Color.gold())
        await ctx.send(embed=embed)

    @megaproject.command(name='presets')
    async def megaproject_presets(self, ctx):
        embed = create_embed("📜 Predefined Megaprojects", "", discord.Color.blue())
        for key, data in config.MEGAPROJECTS.items():
            cost_str = ", ".join([f"{amt} {res}" for res, amt in data['cost'].items()])
            embed.add_field(name=f"{data['name']} (Tech {data['tech_required']})",
                            value=f"Cost: {cost_str}\nEffect: {data['description']}",
                            inline=False)
        embed.add_field(name="Usage", value="`.megaproject preset <name>`", inline=False)
        await ctx.send(embed=embed)

    @megaproject.command(name='preset')
    @app_commands.describe(preset_name="Name of the megaproject preset")
    async def megaproject_preset_build(self, ctx, preset_name: str):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        preset = None
        for key, data in config.MEGAPROJECTS.items():
            if key.lower() == preset_name.lower() or data['name'].lower() == preset_name.lower():
                preset = (key, data)
                break
        if not preset:
            raise CommandUsageError("Unknown preset. Use `.megaproject presets`.")

        key, data = preset
        if civ['military']['tech_level'] < data['tech_required']:
            raise CommandUsageError(f"You need Tech Level {data['tech_required']}!")

        built = civ.get('megaprojects', [])
        if key in built:
            raise CommandUsageError(f"Already built {data['name']}!")

        if not self.civ_manager.can_afford(user_id, data['cost']):
            cost_str = ", ".join([f"{amt} {res}" for res, amt in data['cost'].items()])
            raise CommandUsageError(f"Cannot afford! Requires: {cost_str}")

        self.civ_manager.spend_resources(user_id, data['cost'])
        built.append(key)
        bonuses = civ.get('bonuses', {})
        for ek, ev in data['effect'].items():
            bonuses[ek] = bonuses.get(ek, 0) + ev
        self.db.update_civilization(user_id, {"megaprojects": built, "bonuses": bonuses})
        self.civ_manager.apply_faction_effects(user_id, "build_megaproject")
        await ctx.send(embed=create_embed(f"🏗️ {data['name']} Complete!",
                                          data['description'],
                                          discord.Color.gold()))

    # =================================================================
    # POLICIES
    # =================================================================
    @commands.hybrid_group(name='policy', invoke_without_command=True)
    async def policy(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")
        active = civ.get('policies', {})
        if not active:
            await ctx.send("📭 No active policies. Use `.policy enable <name>`.")
            return
        embed = create_embed("📜 Active Policies", "", discord.Color.blue())
        for pk, level in active.items():
            if pk in config.POLICIES:
                pdata = config.POLICIES[pk]
                ld = pdata['levels'].get(level)
                if ld:
                    embed.add_field(name=f"{pdata['name']} (Level {level})",
                                    value=ld['desc'], inline=False)
        await ctx.send(embed=embed)

    @policy.command(name='enable')
    @app_commands.describe(policy_name="Name of policy to enable")
    async def policy_enable(self, ctx, policy_name: str):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        pk = None
        for key, data in config.POLICIES.items():
            if key.lower() == policy_name.lower() or data['name'].lower() == policy_name.lower():
                pk = key; break
        if not pk:
            raise CommandUsageError("Unknown policy. Use `.policieshelp`.")

        active = civ.get('policies', {})
        if pk in active:
            raise CommandUsageError("Already active.")

        pdata = config.POLICIES[pk]
        ld = pdata['levels'][1]
        cost = {res.replace('_cost', ''): amt for res, amt in ld.items() if res.endswith('_cost')}
        if not self.civ_manager.can_afford(user_id, cost):
            cost_str = ", ".join([f"{amt} {res}" for res, amt in cost.items()])
            raise CommandUsageError(f"Cannot afford! Requires: {cost_str}")

        self.civ_manager.spend_resources(user_id, cost)
        active[pk] = 1
        self.db.update_civilization(user_id, {"policies": active})
        self._apply_policy_effects(user_id, pk, 1, active)
        await ctx.send(f"✅ Enabled **{pdata['name']}** Level 1!")

    @policy.command(name='upgrade')
    @app_commands.describe(policy_name="Name of policy to upgrade")
    async def policy_upgrade(self, ctx, policy_name: str):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        pk = None
        for key, data in config.POLICIES.items():
            if key.lower() == policy_name.lower() or data['name'].lower() == policy_name.lower():
                pk = key; break
        if not pk:
            raise CommandUsageError("Unknown policy.")

        active = civ.get('policies', {})
        if pk not in active:
            raise CommandUsageError("Not active. Enable first.")

        pdata = config.POLICIES[pk]
        cl = active[pk]
        if cl >= pdata['max_level']:
            raise CommandUsageError(f"Already max level ({pdata['max_level']}).")

        nl = cl + 1
        ld = pdata['levels'][nl]
        cost = {res.replace('_cost', ''): amt for res, amt in ld.items() if res.endswith('_cost')}
        if not self.civ_manager.can_afford(user_id, cost):
            cost_str = ", ".join([f"{amt} {res}" for res, amt in cost.items()])
            raise CommandUsageError(f"Cannot afford! Requires: {cost_str}")

        self.civ_manager.spend_resources(user_id, cost)
        active[pk] = nl
        self.db.update_civilization(user_id, {"policies": active})
        self._apply_policy_effects(user_id, pk, nl, active)
        await ctx.send(f"⬆️ Upgraded **{pdata['name']}** to Level {nl}!")

    @policy.command(name='disable')
    @app_commands.describe(policy_name="Name of policy to disable")
    async def policy_disable(self, ctx, policy_name: str):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        pk = None
        for key, data in config.POLICIES.items():
            if key.lower() == policy_name.lower() or data['name'].lower() == policy_name.lower():
                pk = key; break
        if not pk:
            raise CommandUsageError("Unknown policy.")

        active = civ.get('policies', {})
        if pk not in active:
            raise CommandUsageError("Not active.")

        del active[pk]
        self.db.update_civilization(user_id, {"policies": active})
        self._apply_all_policies(user_id)
        await ctx.send(f"❌ Disabled **{config.POLICIES[pk]['name']}**.")

    @policy.command(name='list')
    async def policy_list(self, ctx):
        embed = create_embed("📜 Available Policies", "Use `.policy enable <name>`.",
                             discord.Color.blue())
        for key, data in config.POLICIES.items():
            embed.add_field(name=f"{data['name']} (Max {data['max_level']})",
                            value=f"{data['base_desc']}\nLevel 1: {data['levels'][1]['desc']}",
                            inline=False)
        await ctx.send(embed=embed)

    def _apply_policy_effects(self, user_id: str, pk: str, level: int, active: dict):
        pdata = config.POLICIES[pk]
        ld = pdata['levels'][level]
        effect = ld.get('effect', {})
        if not effect:
            return
        self._remove_policy_effect(user_id, pk)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return
        bonuses = civ.get('bonuses', {})
        for ek, ev in effect.items():
            bonuses[f"policy_{pk}_{ek}"] = ev
        self.db.update_civilization(user_id, {"bonuses": bonuses})

    def _remove_policy_effect(self, user_id: str, pk: str):
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return
        bonuses = civ.get('bonuses', {})
        for k in [k for k in bonuses if k.startswith(f"policy_{pk}_")]:
            del bonuses[k]
        self.db.update_civilization(user_id, {"bonuses": bonuses})

    def _apply_all_policies(self, user_id: str):
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return
        active = civ.get('policies', {})
        bonuses = civ.get('bonuses', {})
        for k in [k for k in bonuses if k.startswith("policy_")]:
            del bonuses[k]
        self.db.update_civilization(user_id, {"bonuses": bonuses})
        for pk, level in active.items():
            self._apply_policy_effects(user_id, pk, level, active)

    @commands.hybrid_command(name='policieshelp')
    async def policies_help(self, ctx):
        await self.policy_list(ctx)

    # =================================================================
    # REVOLUTION
    # =================================================================
    @commands.hybrid_command(name='revolution')
    @check_cooldown_decorator("revolution")
    async def revolution(self, ctx):
        user_id = _uid(ctx)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            raise CommandUsageError("You need a civilization first!")

        if civ['military']['tech_level'] < 10:
            raise CommandUsageError("You need Tech Level 10 to start the revolution!")
        if civ.get('revolution_done', False):
            raise CommandUsageError("Your civilization has already undergone a revolution!")

        cost = 500_000_000
        if civ['resources']['gold'] < cost:
            raise CommandUsageError(f"You need {format_number(cost)} gold.")

        embed = create_embed("💥 REVOLUTION",
                             "This resets tech to 1 and grants permanent +100% global production.\n\n"
                             "Type `yes` to confirm.",
                             discord.Color.red())
        await ctx.send(embed=embed)

        def check(m):
            return (m.author.id == ctx.author.id if not isinstance(ctx, discord.Interaction) else m.author.id == ctx.user.id) \
                and m.channel.id == (ctx.channel.id if not isinstance(ctx, discord.Interaction) else ctx.channel_id) \
                and m.content.lower() == "yes"

        try:
            await self.bot.wait_for('message', timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send("❌ Revolution cancelled.")
            return

        self.civ_manager.spend_resources(user_id, {"gold": cost})
        self.civ_manager.update_military(user_id, {"tech_level": -9})
        bonuses = civ.get('bonuses', {})
        bonuses['revolution_bonus'] = 100
        self.db.update_civilization(user_id, {"revolution_done": True, "bonuses": bonuses})
        await ctx.send(embed=create_embed("💥 REVOLUTION COMPLETE!",
                                          "Tech reset to 1. Permanent **+100% resource production** bonus unlocked.",
                                          discord.Color.gold()))


async def setup(bot):
    await bot.add_cog(EconomyCommands(bot))
