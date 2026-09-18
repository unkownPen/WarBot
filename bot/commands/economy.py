import random
import asyncio
import math
import json
import os
import discord as guilded
from discord.ext import commands
from datetime import datetime, timedelta
import logging
from bot.utils import (
    format_number,
    create_embed,
    get_territory_modifier,
    daily_limit_decorator,
)
from bot import config
from functools import wraps
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


# ---- Cooldown decorator with testing mode skip ----
def check_cooldown_decorator(command_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            if self.db.get_testing_mode():
                return await func(self, ctx, *args, **kwargs)
            minutes = config.COOLDOWNS.get(command_name, 0)
            if minutes <= 0:
                return await func(self, ctx, *args, **kwargs)
            user_id = str(ctx.author.id)
            last_used = self.db.get_command_cooldown(user_id, command_name)
            if last_used:
                cooldown_end = last_used + timedelta(minutes=minutes)
                if datetime.utcnow() < cooldown_end:
                    remaining = cooldown_end - datetime.utcnow()
                    mins = int(remaining.total_seconds() // 60)
                    secs = int(remaining.total_seconds() % 60)
                    await ctx.send(f"⏳ Please wait {mins}m {secs}s before using this command again!")
                    return
            result = await func(self, ctx, *args, **kwargs)
            self.db.set_command_cooldown(user_id, command_name, datetime.utcnow())
            return result
        return wrapper
    return decorator


class EconomyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self._tasks = []

    async def cog_load(self):
        self._tasks.append(asyncio.create_task(self._investment_bank_loop()))

    async def cog_unload(self):
        for t in self._tasks:
            try:
                t.cancel()
            except Exception:
                pass

    # =================================================================
    # SHARED HELPERS
    # =================================================================
    def _is_sanctioned(self, user_id: str) -> bool:
        try:
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                return False
            sanctions = civ.get('received_sanctions', []) or []
            now = datetime.utcnow()
            for s in sanctions:
                exp = s.get('expires_at')
                if exp:
                    try:
                        exp_dt = datetime.fromisoformat(exp)
                        if exp_dt > now:
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
    # PASSIVE LOOP — player bank only (corp loop moved to corporations.py)
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
                                        datetime.utcnow() +
                                        timedelta(days=config.BANKING['bank_ban_days'])
                                    ).isoformat()
                                    changed = True
                                    self.db.log_event(uid, "bank_default", "Bank Default",
                                                      f"Loan unpaid {age_days}d. Deposits seized, "
                                                      f"bank locked {config.BANKING['bank_ban_days']}d.")
                                    self.civ_manager.apply_faction_effects(uid, "bank_default")
                            except Exception:
                                pass

                    if changed:
                        self.db.update_civilization(uid, {"bank": bank})
                        self.civ_manager._invalidate_civ(uid)
            except Exception as e:
                logger.error(f"Bank loop error: {e}")

    # =================================================================
    # AI MEGAPROJECT EVALUATOR
    # =================================================================
    async def _ai_evaluate_megaproject(self, description: str, civ: dict) -> Optional[Dict[str, Any]]:
        tech_level = civ['military']['tech_level']
        pop = civ['population']['citizens']
        gold = civ['resources']['gold']
        food = civ['resources']['food']
        wood = civ['resources']['wood']
        stone = civ['resources']['stone']

        prompt = f"""You are a game balance AI for NationBot. A player wants to build a custom megaproject: "{description}".
Current player stats:
- Tech Level: {tech_level}
- Population: {pop}
- Gold: {gold}
- Food: {food}
- Wood: {wood}
- Stone: {stone}
Generate a JSON response with:
- "cost": object with gold, food, wood, stone (each number, 20-50% of stockpile, min 100,000 each)
- "effect": object with game modifiers
- "description": short description
Return ONLY valid JSON."""

        basic_cog = self.bot.get_cog("BasicCommands")
        if not basic_cog:
            return None
        try:
            response = await basic_cog.generate_ai_response([{"role": "system", "content": prompt}])
            import re
            m = re.search(r'\{.*\}', response, re.DOTALL)
            if m:
                data = json.loads(m.group())
                if "cost" in data and all(k in data["cost"] for k in ["gold", "food", "wood", "stone"]):
                    return data
            return None
        except Exception as e:
            logger.error(f"AI megaproject evaluation failed: {e}")
            return None

    # =================================================================
    # CIVIL WAR HANDLER
    # =================================================================
    async def check_civil_war_and_proceed(self, ctx, user_id: str) -> bool:
        """Silent civil-war gate. Returns True if the action may proceed."""
        try:
            result = self.civ_manager.check_civil_war_risk(user_id)
            state_active = self.civ_manager.get_civil_war_state(user_id)
            if state_active and not result:
                return False
            if not result:
                return True
            if result.get("single_territory") or not result.get("state"):
                return True

            state = result.get("state", {})
            civ = self.civ_manager.get_civilization(user_id)
            civ_name = civ['name'] if civ else "your nation"
            cause = state.get("cause", "people")
            cause_label = {
                "military": "the armed forces",
                "merchant": "the merchant guilds",
                "people": "the common people",
            }.get(cause, "rebels")
            rebel_list = ", ".join(state.get("rebel_territories", [])[:5])

            embed = create_embed(
                "💥 CIVIL WAR ERUPTS!",
                f"**Rebellion by {cause_label}!**\n"
                f"Rebels have seized **{len(state.get('rebel_territories', []))} territories**: {rebel_list}\n"
                f"Rebel strength: **{state.get('rebel_strength')}** troops\n\n"
                f"Use `.reclaim <territory>` to fight them back.\n"
                f"You have a **+30% offensive bonus** when reclaiming land.",
                guilded.Color.red()
            )
            await ctx.send(embed=embed)
            asyncio.create_task(self._post_civil_war_news(ctx.channel, civ_name, state))
            return False
        except Exception as e:
            logger.error(f"Error checking civil war for {user_id}: {e}")
            return True

    async def _post_civil_war_news(self, channel, civ_name: str, state: Dict[str, Any]):
        try:
            openrouter_key = os.getenv("OPENROUTER")
            article = await asyncio.to_thread(
                self.civ_manager.generate_civil_war_article,
                civ_name, state, openrouter_key
            )
            if article:
                for i in range(0, len(article), 1800):
                    chunk = article[i:i+1800]
                    await channel.send(f"📰 **BREAKING NEWS**\n\n{chunk}")
                    await asyncio.sleep(1)
            image_url = self.civ_manager.generate_civil_war_image_url(civ_name, state)
            await channel.send(image_url)
        except Exception as e:
            logger.error(f"_post_civil_war_news error: {e}")

    # =================================================================
    # EARLY-GAME COMMANDS
    # =================================================================
    @commands.command(name='gather')
    @check_cooldown_decorator("gather")
    @daily_limit_decorator("gather")
    async def gather_resources(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        if self.db.get_testing_mode():
            gathered = {r: config.TESTING_GAIN for r in ["gold", "wood", "stone", "food"]}
            self.civ_manager.update_resources(user_id, gathered)
            await ctx.send(embed=create_embed("🧪 TESTING MODE",
                                              f"Gained {config.TESTING_GAIN} of each resource!",
                                              guilded.Color.gold()))
            return

        possible_resources = ['gold', 'wood', 'stone', 'food']
        gathered = {}
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * config.ECONOMY["gather_employment_coeff"]
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        tech_multiplier = self._tech_mult("gather", civ['military']['tech_level'])

        for resource in possible_resources:
            if random.random() < config.ECONOMY["gather_chance"]:
                base = random.randint(config.ECONOMY["gather_base_min"], config.ECONOMY["gather_base_max"])
                amount = int(base * employment_factor * territory_factor * tech_multiplier)
                amount = min(amount, config.CAPS["gather"] * tech_multiplier)
                gathered[resource] = amount

        if not gathered:
            await ctx.send("🔍 Your scouts searched but found nothing of value this time.")
            return

        luck_modifier = self.civ_manager.calculate_total_modifier(user_id, "luck")
        if luck_modifier > 1.0:
            for resource in gathered:
                gathered[resource] = int(gathered[resource] * luck_modifier)

        gathered = self._apply_sanction_penalty(user_id, gathered)
        gathered, lucky_used = self._apply_lucky_strike_gain(user_id, gathered)
        self.civ_manager.update_resources(user_id, gathered)
        self.civ_manager.apply_faction_effects(user_id, "gather")

        embed = create_embed("🔍 Resource Gathering", "Your scouts return with valuable resources!", guilded.Color.green())
        icons = {"gold": "🪙", "wood": "🪵", "stone": "🪨", "food": "🌾"}
        embed.add_field(name="Resources Gathered",
                        value="\n".join(f"{icons[r]} {format_number(a)} {r.capitalize()}" for r, a in gathered.items()),
                        inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        if self._is_sanctioned(user_id):
            embed.add_field(name="⚠️ Sanctions", value="Gains reduced 25%", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='work')
    @check_cooldown_decorator("work")
    @daily_limit_decorator("work")
    async def work(self, ctx, amount: int = None):
        if amount is None or amount < 1:
            await ctx.send("💼 **Work Command**\nUsage: `.work <amount>`\nEmploy <amount> citizens to gain gold.")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        population = civ['population']
        current_employed = population.get('employed', 0)
        unemployed = population['citizens'] - current_employed
        if amount > unemployed:
            await ctx.send(f"❌ Only {unemployed} unemployed citizens available!")
            return

        self.civ_manager.update_employment(user_id, amount)
        tech_multiplier = self._tech_mult("work", civ['military']['tech_level'])
        gold_gain = amount * random.randint(config.ECONOMY["work_gold_per_citizen_min"], config.ECONOMY["work_gold_per_citizen_max"])
        gold_gain = int(gold_gain * tech_multiplier)
        gold_gain = min(gold_gain, config.CAPS["work"] * tech_multiplier)

        gains = {"gold": gold_gain}
        gains = self._apply_sanction_penalty(user_id, gains)
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "work")

        new_rate = self.civ_manager.get_employment_rate(user_id)
        embed = create_embed("💼 Citizens Employed",
                             f"Employed {format_number(amount)} citizens for {format_number(gains['gold'])} gold!",
                             guilded.Color.green())
        embed.add_field(name="Employment Rate", value=f"{new_rate:.1f}%", inline=True)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled gold.")
        await ctx.send(embed=embed)

    @commands.command(name='farm')
    @check_cooldown_decorator("farm")
    @daily_limit_decorator("farm")
    async def farm_food(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        base_food = random.randint(config.ECONOMY["farm_base_min"], config.ECONOMY["farm_base_max"])
        citizen_bonus = civ['population']['citizens'] // config.ECONOMY["farm_citizen_divisor"]
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * config.ECONOMY["farm_employment_coeff"]
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        tech_multiplier = self._tech_mult("farm", civ['military']['tech_level'])

        total_food = int((base_food + citizen_bonus) * employment_factor * territory_factor * tech_multiplier)
        if civ.get('ideology') == 'communism':
            total_food = int(total_food * 1.1)
        total_food = min(total_food, config.CAPS["farm"] * tech_multiplier)

        event_text = ""
        if random.random() < 0.1:
            mult = random.choice([0.5, 1.5, 2.0])
            total_food = int(total_food * mult)
            event_text = "🦗 Locust swarm damaged crops!" if mult < 1 else "🌈 Perfect weather blessed your harvest!"

        gains = {"food": total_food}
        gains = self._apply_sanction_penalty(user_id, gains)
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "farm")

        embed = create_embed("🌾 Farming", f"Farmers produced {format_number(gains['food'])} food!", guilded.Color.green())
        if event_text:
            embed.add_field(name="Special Event", value=event_text, inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled food.")
        await ctx.send(embed=embed)

    @commands.command(name='mine')
    @check_cooldown_decorator("mine")
    @daily_limit_decorator("mine")
    async def mine_resources(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        stone_yield = random.randint(config.ECONOMY["mine_stone_base_min"], config.ECONOMY["mine_stone_base_max"])
        wood_yield = random.randint(config.ECONOMY["mine_wood_base_min"], config.ECONOMY["mine_wood_base_max"])

        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * config.ECONOMY["mine_employment_coeff"]
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        tech_multiplier = self._tech_mult("mine", civ['military']['tech_level'])

        stone_yield = int(stone_yield * employment_factor * territory_factor * tech_multiplier)
        wood_yield = int(wood_yield * employment_factor * territory_factor * tech_multiplier)

        stone_yield = min(stone_yield, config.CAPS["mine_stone"] * tech_multiplier)
        wood_yield = min(wood_yield, config.CAPS["mine_wood"] * tech_multiplier)

        bonus_gold = 0
        if random.random() < config.ECONOMY["mine_bonus_gold_chance"]:
            bonus_gold = random.randint(config.ECONOMY["mine_bonus_gold_min"], config.ECONOMY["mine_bonus_gold_max"])
            bonus_gold = min(bonus_gold, config.ECONOMY["mine_bonus_gold_cap"])

        gains = {"stone": stone_yield, "wood": wood_yield}
        if bonus_gold > 0:
            gains["gold"] = bonus_gold
        gains = self._apply_sanction_penalty(user_id, gains)
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "mine")

        embed = create_embed("⛏️ Mining Operation", "Miners extracted resources!", guilded.Color.blue())
        result_text = f"🪨 {format_number(gains['stone'])} Stone\n🪵 {format_number(gains['wood'])} Wood"
        if bonus_gold > 0:
            result_text += f"\n🪙 {format_number(gains.get('gold', 0))} Gold (Lucky find!)"
        embed.add_field(name="Resources Extracted", value=result_text, inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        await ctx.send(embed=embed)

    @commands.command(name='harvest')
    @check_cooldown_decorator("harvest")
    @daily_limit_decorator("harvest")
    async def harvest_food(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        pop = civ['population']['citizens']
        happiness = civ['population']['happiness']
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        tech_multiplier = self._tech_mult("harvest", civ['military']['tech_level'])

        total_harvest = int((pop * 2 + happiness * 5) * territory_factor * 0.5 * tech_multiplier)
        total_harvest = min(total_harvest, config.CAPS["harvest"] * tech_multiplier)

        gains = {"food": total_harvest}
        gains = self._apply_sanction_penalty(user_id, gains)
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.update_population(user_id, {"happiness": 3})
        self.civ_manager.apply_faction_effects(user_id, "harvest")

        embed = create_embed("🌽 Great Harvest",
                             f"Bountiful harvest: {format_number(gains['food'])} food!",
                             guilded.Color.gold())
        embed.add_field(name="Morale Boost", value="+3 happiness", inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled food.")
        await ctx.send(embed=embed)

    @commands.command(name='drill')
    @check_cooldown_decorator("drill")
    @daily_limit_decorator("drill")
    async def drill_minerals(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
        if civ['military']['tech_level'] < 2:
            await ctx.send("❌ You need Tech Level 2 to drill!")
            return

        tech = civ['military']['tech_level']
        pop = civ['population']['citizens']
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        tech_multiplier = self._tech_mult("drill", tech)

        base = 200 + (tech * 50) + (pop // 20)
        gold_gain = int(base * 2 * territory_factor * tech_multiplier)
        stone_gain = int(base * 1.5 * territory_factor * tech_multiplier)

        gold_gain = min(gold_gain, config.CAPS["drill_gold"] * tech_multiplier)
        stone_gain = min(stone_gain, config.CAPS["drill_stone"] * tech_multiplier)

        gains = {"gold": gold_gain, "stone": stone_gain}
        gains = self._apply_sanction_penalty(user_id, gains)
        gains, lucky_used = self._apply_lucky_strike_gain(user_id, gains)
        self.civ_manager.update_resources(user_id, gains)
        self.civ_manager.apply_faction_effects(user_id, "drill")

        embed = create_embed("⛏️ Deep Drilling",
                             f"Extracted {format_number(gains['gold'])} gold and {format_number(gains['stone'])} stone!",
                             guilded.Color.purple())
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        await ctx.send(embed=embed)

    @commands.command(name='labor', aliases=['labour'])
    @check_cooldown_decorator("labor")
    @daily_limit_decorator("labor")
    async def forced_labor(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
        if civ['military']['tech_level'] < 3:
            await ctx.send("❌ You need Tech Level 3 for forced labor!")
            return

        pop = civ['population']['citizens']
        tech = civ['military']['tech_level']
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        tech_multiplier = self._tech_mult("labor", tech)

        base = 50 + (pop // 10) + (tech * 20)
        loot = {
            "gold": int(base * 1.2 * territory_factor * tech_multiplier),
            "food": int(base * 1.0 * territory_factor * tech_multiplier),
            "wood": int(base * 1.5 * territory_factor * tech_multiplier),
            "stone": int(base * 1.5 * territory_factor * tech_multiplier)
        }
        for key in loot:
            loot[key] = min(loot[key], config.CAPS["labor"] * tech_multiplier)

        loot = self._apply_sanction_penalty(user_id, loot)
        loot, lucky_used = self._apply_lucky_strike_gain(user_id, loot)
        self.civ_manager.update_resources(user_id, loot)
        self.civ_manager.update_population(user_id, {"happiness": config.ECONOMY["labor_happiness_cost"]})
        self.civ_manager.apply_faction_effects(user_id, "labor")

        embed = create_embed("⛏️ Forced Labor", "Citizens worked tirelessly!", guilded.Color.orange())
        icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        embed.add_field(name="Resources",
                        value="\n".join(f"{icons[r]} {format_number(a)} {r.capitalize()}" for r, a in loot.items()),
                        inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled yields.")
        await ctx.send(embed=embed)

    @commands.command(name='raidcaravan')
    @check_cooldown_decorator("raidcaravan")
    @daily_limit_decorator("raidcaravan")
    async def raid_caravan(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        military = civ['military']
        if military['soldiers'] < config.ECONOMY["raid_min_soldiers"]:
            await ctx.send(f"❌ You need {config.ECONOMY['raid_min_soldiers']} soldiers to raid caravans!")
            return

        base_success = 0.6
        soldier_bonus = min(0.3, military['soldiers'] / 100)
        spy_bonus = min(0.1, military['spies'] / 50)
        success_chance = base_success + soldier_bonus + spy_bonus
        if civ.get('ideology') == 'anarchy':
            success_chance += 0.1

        if random.random() < success_chance:
            soldier_power = military['soldiers'] * 2
            territory_factor = get_territory_modifier(civ['territory']['land_size']) ** 1.3
            tech = civ['military']['tech_level']
            tech_multiplier = self._tech_mult("raid", tech)

            loot = {
                "gold": int(random.randint(config.ECONOMY["raid_gold_min"], config.ECONOMY["raid_gold_max"]) * territory_factor * (1 + soldier_power/500) * tech_multiplier),
                "food": int(random.randint(config.ECONOMY["raid_food_min"], config.ECONOMY["raid_food_max"]) * territory_factor * (1 + soldier_power/500) * tech_multiplier),
                "wood": int(random.randint(config.ECONOMY["raid_wood_min"], config.ECONOMY["raid_wood_max"]) * territory_factor * (1 + soldier_power/500) * tech_multiplier),
                "stone": int(random.randint(config.ECONOMY["raid_stone_min"], config.ECONOMY["raid_stone_max"]) * territory_factor * (1 + soldier_power/500) * tech_multiplier)
            }
            if random.random() < config.ECONOMY["raid_bonus_gold_chance"]:
                loot["gold"] += random.randint(config.ECONOMY["raid_bonus_gold_min"], config.ECONOMY["raid_bonus_gold_max"])
            for key in loot:
                loot[key] = min(loot[key], config.CAPS["raidcaravan"] * tech_multiplier)

            loot = self._apply_sanction_penalty(user_id, loot)
            loot, lucky_used = self._apply_lucky_strike_gain(user_id, loot)
            self.civ_manager.update_resources(user_id, loot)
            self.civ_manager.apply_faction_effects(user_id, "raidcaravan")

            embed = create_embed("🏴‍☠️ Caravan Raid - Success!",
                                 "Raiders ambushed a wealthy caravan!",
                                 guilded.Color.green())
            icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
            embed.add_field(name="Loot",
                            value="\n".join(f"{icons[r]} {format_number(a)} {r.capitalize()}" for r, a in loot.items() if a > 0),
                            inline=False)
            if lucky_used:
                embed.set_footer(text="🍀 Lucky Strike! Doubled loot.")
        else:
            loss = random.randint(1, 3)
            self.civ_manager.update_military(user_id, {"soldiers": -loss})
            embed = create_embed("🏴‍☠️ Caravan Raid - Failed!",
                                 f"Guards were too strong. Lost {loss} soldiers.",
                                 guilded.Color.red())
        await ctx.send(embed=embed)

    # =================================================================
    # LATE-GAME COMMANDS
    # =================================================================
    @commands.command(name='globaltrade')
    @check_cooldown_decorator("globaltrade")
    @daily_limit_decorator("globaltrade")
    async def global_trade(self, ctx, resource: str = None, amount: int = None):
        if resource not in ("gold", "food", "wood", "stone") or amount is None:
            await ctx.send("🌍 **Global Trade**\nUsage: `.globaltrade <gold|food|wood|stone> <amount>`\nMinimum 10,000. Requires Tech 3.")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first!")
            return

        if self._is_sanctioned(user_id):
            await ctx.send("🚫 **You are under sanctions.** Global trade is blocked until your sanctions expire.")
            return

        tech = civ['military']['tech_level']
        if tech < 3:
            await ctx.send("❌ You need Tech Level 3 to access global trade!")
            return
        if amount < 10000:
            await ctx.send("❌ Minimum trade amount is 10,000.")
            return

        margin = 1.0 + (tech * 0.03)
        resources = ["gold", "food", "wood", "stone"]
        resources.remove(resource)
        receive = random.choice(resources)
        receive_amount = int(amount * margin)

        if not self.civ_manager.can_afford(user_id, {resource: amount}):
            await ctx.send(f"❌ You don't have {format_number(amount)} {resource}.")
            return

        self.civ_manager.spend_resources(user_id, {resource: amount})
        self.civ_manager.update_resources(user_id, {receive: receive_amount})
        self.civ_manager.apply_faction_effects(user_id, "globaltrade")

        embed = create_embed("🌍 Global Trade",
                             f"Traded {format_number(amount)} {resource} for {format_number(receive_amount)} {receive} (profit: {int((margin-1)*100)}%)",
                             guilded.Color.blue())
        await ctx.send(embed=embed)

    @commands.command(name='investmentbank')
    @check_cooldown_decorator("investmentbank")
    @daily_limit_decorator("investmentbank")
    async def investment_bank(self, ctx, action: str = None, amount: int = None):
        if action not in ("deposit", "withdraw", "balance"):
            await ctx.send("🏦 **Investment Bank**\nUsage: `.investmentbank <deposit|withdraw|balance> [amount]`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first!")
            return

        if self._is_sanctioned(user_id):
            await ctx.send("🚫 **You are under sanctions.** Banking is blocked until your sanctions expire.")
            return

        bank = civ.get('bank', {})
        if action == "balance":
            deposits = bank.get('deposits', 0)
            tech = civ['military']['tech_level']
            rate = (0.005 + (tech * 0.001)) * 100
            embed = create_embed("🏦 Investment Bank Balance",
                                 f"Current deposits: {format_number(deposits)} gold",
                                 guilded.Color.blue())
            embed.add_field(name="Interest Rate", value=f"{rate:.2f}% per hour", inline=True)
            embed.add_field(name="Projected Daily Growth",
                            value=f"{format_number(int(deposits * (rate/100) * 24))} gold/day",
                            inline=True)
            await ctx.send(embed=embed)
            return

        if action == "deposit":
            if amount is None or amount <= 0:
                await ctx.send("❌ Please specify a positive amount.")
                return
            if not self.civ_manager.can_afford(user_id, {"gold": amount}):
                await ctx.send(f"❌ You don't have {format_number(amount)} gold.")
                return
            self.civ_manager.spend_resources(user_id, {"gold": amount})
            bank['deposits'] = bank.get('deposits', 0) + amount
            bank['last_interest'] = datetime.utcnow().isoformat()
            self.db.update_civilization(user_id, {"bank": bank})
            await ctx.send(f"🏦 Deposited {format_number(amount)} gold. Balance: {format_number(bank['deposits'])}.")
            return

        if action == "withdraw":
            if amount is None or amount <= 0:
                await ctx.send("❌ Please specify a positive amount.")
                return
            if bank.get('deposits', 0) < amount:
                await ctx.send(f"❌ You only have {format_number(bank.get('deposits', 0))} in the bank.")
                return
            bank['deposits'] -= amount
            self.db.update_civilization(user_id, {"bank": bank})
            self.civ_manager.update_resources(user_id, {"gold": amount})
            await ctx.send(f"🏦 Withdrew {format_number(amount)} gold. Balance: {format_number(bank['deposits'])}.")
            return

    @commands.command(name='revolution')
    @check_cooldown_decorator("revolution")
    @daily_limit_decorator("revolution")
    async def revolution(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first!")
            return

        if civ['military']['tech_level'] < 10:
            await ctx.send("❌ You need Tech Level 10 to start the revolution!")
            return
        if civ.get('revolution_done', False):
            await ctx.send("❌ Your civilization has already undergone a revolution!")
            return

        cost = 500_000_000
        if civ['resources']['gold'] < cost:
            await ctx.send(f"❌ You need {format_number(cost)} gold.")
            return

        embed = create_embed("💥 REVOLUTION",
                             "This resets tech to 1 and grants permanent +100% global production.\n\nType `yes` to confirm.",
                             guilded.Color.red())
        await ctx.send(embed=embed)

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() == "yes"

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
                                          guilded.Color.gold()))

    @commands.command(name='cheerup')
    @check_cooldown_decorator("cheerup")
    @daily_limit_decorator("cheerup")
    async def cheer_up(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first!")
            return
        if civ['resources']['gold'] < 2000:
            await ctx.send("❌ You need 2000 gold!")
            return
        self.civ_manager.spend_resources(user_id, {"gold": 2000})
        current = civ['population']['happiness']
        boost = int((100 - current) * 0.5)
        self.civ_manager.update_population(user_id, {"happiness": boost})
        self.civ_manager.apply_faction_effects(user_id, "cheerup")
        await ctx.send(embed=create_embed("😊 Cheer Up!",
                                          f"Citizens are much happier! (+{boost} happiness)",
                                          guilded.Color.green()))

    @commands.command(name='buytech', aliases=['buylevel'])
    @check_cooldown_decorator("buytech")
    @daily_limit_decorator("buytech")
    async def buy_tech_level(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first!")
            return
        current_level = civ['military']['tech_level']
        if current_level >= 10:
            await ctx.send("❌ Max tech level (10)!")
            return
        if civ['resources']['gold'] < 2000:
            await ctx.send("❌ You need 2000 gold!")
            return
        self.civ_manager.spend_resources(user_id, {"gold": 2000})
        self.civ_manager.update_military(user_id, {"tech_level": 1})
        new_level = current_level + 1
        await ctx.send(embed=create_embed("🔬 Technology Purchased!",
                                          f"Tech level: **{current_level}** → **{new_level}**",
                                          guilded.Color.blue()))

    # =================================================================
    # MEGAPROJECTS (corporation group removed — moved to corporations.py)
    # =================================================================
    @commands.group(name='megaproject', invoke_without_command=True)
    async def megaproject(self, ctx):
        embed = create_embed("🏗️ Megaprojects",
                             "**Custom:** `.megaproject build <description>`\n"
                             "**Presets:** `.megaproject preset <name>`\n"
                             "**List presets:** `.megaproject presets`",
                             guilded.Color.gold())
        await ctx.send(embed=embed)

    @megaproject.command(name='presets')
    async def megaproject_presets(self, ctx):
        embed = create_embed("📜 Predefined Megaprojects", "", guilded.Color.blue())
        for key, data in config.MEGAPROJECTS.items():
            cost_str = ", ".join([f"{amt} {res}" for res, amt in data['cost'].items()])
            embed.add_field(name=f"{data['name']} (Tech {data['tech_required']})",
                            value=f"Cost: {cost_str}\nEffect: {data['description']}",
                            inline=False)
        embed.add_field(name="Usage", value="`.megaproject preset <name>`", inline=False)
        await ctx.send(embed=embed)

    @megaproject.command(name='preset')
    async def megaproject_preset_build(self, ctx, preset_name: str):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        preset = None
        for key, data in config.MEGAPROJECTS.items():
            if key.lower() == preset_name.lower() or data['name'].lower() == preset_name.lower():
                preset = (key, data)
                break
        if not preset:
            await ctx.send("❌ Unknown preset. Use `.megaproject presets`.")
            return
        key, data = preset
        if civ['military']['tech_level'] < data['tech_required']:
            await ctx.send(f"❌ You need Tech Level {data['tech_required']}!")
            return
        built = civ.get('megaprojects', [])
        if key in built:
            await ctx.send(f"❌ Already built {data['name']}!")
            return
        if not self.civ_manager.can_afford(user_id, data['cost']):
            cost_str = ", ".join([f"{amt} {res}" for res, amt in data['cost'].items()])
            await ctx.send(f"❌ Cannot afford! Requires: {cost_str}")
            return
        self.civ_manager.spend_resources(user_id, data['cost'])
        built.append(key)
        bonuses = civ.get('bonuses', {})
        for ek, ev in data['effect'].items():
            bonuses[ek] = bonuses.get(ek, 0) + ev
        self.db.update_civilization(user_id, {"megaprojects": built, "bonuses": bonuses})
        self.civ_manager.apply_faction_effects(user_id, "build_megaproject")
        await ctx.send(embed=create_embed(f"🏗️ {data['name']} Complete!",
                                          data['description'],
                                          guilded.Color.gold()))

    @megaproject.command(name='build')
    async def megaproject_build_custom(self, ctx, *, description: str):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if civ['military']['tech_level'] < 4:
            await ctx.send("❌ You need Tech Level 4!")
            return
        if civ.get('custom_megaproject_built', False):
            await ctx.send("❌ Only one custom megaproject per civ!")
            return
        await ctx.send("🧠 Consulting the AI...")
        ai = await self._ai_evaluate_megaproject(description, civ)
        if not ai:
            await ctx.send("❌ AI couldn't evaluate your project.")
            return
        cost = ai.get("cost", {})
        effect = ai.get("effect", {})
        proj_desc = ai.get("description", description)
        for res in ["gold", "food", "wood", "stone"]:
            if res not in cost or cost[res] < 100000:
                cost[res] = 100000
        if not self.civ_manager.can_afford(user_id, cost):
            cost_str = ", ".join([f"{amt} {res}" for res, amt in cost.items()])
            await ctx.send(f"❌ Cannot afford! Requires: {cost_str}")
            return
        self.civ_manager.spend_resources(user_id, cost)
        bonuses = civ.get('bonuses', {})
        for ek, ev in effect.items():
            bonuses[ek] = bonuses.get(ek, 0) + ev
        self.db.update_civilization(user_id, {
            "megaprojects": civ.get('megaprojects', []) + ["custom_megaproject"],
            "bonuses": bonuses,
            "custom_megaproject_built": True
        })
        embed = create_embed("🏗️ Custom Megaproject Built!",
                             f"**Project:** {proj_desc}\n\n**Cost:**\n" +
                             "\n".join([f"{'🪙' if res=='gold' else '🌾' if res=='food' else '🪵' if res=='wood' else '🪨'} {format_number(amt)} {res.capitalize()}"
                                        for res, amt in cost.items()]),
                             guilded.Color.gold())
        await ctx.send(embed=embed)

    # =================================================================
    # POLICIES
    # =================================================================
    @commands.group(name='policy', invoke_without_command=True)
    async def policy(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        active = civ.get('policies', {})
        if not active:
            await ctx.send("📭 No active policies. Use `.policy enable <name>`.")
            return
        embed = create_embed("📜 Active Policies", "", guilded.Color.blue())
        for pk, level in active.items():
            if pk in config.POLICIES:
                pdata = config.POLICIES[pk]
                ld = pdata['levels'].get(level)
                if ld:
                    embed.add_field(name=f"{pdata['name']} (Level {level})",
                                    value=ld['desc'],
                                    inline=False)
        await ctx.send(embed=embed)

    @policy.command(name='enable')
    async def policy_enable(self, ctx, policy_name: str):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        pk = None
        for key, data in config.POLICIES.items():
            if key.lower() == policy_name.lower() or data['name'].lower() == policy_name.lower():
                pk = key
                break
        if not pk:
            await ctx.send("❌ Unknown policy. Use `.policieshelp`.")
            return
        active = civ.get('policies', {})
        if pk in active:
            await ctx.send("❌ Already active.")
            return
        pdata = config.POLICIES[pk]
        ld = pdata['levels'][1]
        cost = {res.replace('_cost', ''): amt for res, amt in ld.items() if res.endswith('_cost')}
        if not self.civ_manager.can_afford(user_id, cost):
            cost_str = ", ".join([f"{amt} {res}" for res, amt in cost.items()])
            await ctx.send(f"❌ Cannot afford! Requires: {cost_str}")
            return
        self.civ_manager.spend_resources(user_id, cost)
        active[pk] = 1
        self.db.update_civilization(user_id, {"policies": active})
        self._apply_policy_effects(user_id, pk, 1, active)
        await ctx.send(f"✅ Enabled **{pdata['name']}** Level 1!")

    @policy.command(name='upgrade')
    async def policy_upgrade(self, ctx, policy_name: str):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        pk = None
        for key, data in config.POLICIES.items():
            if key.lower() == policy_name.lower() or data['name'].lower() == policy_name.lower():
                pk = key
                break
        if not pk:
            await ctx.send("❌ Unknown policy.")
            return
        active = civ.get('policies', {})
        if pk not in active:
            await ctx.send("❌ Not active. Enable first.")
            return
        pdata = config.POLICIES[pk]
        cl = active[pk]
        if cl >= pdata['max_level']:
            await ctx.send(f"❌ Already max level ({pdata['max_level']}).")
            return
        nl = cl + 1
        ld = pdata['levels'][nl]
        cost = {res.replace('_cost', ''): amt for res, amt in ld.items() if res.endswith('_cost')}
        if not self.civ_manager.can_afford(user_id, cost):
            cost_str = ", ".join([f"{amt} {res}" for res, amt in cost.items()])
            await ctx.send(f"❌ Cannot afford! Requires: {cost_str}")
            return
        self.civ_manager.spend_resources(user_id, cost)
        active[pk] = nl
        self.db.update_civilization(user_id, {"policies": active})
        self._apply_policy_effects(user_id, pk, nl, active)
        await ctx.send(f"⬆️ Upgraded **{pdata['name']}** to Level {nl}!")

    @policy.command(name='disable')
    async def policy_disable(self, ctx, policy_name: str):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        pk = None
        for key, data in config.POLICIES.items():
            if key.lower() == policy_name.lower() or data['name'].lower() == policy_name.lower():
                pk = key
                break
        if not pk:
            await ctx.send("❌ Unknown policy.")
            return
        active = civ.get('policies', {})
        if pk not in active:
            await ctx.send("❌ Not active.")
            return
        del active[pk]
        self.db.update_civilization(user_id, {"policies": active})
        self._apply_all_policies(user_id)
        await ctx.send(f"❌ Disabled **{config.POLICIES[pk]['name']}**.")

    @policy.command(name='list')
    async def policy_list(self, ctx):
        embed = create_embed("📜 Available Policies", "Use `.policy enable <name>`.", guilded.Color.blue())
        for key, data in config.POLICIES.items():
            embed.add_field(name=f"{data['name']} (Max {data['max_level']})",
                            value=f"{data['base_desc']}\nLevel 1: {data['levels'][1]['desc']}",
                            inline=False)
        await ctx.send(embed=embed)

    def _format_cost(self, level_data: dict) -> str:
        items = []
        for key, val in level_data.items():
            if key.endswith('_cost'):
                items.append(f"{val} {key.replace('_cost', '')}")
        return ", ".join(items) if items else "Free"

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

    @commands.command(name='policieshelp')
    async def policies_help(self, ctx):
        await self.policy_list(ctx)

    # =================================================================
    # TAX
    # =================================================================
    @commands.command(name='tax')
    @check_cooldown_decorator("tax")
    @daily_limit_decorator("tax")
    async def collect_taxes(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        population = civ['population']
        tech = civ['military']['tech_level']
        happiness = population['happiness']

        base_tax = population['citizens'] * (1 + tech * 0.25)
        happiness_modifier = max(0.0, happiness / 100)
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * 0.2

        land = civ['territory']['land_size']
        if land <= 0:
            territory_factor = 1.0
        else:
            territory_factor = min(1.0 + 0.15 * math.log10(land / 1000 + 1), 1.5)

        total_tax = int(base_tax * happiness_modifier * employment_factor * territory_factor)

        TAX_CAP = 150_000
        capped = total_tax > TAX_CAP
        total_tax = min(total_tax, TAX_CAP)

        ideology = civ.get('ideology', '')
        if ideology == 'democracy':
            total_tax = int(total_tax * 1.05)
        elif ideology == 'fascism':
            total_tax = int(total_tax * 1.1)
        elif ideology == 'communism':
            total_tax = int(total_tax * 0.8)

        if total_tax >= 120_000:
            happiness_cost = -30
        elif total_tax >= 80_000:
            happiness_cost = -20
        elif total_tax >= 40_000:
            happiness_cost = -12
        elif total_tax >= 10_000:
            happiness_cost = -7
        else:
            happiness_cost = -3

        if ideology == 'fascism':
            happiness_cost -= 5

        tax_gains = {"gold": total_tax}
        tax_gains = self._apply_sanction_penalty(user_id, tax_gains)
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
                             f"Collected {format_number(tax_gains['gold'])} gold in taxes.",
                             guilded.Color.gold())
        embed.add_field(name="Social Cost", value=f"😡 Happiness: {happiness_cost}", inline=True)
        if capped:
            embed.add_field(name="⚠️ Hard Cap",
                            value=f"Tax capped at {format_number(TAX_CAP)} per collection.",
                            inline=False)
        if population_loss > 0:
            embed.add_field(name="💀 Population Loss",
                            value=f"{population_loss} citizens emigrated!",
                            inline=False)
        if soldier_loss > 0:
            embed.add_field(name="⚔️ Desertion",
                            value=f"{soldier_loss} soldiers deserted!",
                            inline=False)
        if riot:
            embed.add_field(name="🔥 Tax Revolt", value="Riots broke out!", inline=False)
        if lucky_used:
            embed.set_footer(text="🍀 Lucky Strike! Doubled tax.")
        await ctx.send(embed=embed)

    # =================================================================
    # REMAINING ECONOMY COMMANDS
    # =================================================================
    @commands.command(name='lottery')
    @check_cooldown_decorator("lottery")
    @daily_limit_decorator("lottery")
    async def play_lottery(self, ctx, bet: int = None):
        if bet is None:
            await ctx.send("💸 **Lottery**\nUsage: `.lottery <amount>`\nMinimum: 50 gold")
            return
        if bet < 50:
            await ctx.send("❌ Minimum bet is 50 gold!")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if not self.civ_manager.can_afford(user_id, {"gold": bet}):
            await ctx.send(f"❌ You don't have {format_number(bet)} gold!")
            return

        self.civ_manager.spend_resources(user_id, {"gold": bet})
        roll = random.random()
        if roll < 0.01:
            winnings = bet * 50
            result = f"🎰 **MEGA JACKPOT!** Won {format_number(winnings)} gold!"
            color = guilded.Color.gold()
        elif roll < 0.05:
            winnings = bet * 10
            result = f"🎰 **Big Win!** Won {format_number(winnings)} gold!"
            color = guilded.Color.green()
        elif roll < 0.20:
            winnings = bet * 2
            result = f"🎰 **Winner!** Won {format_number(winnings)} gold!"
            color = guilded.Color.green()
        elif roll < 0.40:
            winnings = bet
            result = "🎰 Break even."
            color = guilded.Color.blue()
        else:
            winnings = 0
            result = "🎰 No luck."
            color = guilded.Color.red()

        if winnings > 0:
            winnings = min(winnings, 10000000)
            self.civ_manager.update_resources(user_id, {"gold": winnings})

        embed = create_embed("🎰 Lottery Results", result, color)
        embed.add_field(name="Bet", value=f"{format_number(bet)} gold", inline=True)
        if winnings > 0:
            embed.add_field(name="Winnings", value=f"{format_number(winnings)} gold", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='invest')
    @check_cooldown_decorator("invest")
    @daily_limit_decorator("invest")
    async def invest_gold(self, ctx, amount: int = None):
        if amount is None:
            await ctx.send("💼 **Investment**\nUsage: `.invest <gold>`\nReturns in 2h, 80% success.")
            return
        if amount < 100:
            await ctx.send("❌ Minimum 100 gold!")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if not self.civ_manager.can_afford(user_id, {"gold": amount}):
            await ctx.send(f"❌ You don't have {format_number(amount)} gold!")
            return

        self.civ_manager.spend_resources(user_id, {"gold": amount})
        self.civ_manager.apply_faction_effects(user_id, "invest")
        await ctx.send(embed=create_embed("💼 Investment Made",
                                          f"Invested {format_number(amount)} gold. Returns in 2h.",
                                          guilded.Color.blue()))

        async def investment_return():
            await asyncio.sleep(7200)
            if random.random() < 0.8:
                mult = random.uniform(1.2, 1.8)
                returns = min(int(amount * mult), 10000000)
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

    @commands.command(name='drive')
    async def drive_citizens(self, ctx, amount: int = None):
        if amount is None or amount < 1:
            await ctx.send("🚗 **Drive**\nUsage: `.drive <amount>`")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        current_employed = civ['population'].get('employed', 0)
        if amount > current_employed:
            await ctx.send(f"❌ Only {current_employed} employed citizens!")
            return
        self.civ_manager.update_employment(user_id, -amount)
        self.civ_manager.update_population(user_id, {"happiness": -2})
        new_rate = self.civ_manager.get_employment_rate(user_id)
        embed = create_embed("🚗 Citizens Unemployed",
                             f"Unemployed {format_number(amount)} citizens.",
                             guilded.Color.red())
        embed.add_field(name="Employment Rate", value=f"{new_rate:.1f}%", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='festival')
    @check_cooldown_decorator("festival")
    @daily_limit_decorator("festival")
    async def hold_festival(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        cost = {"gold": 200, "food": 100}
        if not self.civ_manager.can_afford(user_id, cost):
            await ctx.send("❌ Need 200 gold and 100 food!")
            return
        self.civ_manager.spend_resources(user_id, cost)
        boost = 10
        if civ.get('ideology') == 'theocracy':
            boost = int(boost * 1.2)
        self.civ_manager.update_population(user_id, {"happiness": boost})
        self.civ_manager.apply_faction_effects(user_id, "festival")
        await ctx.send(embed=create_embed("🎉 Grand Festival",
                                          f"+{boost} happiness!",
                                          guilded.Color.gold()))

    @commands.command(name='cheer')
    @check_cooldown_decorator("cheer")
    @daily_limit_decorator("cheer")
    async def cheer_citizens(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if not self.civ_manager.can_afford(user_id, {"gold": 50}):
            await ctx.send("❌ Need 50 gold!")
            return
        self.civ_manager.spend_resources(user_id, {"gold": 50})
        boost = 5
        if civ.get('ideology') == 'democracy':
            boost = int(boost * 1.1)
        self.civ_manager.update_population(user_id, {"happiness": boost})
        self.civ_manager.apply_faction_effects(user_id, "cheer")
        await ctx.send(embed=create_embed("😊 Spreading Cheer",
                                          f"+{boost} happiness!",
                                          guilded.Color.green()))

    @commands.command(name='sell')
    async def sell_hyper_item(self, ctx, *, item_name: str = None):
        if not item_name:
            await ctx.send("💰 **Sell**\nUsage: `.sell <item-name>`")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        hyper_items = civ['hyper_items']
        if item_name not in hyper_items:
            await ctx.send(f"❌ You don't have '{item_name}'!")
            return

        prices = {
            "Lucky-Charm": random.randint(config.ECONOMY["sell_common_min"], config.ECONOMY["sell_common_max"]),
            "Ancient-Relic": random.randint(config.ECONOMY["sell_rare_min"], config.ECONOMY["sell_rare_max"]),
            "Crystal-Heart": random.randint(config.ECONOMY["sell_rare_min"], config.ECONOMY["sell_rare_max"]),
            "Dragon-Scale": random.randint(config.ECONOMY["sell_rare_min"] + 50, config.ECONOMY["sell_rare_max"] + 50),
            "Phoenix-Feather": random.randint(config.ECONOMY["sell_legendary_min"], config.ECONOMY["sell_legendary_max"])
        }
        gold_value = min(prices.get(item_name, random.randint(50, 150)), config.CAPS["sell"])
        self.civ_manager.use_hyper_item(user_id, item_name)
        self.civ_manager.update_resources(user_id, {"gold": gold_value})
        await ctx.send(embed=create_embed("💰 Item Sold!",
                                          f"Sold '{item_name}' for {format_number(gold_value)} gold!",
                                          guilded.Color.gold()))

    @commands.command(name='advertise')
    @check_cooldown_decorator("advertise")
    @daily_limit_decorator("advertise")
    async def advertise_civilization(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        ad_cost = config.ECONOMY["advertise_cost"]
        if not self.civ_manager.can_afford(user_id, {"gold": ad_cost}):
            await ctx.send(f"❌ Need {ad_cost} gold!")
            return
        self.civ_manager.spend_resources(user_id, {"gold": ad_cost})
        tech_multiplier = 1 + (civ['military']['tech_level'] * 0.05)
        base = random.randint(config.ECONOMY["advertise_citizen_min"], config.ECONOMY["advertise_citizen_max"])
        happiness_bonus = civ['population']['happiness'] // 10
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * config.ECONOMY["advertise_employment_coeff"]
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        total = int((base + happiness_bonus) * employment_factor * territory_factor * tech_multiplier)
        total = min(total, config.CAPS["advertise"] * tech_multiplier)
        if civ.get('ideology') == 'democracy':
            total = int(total * 1.2)
        elif civ.get('ideology') == 'fascism':
            total = int(total * 0.8)
        self.civ_manager.update_population(user_id, {"citizens": total})
        self.civ_manager.apply_faction_effects(user_id, "advertise")
        await ctx.send(embed=create_embed("📢 Advertising Campaign",
                                          f"{format_number(total)} people became citizens!",
                                          guilded.Color.green()))

    @commands.command(name='census')
    async def show_census(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        resources = civ['resources']
        population = civ['population']
        employment_rate = self.civ_manager.get_employment_rate(user_id)
        embed = create_embed("📊 National Census Report",
                             f"Status of {civ['name']}",
                             guilded.Color.blue())
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
        await ctx.send(embed=embed)

    @commands.command(name='recruit')
    async def recruit_soldiers(self, ctx, number: int = None):
        if number is None or number < 1:
            await ctx.send("🎖️ **Recruit**\nUsage: `.recruit <number>`")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        population = civ['population']
        current = population['citizens']
        if number > current:
            await ctx.send(f"❌ Only {format_number(current)} citizens available!")
            return

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
                                 guilded.Color.green())
            embed.add_field(name="New Military",
                            value=f"🛡️ {format_number(civ['military']['soldiers'] + number)} Soldiers",
                            inline=True)
        else:
            lost = min(number * 2, current // 2)
            self.civ_manager.update_population(user_id, {"citizens": -lost, "happiness": -5})
            embed = create_embed("🎖️ Recruitment Failed!",
                                 f"{format_number(lost)} citizens fled.",
                                 guilded.Color.red())
        await ctx.send(embed=embed)

    @commands.command(name='buysoldiers')
    async def buy_soldiers(self, ctx, amount: int = None):
        if amount is None or amount < 1:
            await ctx.send(f"⚔️ **Buy Soldiers**\nUsage: `.buysoldiers <amount>`\nCost: {config.MILITARY['soldier_buy_cost']} gold each.")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        cost = amount * config.MILITARY['soldier_buy_cost']
        if not self.civ_manager.can_afford(user_id, {"gold": cost}):
            await ctx.send(f"❌ Need {format_number(cost)} gold!")
            return
        self.civ_manager.spend_resources(user_id, {"gold": cost})
        self.civ_manager.update_military(user_id, {"soldiers": amount})
        await ctx.send(embed=create_embed("⚔️ Soldiers Bought!",
                                          f"Bought {format_number(amount)} soldiers for {format_number(cost)} gold!",
                                          guilded.Color.green()))

    @commands.command(name='burn')
    async def burn_resources(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        resources = civ['resources']
        changes = {res: 1000 - resources.get(res, 0)
                   for res in ['gold', 'food', 'wood', 'stone']
                   if resources.get(res, 0) > 1000}
        if not changes:
            await ctx.send("✅ All resources already ≤1000.")
            return
        self.civ_manager.update_resources(user_id, changes)
        embed = create_embed("🔥 Resources Burned!",
                             "Excess reduced to 1000 each.",
                             guilded.Color.orange())
        for res, change in changes.items():
            embed.add_field(name=res.capitalize(),
                            value=f"{format_number(resources[res])} → 1000",
                            inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='immigration')
    @check_cooldown_decorator("immigration")
    @daily_limit_decorator("immigration")
    async def open_immigration(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return

        tech_multiplier = 1 + (civ['military']['tech_level'] * 0.05)
        employment_rate = self.civ_manager.get_employment_rate(user_id) / 100
        employment_factor = 1 + employment_rate * config.ECONOMY["immigration_employment_coeff"]
        territory_factor = get_territory_modifier(civ['territory']['land_size'])
        base = random.randint(config.ECONOMY["immigration_citizen_min"],
                              config.ECONOMY["immigration_citizen_max"])
        gained = int(base * employment_factor * territory_factor * tech_multiplier)
        gained = min(gained, config.CAPS["immigration"] * tech_multiplier)
        self.civ_manager.update_population(user_id, {"citizens": gained})

        happiness_loss = random.randint(config.ECONOMY["immigration_happiness_loss_min"],
                                        config.ECONOMY["immigration_happiness_loss_max"])
        self.civ_manager.update_population(user_id, {"happiness": -happiness_loss})

        riot_triggered = False
        if random.random() < config.ECONOMY["immigration_riot_chance"]:
            riot_triggered = True
            extra_h = random.randint(config.ECONOMY["immigration_riot_happiness_loss_min"],
                                     config.ECONOMY["immigration_riot_happiness_loss_max"])
            s_loss = random.randint(config.ECONOMY["immigration_riot_soldier_loss_min"],
                                    config.ECONOMY["immigration_riot_soldier_loss_max"])
            self.civ_manager.update_population(user_id, {"happiness": -extra_h})
            self.civ_manager.update_military(user_id, {"soldiers": -s_loss})
            self.civ_manager.apply_faction_effects(user_id, "immigration_riot")
            self.db.log_event(user_id, "immigration_riot", "Immigration Riot!",
                              f"Anti-immigration protests turned violent! Lost {s_loss} soldiers and {extra_h} happiness.")

        self.civ_manager.apply_faction_effects(user_id, "immigration")
        self.db.log_event(user_id, "immigration", "Immigration Opened",
                          f"Gained {gained} citizens, lost {happiness_loss} happiness. Riot: {riot_triggered}")

        embed = create_embed("🛂 Immigration Open!",
                             f"{gained} new citizens arrived!",
                             guilded.Color.blue())
        embed.add_field(name="👥 Citizens Gained", value=f"+{format_number(gained)}", inline=True)
        embed.add_field(name="😡 Happiness", value=f"-{happiness_loss}", inline=True)
        if riot_triggered:
            embed.add_field(name="💥 PROTEST RIOT!",
                            value=f"Lost {s_loss} soldiers and {extra_h} more happiness!",
                            inline=False)
            embed.color = guilded.Color.red()
        await ctx.send(embed=embed)

    @commands.command(name='buycard')
    async def buy_card(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if not self.civ_manager.can_afford(user_id, {"gold": 500}):
            await ctx.send("❌ Need 500 gold!")
            return
        self.civ_manager.spend_resources(user_id, {"gold": 500})
        card = random.choice(config.CARD_POOL)
        purchased = civ.get('purchased_cards', [])
        purchased.append(card)
        self.db.update_civilization(user_id, {"purchased_cards": purchased})
        embed = create_embed("🎴 Card Purchased!",
                             f"You received:\n**{card['name']}** – {card['description']}",
                             guilded.Color.gold())
        embed.add_field(name="How to use", value="`.cards use \"Card Name\"`", inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(EconomyCommands(bot))
