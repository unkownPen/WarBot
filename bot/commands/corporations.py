import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

import discord as guilded
from discord.ext import commands

from bot.utils import format_number, create_embed
from bot import config

logger = logging.getLogger(__name__)


# =====================================================================
# DOPAMINE HELPERS
# =====================================================================
BANNER = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
FIRE = "🔥"

def _hype_color(tier: str = "good") -> int:
    return config.DOPAMINE_COLORS.get(tier, 0x6366f1)

def _hype_title(text: str, tier: str = "good") -> str:
    emoji_map = {
        "common": "🟢", "good": "🔵", "great": "🟣", "epic": "🟠", "legend": "🟡",
    }
    return f"{emoji_map.get(tier, '✨')} **{text}** {emoji_map.get(tier, '✨')}"


# =====================================================================
# DAILY VIEWS
# =====================================================================
class DailyMathView(guilded.ui.View):
    """3 rapid math questions, 30s total."""

    def __init__(self, cog, user_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.questions: List[Tuple[str, int, List[int]]] = []
        self.current_idx = 0
        self.correct_count = 0
        self.done = False
        self._build_questions()
        self._rebuild_buttons()

    def _build_questions(self):
        for _ in range(3):
            q = self._gen_q()
            self.questions.append(q)

    def _gen_q(self):
        kind = random.choice(["add", "sub", "mul"])
        if kind == "add":
            a, b = random.randint(20, 99), random.randint(10, 80)
            ans = a + b
            return f"{a} + {b}", ans, self._choices(ans)
        elif kind == "sub":
            a, b = random.randint(60, 150), random.randint(10, 50)
            ans = a - b
            return f"{a} − {b}", ans, self._choices(ans)
        else:
            a, b = random.randint(4, 12), random.randint(3, 9)
            ans = a * b
            return f"{a} × {b}", ans, self._choices(ans)

    def _choices(self, correct):
        s = {correct}
        while len(s) < 4:
            offset = random.randint(-15, 15)
            if offset == 0:
                continue
            cand = correct + offset
            if cand > 0:
                s.add(cand)
        out = list(s)
        random.shuffle(out)
        return out

    def _rebuild_buttons(self):
        self.clear_items()
        if self.current_idx >= len(self.questions):
            return
        _, correct, choices = self.questions[self.current_idx]
        for c in choices:
            btn = guilded.ui.Button(label=str(c), style=guilded.ButtonStyle.primary)
            btn.callback = self._make_cb(c, correct)
            self.add_item(btn)

    def _make_cb(self, chosen, correct):
        async def callback(interaction: guilded.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your daily.", ephemeral=True)
                return
            if self.done:
                await interaction.response.send_message("Already finished.", ephemeral=True)
                return
            if chosen == correct:
                self.correct_count += 1
            self.current_idx += 1
            if self.current_idx >= len(self.questions):
                self.done = True
                self.stop()
                await interaction.response.edit_message(
                    content=f"**Finished!** Correct: **{self.correct_count}/3**",
                    view=None,
                )
                return
            self._rebuild_buttons()
            q, _, _ = self.questions[self.current_idx]
            await interaction.response.edit_message(
                content=f"**Q{self.current_idx + 1}/3:** What is **{q}**?",
                view=self,
            )
        return callback


class DailyDecisionView(guilded.ui.View):
    def __init__(self, cog, user_id: int, choices: List[Dict[str, Any]], timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.choice_result: Optional[Dict[str, Any]] = None
        for c in choices:
            btn = guilded.ui.Button(
                label=c["label"],
                emoji=c.get("emoji"),
                style=guilded.ButtonStyle.primary,
            )
            btn.callback = self._make_cb(c)
            self.add_item(btn)

    def _make_cb(self, choice):
        async def callback(interaction: guilded.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your daily.", ephemeral=True)
                return
            if self.choice_result is not None:
                await interaction.response.send_message("Already chosen.", ephemeral=True)
                return
            self.choice_result = choice
            for item in self.children:
                item.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                pass
            self.stop()
        return callback


class DailyGambleView(guilded.ui.View):
    def __init__(self, cog, user_id: int, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.rolled = False
        spin = guilded.ui.Button(label="🎲 SPIN", style=guilded.ButtonStyle.success)
        spin.callback = self._spin
        self.add_item(spin)
        skip = guilded.ui.Button(label="😴 Skip", style=guilded.ButtonStyle.secondary)
        skip.callback = self._skip
        self.add_item(skip)

    async def _spin(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your daily.", ephemeral=True)
            return
        if self.rolled:
            await interaction.response.send_message("Already rolled.", ephemeral=True)
            return
        self.rolled = True
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        self.stop()

    async def _skip(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your daily.", ephemeral=True)
            return
        self.rolled = False
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        self.stop()


# =====================================================================
# MAIN COG
# =====================================================================
class CorporationsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self._tick_task = None

    async def cog_load(self):
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def cog_unload(self):
        if self._tick_task:
            self._tick_task.cancel()

    # =================================================================
    # CORP HOURLY TICK
    # =================================================================
    async def _tick_loop(self):
        await self.bot.wait_until_ready()
        logger.info("Corporation tick loop started")
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(3600)
                await self._run_tick()
            except asyncio.CancelledError:
                logger.info("Corporation tick loop cancelled")
                break
            except Exception as e:
                logger.error(f"Corporation tick error: {e}", exc_info=True)
                await asyncio.sleep(300)

    async def _run_tick(self):
        corps = self.db.get_all_corporations()
        logger.info(f"Corporation tick: processing {len(corps)} corps")
        for corp in corps:
            try:
                self._tick_one_corp(corp)
            except Exception as e:
                logger.error(f"Corp tick failed for {corp.get('id')}: {e}")

    def _compute_research_bonuses(self, corp):
        rd = float(corp.get("r_and_d", 0))
        out_mult = 1.0
        eff_floor = 0.0
        contract_slots = 0
        rep_rate = 0.0
        for thresh, tier in sorted(config.CORP_RESEARCH_TIERS.items()):
            if rd >= thresh:
                b = tier.get("bonus", {})
                if "output_mult" in b:
                    out_mult = max(out_mult, b["output_mult"])
                if "efficiency_floor" in b:
                    eff_floor = max(eff_floor, b["efficiency_floor"])
                if "contract_slots" in b:
                    contract_slots += b["contract_slots"]
                if "rep_rate" in b:
                    rep_rate += b["rep_rate"]
        return {
            "output_mult": out_mult,
            "efficiency_floor": eff_floor,
            "contract_slots": contract_slots,
            "rep_rate": rep_rate,
        }

    def _tick_one_corp(self, corp):
        owner_id = corp["owner_id"]
        industry = corp.get("industry", "agriculture")
        ind = config.INDUSTRIES.get(industry)
        if not ind:
            return
        civ = self.civ_manager.get_civilization(owner_id)
        if not civ:
            return

        employees = int(corp.get("employees", 0))
        level = int(corp.get("level", 1))

        if employees <= 0:
            new_eff = max(0, corp.get("efficiency", 100) - 2)
            new_mor = max(0, corp.get("morale", 100) - 3)
            self._push_event(corp, {"type": "info", "name": "Idle",
                                    "desc": "No employees assigned — decaying."})
            self.db.update_corporation(corp["id"], {
                "efficiency": new_eff,
                "morale": new_mor,
            })
            return

        event = None
        event_effects = {}
        if random.random() < 0.15:
            event = random.choice(config.BUSINESS_EVENTS)
            event_effects = event.get("effect", {})

        research = self._compute_research_bonuses(corp)

        eff = float(corp.get("efficiency", 100))
        morale = float(corp.get("morale", 100))
        assets = float(corp.get("assets", 0))
        rd = float(corp.get("r_and_d", 0))

        eff = max(0, eff - 1)
        morale = max(0, morale - 0.5)

        if "efficiency" in event_effects:
            eff = max(0, min(100, eff + event_effects["efficiency"]))
        if "morale" in event_effects:
            morale = max(0, min(100, morale + event_effects["morale"]))
        if "r_and_d" in event_effects:
            rd = max(0, min(100, rd + event_effects["r_and_d"]))

        eff = max(eff, research["efficiency_floor"])

        emp_factor = min(1.0, employees / 50.0)
        revenue_mult = float(event_effects.get("revenue_mult", 1.0))
        level_mult = 1 + (level - 1) * config.CORP_LEVEL_REQUIREMENTS["output_bonus_per_level"]
        branches = corp.get("branches") or []
        branch_mult = 1 + 0.15 * len(branches)

        production_mult = (
            (eff / 100.0)
            * (morale / 100.0)
            * (1 + assets / 100.0)
            * (1 + rd / 200.0)
            * emp_factor
            * revenue_mult
            * level_mult
            * branch_mult
            * research["output_mult"]
        )

        skip_production = bool(event_effects.get("skip_production"))
        if not skip_production:
            can_produce = True
            for res, amt in ind.get("consumes", {}).items():
                if civ["resources"].get(res, 0) < amt:
                    can_produce = False
                    break
            if can_produce:
                for res, amt in ind.get("consumes", {}).items():
                    self.civ_manager.update_resources(owner_id, {res: -amt})
                for res, amt in ind.get("produces", {}).items():
                    produced = int(amt * production_mult)
                    if produced <= 0:
                        continue
                    if res == "soldiers":
                        self.civ_manager.update_military(owner_id, {"soldiers": produced})
                    else:
                        self.civ_manager.update_resources(owner_id, {res: produced})
            else:
                eff = max(0, eff - 5)

        wage_per_emp = ind.get("base_wage", 2)
        wages = int(employees * wage_per_emp * (1 + (level - 1) * 0.15))
        reserve = int(corp.get("reserve", 0))

        if reserve >= wages:
            new_reserve = reserve - wages
            new_debt = int(corp.get("debt", 0))
        else:
            owed = wages - reserve
            if civ["resources"].get("gold", 0) >= owed:
                self.civ_manager.update_resources(owner_id, {"gold": -owed})
                new_reserve = 0
                new_debt = int(corp.get("debt", 0))
            else:
                new_reserve = 0
                new_debt = int(corp.get("debt", 0)) + owed
                morale = max(0, morale - 15)

        bonus = int(event_effects.get("gold_bonus", 0))
        if bonus:
            if bonus > 0:
                new_reserve += bonus
            else:
                cost = -bonus
                if new_reserve >= cost:
                    new_reserve -= cost
                else:
                    new_debt += (cost - new_reserve)
                    new_reserve = 0

        rep = float(corp.get("reputation", 50))
        rep += research["rep_rate"]
        if rep > 50:
            rep = max(50, rep - 0.5)
        elif rep < 50:
            rep = min(50, rep + 0.5)
        rep = max(0, min(100, rep))

        contracts = list(corp.get("contracts") or [])
        now = datetime.utcnow()
        still_valid = []
        for c in contracts:
            exp = c.get("expires_at")
            try:
                if exp and datetime.fromisoformat(exp) > now:
                    still_valid.append(c)
                else:
                    self._push_event(corp, {"type": "info",
                                            "name": "Contract Expired",
                                            "desc": c.get("name", "Contract")})
            except Exception:
                still_valid.append(c)

        update = {
            "efficiency": round(eff, 2),
            "morale": round(morale, 2),
            "reserve": new_reserve,
            "debt": new_debt,
            "reputation": round(rep, 2),
            "r_and_d": round(rd, 2),
            "contracts": still_valid,
        }
        if event:
            update["last_event"] = {"type": event["type"], "name": event["name"], "desc": event["desc"]}
            self._push_event(corp, {"type": event["type"], "name": event["name"], "desc": event["desc"]})

        self.db.update_corporation(corp["id"], update)

    def _push_event(self, corp, evt):
        history = list(corp.get("event_history") or [])
        entry = dict(evt)
        entry["at"] = datetime.utcnow().isoformat()
        history.insert(0, entry)
        history = history[:5]
        try:
            self.db.update_corporation(corp["id"], {"event_history": history})
        except Exception as e:
            logger.error(f"_push_event failed for {corp.get('id')}: {e}")

    # =================================================================
    # CORP COMMANDS
    # =================================================================
    @commands.group(name="corp", aliases=["biz"], invoke_without_command=True)
    async def corp(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        corps = self.db.get_user_corporations(user_id)
        embed = self._main_menu_embed(civ, corps)
        view = CorpMainMenuView(self, ctx.author.id, corps)
        await ctx.send(embed=embed, view=view)

    def _main_menu_embed(self, civ, corps):
        embed = create_embed(
            "🏢 Your Corporations",
            f"Owner: **{civ['name']}**\n"
            f"Slots: **{len(corps)}/{config.CORP_LIMITS['max_per_user']}**",
            guilded.Color.dark_teal(),
        )
        if not corps:
            embed.add_field(
                name="No corporations yet",
                value="Use `.corp build <industry> <name>` to found one.",
                inline=False,
            )
        else:
            for i, c in enumerate(corps, 1):
                ind = config.INDUSTRIES.get(c.get("industry"), {})
                reserve = int(c.get("reserve", 0))
                debt = int(c.get("debt", 0))
                debt_str = f" · 🔻 debt {format_number(debt)}" if debt > 0 else ""
                branches = len(c.get("branches") or [])
                contracts = len(c.get("contracts") or [])
                embed.add_field(
                    name=f"{ind.get('emoji','🏢')} {c['name']} (Lv {c.get('level',1)})",
                    value=(f"{ind.get('name','?')}\n"
                           f"Reserve: 🪙 {format_number(reserve)}{debt_str}\n"
                           f"Eff {int(c.get('efficiency',100))}% | Morale {int(c.get('morale',100))}% | "
                           f"Emp {c.get('employees',0)}\n"
                           f"Branches: {branches} | Contracts: {contracts}"),
                    inline=False,
                )
        return embed

    @corp.command(name="build")
    async def corp_build(self, ctx, industry: str = None, *, name: str = None):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return

        if not industry or not name:
            embed = create_embed(
                "🏢 Build a Corporation",
                "Usage: `.corp build <industry> <name>`",
                guilded.Color.dark_teal(),
            )
            for key, ind in config.INDUSTRIES.items():
                tech = civ['military']['tech_level']
                lock = " 🔒" if tech < ind['tech_required'] else ""
                embed.add_field(
                    name=f"{ind['emoji']} {ind['name']}{lock}",
                    value=(f"Startup: 🪙 {format_number(ind['startup_cost'])}\n"
                           f"Tech required: {ind['tech_required']}\n"
                           f"Produces: {', '.join(f'{v} {k}' for k, v in ind['produces'].items())}\n"
                           f"*{ind['desc']}*"),
                    inline=False,
                )
            await ctx.send(embed=embed)
            return

        industry = industry.lower()
        if industry not in config.INDUSTRIES:
            await ctx.send(f"❌ Unknown industry. Options: {', '.join(config.INDUSTRIES.keys())}")
            return
        ind = config.INDUSTRIES[industry]

        name = name.strip()
        lim = config.CORP_LIMITS
        if not (lim["min_name_length"] <= len(name) <= lim["max_name_length"]):
            await ctx.send(f"❌ Name must be {lim['min_name_length']}–{lim['max_name_length']} chars.")
            return
        if self.db.count_user_corporations(user_id) >= lim["max_per_user"]:
            await ctx.send(f"❌ You already have {lim['max_per_user']} corporations.")
            return
        if civ['military']['tech_level'] < ind['tech_required']:
            await ctx.send(f"❌ Requires Tech Level {ind['tech_required']}.")
            return
        owned = self.db.get_player_territories(user_id)
        if not owned:
            await ctx.send("❌ You need at least one province.")
            return
        if ind.get("requires_provinces") and len(owned) < ind["requires_provinces"]:
            await ctx.send(f"❌ Requires {ind['requires_provinces']}+ provinces.")
            return
        if not self.civ_manager.can_afford(user_id, {"gold": ind['startup_cost']}):
            await ctx.send(f"❌ Need 🪙 {format_number(ind['startup_cost'])} gold.")
            return

        self.civ_manager.spend_resources(user_id, {"gold": ind['startup_cost']})
        location = owned[0]
        corp_id = self.db.create_corporation(user_id, name, industry, location)
        if not corp_id:
            self.civ_manager.update_resources(user_id, {"gold": ind['startup_cost']})
            await ctx.send("❌ Failed to create corporation.")
            return

        await ctx.send(embed=create_embed(
            f"{ind['emoji']} {name} Founded",
            f"**{ind['name']}** corporation established in **{location}**.\n\n"
            f"Manage it with `.corp`.",
            guilded.Color.green(),
        ))

    @corp.command(name="leaderboard", aliases=["lb", "top"])
    async def corp_leaderboard(self, ctx):
        corps = self.db.get_all_corporations()
        if not corps:
            await ctx.send("📭 No corporations exist yet.")
            return
        def score(c):
            return int(c.get("reserve", 0)) + int(c.get("level", 1)) * 50_000
        top = sorted(corps, key=score, reverse=True)[:10]

        embed = create_embed("🏆 Top Corporations", "Ranked by value (reserve + level bonus)", guilded.Color.gold())
        for i, c in enumerate(top, 1):
            ind = config.INDUSTRIES.get(c.get("industry"), {})
            owner = self.civ_manager.get_civilization(c.get("owner_id"))
            owner_name = owner["name"] if owner else "?"
            embed.add_field(
                name=f"#{i} {ind.get('emoji','🏢')} {c['name']}",
                value=(f"Owner: **{owner_name}**\n"
                       f"Level {c.get('level',1)} · Reserve 🪙 {format_number(int(c.get('reserve',0)))}"),
                inline=False,
            )
        await ctx.send(embed=embed)

    @corp.command(name="takeover")
    async def corp_takeover(self, ctx, *, target_name: str = None):
        user_id = str(ctx.author.id)
        attacker_civ = self.civ_manager.get_civilization(user_id)
        if not attacker_civ:
            await ctx.send("❌ Need a civilization first.")
            return
        if not target_name:
            await ctx.send("Usage: `.corp takeover <corp name>`")
            return

        target_name_lc = target_name.strip().lower()
        all_corps = self.db.get_all_corporations()
        target = None
        for c in all_corps:
            if str(c.get("owner_id")) == user_id:
                continue
            if c["name"].lower() == target_name_lc:
                target = c
                break
        if not target:
            for c in all_corps:
                if str(c.get("owner_id")) == user_id:
                    continue
                if target_name_lc in c["name"].lower():
                    target = c
                    break
        if not target:
            await ctx.send(f"❌ No corp matching `{target_name}`.")
            return

        own_corps = self.db.get_user_corporations(user_id)
        attacker_rep = 50.0
        if own_corps:
            attacker_rep = max(float(c.get("reputation", 50)) for c in own_corps)
        target_rep = float(target.get("reputation", 50))

        if attacker_rep < config.CORP_TAKEOVER["min_attacker_rep"]:
            await ctx.send(f"❌ Your reputation is too low (**{int(attacker_rep)}**). "
                           f"Minimum {config.CORP_TAKEOVER['min_attacker_rep']} required.")
            return

        level = int(target.get("level", 1))
        cost = int(target.get("reserve", 0)) + level * config.CORP_TAKEOVER["cost_per_level"]
        if not self.civ_manager.can_afford(user_id, {"gold": cost}):
            await ctx.send(f"❌ Takeover cost is 🪙 {format_number(cost)} — you can't afford it.")
            return

        ratio = attacker_rep / max(1.0, attacker_rep + target_rep)
        success = ratio >= config.CORP_TAKEOVER["success_rep_ratio"]

        view = TakeoverView(self, ctx.author.id, target, cost, success)
        await ctx.send(embed=view._make_embed(), view=view)

    # =================================================================
    # DAILY
    # =================================================================
    @commands.command(name="daily", aliases=["d"])
    async def daily(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first! Use `.start <name>`")
            return

        state = self.db.get_daily_state(user_id) or {}

        # --- Cooldown check ---
        last = state.get("last_completed_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                ready_at = last_dt + timedelta(hours=config.DAILY["cooldown_hours"])
                if datetime.utcnow() < ready_at:
                    remaining = ready_at - datetime.utcnow()
                    hrs = int(remaining.total_seconds() // 3600)
                    mins = int((remaining.total_seconds() % 3600) // 60)
                    streak = state.get("streak", 0)
                    embed = guilded.Embed(
                        title=_hype_title("DAILY COOLDOWN", "good"),
                        description=(
                            f"{BANNER}\n"
                            f"🔥 Streak: **{streak}** days\n"
                            f"⏰ Next daily in: **{hrs}h {mins}m**\n"
                            f"{BANNER}\n\n"
                            f"*Come back tomorrow, President.*"
                        ),
                        color=_hype_color("good"),
                    )
                    await ctx.send(embed=embed)
                    return
            except Exception:
                pass

        # --- Roll a challenge ---
        challenge = random.choice(["math", "decision", "gamble"])
        streak = int(state.get("streak", 0))
        next_streak = streak + 1
        milestone = config.DAILY["milestones"].get(next_streak)

        # Preview the challenge
        if challenge == "math":
            embed = guilded.Embed(
                title=_hype_title("DAILY: MATH SPRINT 🧮", "great"),
                description=(
                    f"{BANNER}\n"
                    f"🔥 Streak: **{streak}** → **{next_streak}**\n"
                    f"🎯 **3 questions** · **30 seconds**\n"
                    f"⚡ *Answer fast, answer right.*\n"
                    f"{BANNER}"
                ),
                color=_hype_color("great"),
            )
            await ctx.send(embed=embed)
            view = DailyMathView(self, ctx.author.id, timeout=30.0)
            q, _, _ = view.questions[0]
            msg = await ctx.send(f"**Q1/3:** What is **{q}**?", view=view)
            await view.wait()
            # Grade
            passed = view.correct_count >= 2
            await self._complete_daily(
                ctx, user_id, civ, passed,
                detail=f"Correct: **{view.correct_count}/3**",
            )
            return

        if challenge == "decision":
            scenario, choices = self._roll_decision()
            embed = guilded.Embed(
                title=_hype_title("DAILY: DECISION 🎯", "great"),
                description=(
                    f"{BANNER}\n"
                    f"🔥 Streak: **{streak}** → **{next_streak}**\n"
                    f"{BANNER}\n\n"
                    f"**{scenario}**\n\n"
                    f"*There's no wrong answer — only consequences.*"
                ),
                color=_hype_color("great"),
            )
            view = DailyDecisionView(self, ctx.author.id, choices)
            await ctx.send(embed=embed, view=view)
            await view.wait()
            if view.choice_result is None:
                await ctx.send("⏰ Timed out. Try again next time.")
                return
            await self._apply_decision(user_id, view.choice_result)
            await self._complete_daily(
                ctx, user_id, civ, True,
                detail=f"Chose: **{view.choice_result['label']}**",
            )
            return

        # gamble
        embed = guilded.Embed(
            title=_hype_title("DAILY: HIGH STAKES GAMBLE 🎲", "epic"),
            description=(
                f"{BANNER}\n"
                f"🔥 Streak: **{streak}** → **{next_streak}**\n"
                f"{BANNER}\n\n"
                f"🎰 **Free spin.** Win **1k–10k gold** or nothing.\n"
                f"💸 *No cost to you either way.*"
            ),
            color=_hype_color("epic"),
        )
        view = DailyGambleView(self, ctx.author.id)
        await ctx.send(embed=embed, view=view)
        await view.wait()

        win_amount = 0
        if view.rolled:
            if random.random() < (1 - config.DAILY["gamble_lose_chance"]):
                win_amount = random.randint(config.DAILY["gamble_min"], config.DAILY["gamble_max"])
                self.civ_manager.update_resources(user_id, {"gold": win_amount})

        await self._complete_daily(
            ctx, user_id, civ, True,
            detail=f"🎲 Won: **{format_number(win_amount)} gold**" if win_amount else "💀 Nothing this time.",
            extra_gold=win_amount,
        )

    # ---------------------------------------------------------------
    def _roll_decision(self):
        pool = [
            ("Your merchants offer a deal.", [
                {"label": "Take 5,000 gold", "emoji": "💰", "effect": {"gold": 5000}},
                {"label": "+3 Merchant faction", "emoji": "🪙", "effect": {"faction": ("merchant", 3)}},
            ]),
            ("Your military demands more recruits.", [
                {"label": "Give 20 soldiers", "emoji": "⚔️", "effect": {"soldiers": 20}},
                {"label": "Refuse", "emoji": "🚫", "effect": {"faction": ("military", -3), "happiness": 5}},
            ]),
            ("A neighboring nation sends a gift.", [
                {"label": "Accept gold", "emoji": "🪙", "effect": {"gold": 3000}},
                {"label": "Accept food", "emoji": "🌾", "effect": {"food": 2000}},
                {"label": "Refuse politely", "emoji": "🤝", "effect": {"faction": ("merchant", 2)}},
            ]),
            ("Your citizens ask for a festival.", [
                {"label": "Fund it (−2,000g)", "emoji": "🎉", "effect": {"gold": -2000, "happiness": 10}},
                {"label": "Deny it", "emoji": "🚫", "effect": {"happiness": -5}},
            ]),
        ]
        return random.choice(pool)

    async def _apply_decision(self, user_id: str, choice: Dict[str, Any]):
        try:
            eff = choice.get("effect", {})
            for k, v in eff.items():
                if k == "gold":
                    self.civ_manager.update_resources(user_id, {"gold": v})
                elif k == "food":
                    self.civ_manager.update_resources(user_id, {"food": v})
                elif k == "soldiers":
                    self.civ_manager.update_military(user_id, {"soldiers": v})
                elif k == "happiness":
                    self.civ_manager.update_population(user_id, {"happiness": v})
                elif k == "faction":
                    fname, delta = v
                    self.civ_manager.update_faction(user_id, fname, delta)
        except Exception as e:
            logger.error(f"decision apply failed: {e}")

    # ---------------------------------------------------------------
    def _streak_reward(self, streak: int) -> Dict[str, Any]:
        base_gold = config.DAILY["base_gold"]
        base_food = config.DAILY["base_food"]
        mult = 1.0
        bonus_gold = 0
        bonus_item = None
        milestone_label = None

        # Find the highest milestone ≤ streak
        for day in sorted(config.DAILY["milestones"].keys()):
            if streak >= day:
                m = config.DAILY["milestones"][day]
                mult = m["mult"]
                milestone_label = m.get("label")
                # Exact-hit bonus only lands on the exact day
                if streak == day:
                    bonus_gold = m.get("gold", 0)
                    bonus_item = m.get("item")

        mult = min(mult, config.DAILY["max_multiplier"])
        gold = int(base_gold * mult) + bonus_gold
        food = int(base_food * mult)
        return {
            "gold": gold,
            "food": food,
            "mult": mult,
            "bonus_gold": bonus_gold,
            "bonus_item": bonus_item,
            "milestone_label": milestone_label,
        }

    async def _complete_daily(self, ctx, user_id: str, civ: Dict[str, Any],
                              passed: bool, detail: str = "", extra_gold: int = 0):
        state = self.db.get_daily_state(user_id) or {}
        streak = int(state.get("streak", 0))
        best = int(state.get("best_streak", 0))
        total = int(state.get("total_completed", 0))

        if not passed:
            # Fail → reset streak
            state["streak"] = 0
            state["last_completed_at"] = datetime.utcnow().isoformat()
            self.db.save_daily_state(user_id, state)
            embed = guilded.Embed(
                title=_hype_title("DAILY FAILED 💀", "common"),
                description=(
                    f"{BANNER}\n"
                    f"{detail}\n\n"
                    f"🔥 Streak reset: **{streak} → 0**\n"
                    f"*You'll get 'em tomorrow, President.*"
                ),
                color=_hype_color("common"),
            )
            await ctx.send(embed=embed)
            return

        new_streak = streak + 1
        best = max(best, new_streak)
        total += 1

        reward = self._streak_reward(new_streak)
        total_gold = reward["gold"] + extra_gold
        total_food = reward["food"]

        self.civ_manager.update_resources(user_id, {"gold": total_gold, "food": total_food})

        item_line = ""
        if reward["bonus_item"]:
            pool = config.DAILY["item_pools"].get(reward["bonus_item"], [])
            if pool:
                chosen_item = random.choice(pool)
                self.civ_manager.add_hyper_item(user_id, chosen_item)
                item_line = f"\n🎁 **BONUS ITEM:** *{chosen_item}*"

        state["streak"] = new_streak
        state["best_streak"] = best
        state["total_completed"] = total
        state["last_completed_at"] = datetime.utcnow().isoformat()
        self.db.save_daily_state(user_id, state)

        # Pick a dopamine color
        if new_streak >= 100:
            tier = "legend"
        elif new_streak >= 30:
            tier = "epic"
        elif new_streak >= 7:
            tier = "great"
        elif new_streak >= 3:
            tier = "good"
        else:
            tier = "common"

        milestone_line = ""
        if reward["milestone_label"]:
            milestone_line = f"\n\n🎊 **{reward['milestone_label']}**"

        embed = guilded.Embed(
            title=_hype_title(f"{FIRE} DAILY COMPLETE {FIRE}", tier),
            description=(
                f"{BANNER}\n"
                f"🔥 **Streak:** `{streak}` → **`{new_streak}`**  "
                f"*(best: {best})*\n"
                f"⚡ **Multiplier:** ×**{reward['mult']:.2f}**\n"
                f"{BANNER}\n"
                f"💰 **Gold:** +{format_number(total_gold)}\n"
                f"🌾 **Food:** +{format_number(total_food)}"
                f"{item_line}"
                f"{milestone_line}\n\n"
                f"*{detail}*"
            ),
            color=_hype_color(tier),
        )
        embed.set_footer(text=f"Total completed: {total} days")
        await ctx.send(embed=embed)

    @commands.command(name="streak", aliases=["mystreak"])
    async def streak_info(self, ctx):
        user_id = str(ctx.author.id)
        state = self.db.get_daily_state(user_id) or {}
        streak = int(state.get("streak", 0))
        best = int(state.get("best_streak", 0))
        total = int(state.get("total_completed", 0))
        last = state.get("last_completed_at")

        embed = guilded.Embed(
            title=_hype_title("YOUR STREAK", "great"),
            description=f"{BANNER}\n"
                        f"🔥 **Current:** `{streak}` days\n"
                        f"🏆 **Best:** `{best}` days\n"
                        f"📊 **Total:** `{total}` days\n"
                        f"{BANNER}",
            color=_hype_color("great"),
        )

        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                ready_at = last_dt + timedelta(hours=config.DAILY["cooldown_hours"])
                if datetime.utcnow() < ready_at:
                    remaining = ready_at - datetime.utcnow()
                    hrs = int(remaining.total_seconds() // 3600)
                    mins = int((remaining.total_seconds() % 3600) // 60)
                    embed.add_field(
                        name="⏰ Next daily",
                        value=f"**{hrs}h {mins}m**",
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name="✅ Daily ready",
                        value="Use `.daily` to claim it!",
                        inline=False,
                    )
            except Exception:
                pass

        # Show next milestone
        next_ms = None
        for day in sorted(config.DAILY["milestones"].keys()):
            if day > streak:
                next_ms = day
                break
        if next_ms:
            m = config.DAILY["milestones"][next_ms]
            embed.add_field(
                name=f"🎯 Next milestone — Day {next_ms}",
                value=f"**{m.get('label','—')}** · ×{m['mult']:.2f} multiplier + "
                      f"🪙 {format_number(m['gold'])}"
                      + (f" + *{m['item']}* item" if m.get("item") else ""),
                inline=False,
            )

        await ctx.send(embed=embed)


# =====================================================================
# CORP VIEWS (unchanged from before)
# =====================================================================
class CorpMainMenuView(guilded.ui.View):
    def __init__(self, cog, user_id, corps, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id

        if not corps:
            build_btn = guilded.ui.Button(label="Build a Corporation", emoji="🏗️",
                                           style=guilded.ButtonStyle.success)
            build_btn.callback = self._build
            self.add_item(build_btn)
        else:
            for i, c in enumerate(corps[:5]):
                ind = config.INDUSTRIES.get(c.get("industry"), {})
                btn = guilded.ui.Button(
                    label=f"Manage {c['name'][:60]}",
                    emoji=ind.get("emoji", "🏢"),
                    style=guilded.ButtonStyle.primary,
                )
                btn.callback = self._make_manage(c["id"])
                self.add_item(btn)

            build_btn = guilded.ui.Button(label="Build New", emoji="🏗️",
                                           style=guilded.ButtonStyle.success)
            build_btn.callback = self._build
            self.add_item(build_btn)

    async def _build(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Use `.corp build <industry> <name>` to found a corporation.",
            ephemeral=True,
        )

    def _make_manage(self, corp_id):
        async def callback(interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your menu.", ephemeral=True)
                return
            corp = self.cog.db.get_corporation(corp_id)
            if not corp or str(corp.get("owner_id")) != str(self.user_id):
                await interaction.response.send_message("Corporation not found.", ephemeral=True)
                return
            view = CorpManageView(self.cog, self.user_id, corp_id)
            await interaction.response.send_message(
                embed=view._make_embed(corp),
                view=view,
                ephemeral=True,
            )
        return callback


class CorpManageView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        self._add("Staff", "👥", self._staff)
        self._add("Assets", "🏗️", lambda i: self._buy_stat(i, "assets"))
        self._add("Marketing", "📈", lambda i: self._buy_stat(i, "marketing"))
        self._add("R&D", "🔬", lambda i: self._buy_stat(i, "r_and_d"))
        self._add("Research", "🧬", self._research)
        self._add("Branches", "🌍", self._branches)
        self._add("Contracts", "📜", self._contracts)
        self._add("Log", "🗒️", self._log)
        self._add("Level Up", "⬆️", self._level)
        self._add("Finance", "💰", self._finance, style=guilded.ButtonStyle.success)
        self._add("Sell", "📤", self._sell, style=guilded.ButtonStyle.danger)

    def _add(self, label, emoji, cb, style=guilded.ButtonStyle.primary):
        btn = guilded.ui.Button(label=label, emoji=emoji, style=style)
        btn.callback = cb
        self.add_item(btn)

    def _make_embed(self, corp):
        ind = config.INDUSTRIES.get(corp.get("industry"), {})
        evt = corp.get("last_event")
        evt_line = ""
        if evt:
            icon = "🎉" if evt.get("type") == "positive" else ("⚠️" if evt.get("type") == "negative" else "ℹ️")
            evt_line = f"\n\n**Last event:** {icon} {evt['name']} — {evt['desc']}"
        branches = len(corp.get("branches") or [])
        contracts = len(corp.get("contracts") or [])
        embed = create_embed(
            f"{ind.get('emoji','🏢')} {corp['name']}",
            f"**{ind.get('name','?')}** · Lv {corp.get('level',1)} · {corp.get('location','?')}\n\n"
            f"💰 Reserve: **{format_number(int(corp.get('reserve',0)))}**"
            + (f"  ·  🔻 Debt: **{format_number(int(corp.get('debt',0)))}**" if corp.get('debt',0) else "")
            + f"\n👥 Employees: **{corp.get('employees',0)}**\n"
            f"🏗️ Assets: **{corp.get('assets',0)}**  ·  "
            f"📈 Marketing: **{corp.get('marketing',0)}**\n"
            f"🔬 R&D: **{corp.get('r_and_d',0)}**  ·  "
            f"⭐ Reputation: **{int(corp.get('reputation',50))}**\n"
            f"⚙️ Efficiency: **{int(corp.get('efficiency',100))}%**  ·  "
            f"😊 Morale: **{int(corp.get('morale',100))}%**\n"
            f"🌍 Branches: **{branches}**  ·  📜 Contracts: **{contracts}**"
            f"{evt_line}",
            guilded.Color.dark_teal(),
        )
        return embed

    async def _staff(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        view = StaffSubView(self.cog, self.user_id, self.corp_id)
        await interaction.response.send_message(
            embed=StaffSubView._make_embed(corp),
            view=view,
            ephemeral=True,
        )

    async def _buy_stat(self, interaction, stat_key):
        cost_map = {
            "assets": config.CORP_LIMITS["asset_cost_per_point"],
            "marketing": config.CORP_LIMITS["marketing_cost_per_point"],
            "r_and_d": config.CORP_LIMITS["rd_cost_per_point"],
        }
        labels = {"assets": "Assets 🏗️", "marketing": "Marketing 📈", "r_and_d": "R&D 🔬"}
        unit_cost = cost_map[stat_key]

        corp = self.cog.db.get_corporation(self.corp_id)
        level = int(corp.get("level", 1))
        base_cap_map = {
            "assets": config.CORP_LIMITS["max_assets"],
            "marketing": config.CORP_LIMITS["max_marketing"],
            "r_and_d": config.CORP_LIMITS["max_r_and_d"],
        }
        per_level = config.CORP_LEVEL_REQUIREMENTS[f"{stat_key}_per_level"]
        cap = base_cap_map[stat_key] + (level - 1) * per_level
        cap = min(cap, base_cap_map[stat_key] * 2)

        current = int(corp.get(stat_key, 0))
        if current >= cap:
            await interaction.response.send_message(f"❌ {labels[stat_key]} already at cap ({cap}).", ephemeral=True)
            return

        buy = min(5, cap - current)
        total_cost = unit_cost * buy

        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": total_cost}):
            await interaction.response.send_message(
                f"❌ Need 🪙 {format_number(total_cost)} gold to buy {buy} {stat_key}.", ephemeral=True
            )
            return

        self.cog.civ_manager.spend_resources(self.user_id, {"gold": total_cost})
        self.cog.db.update_corporation(self.corp_id, {stat_key: current + buy})

        corp = self.cog.db.get_corporation(self.corp_id)
        await interaction.response.send_message(
            f"✅ Bought **+{buy}** {labels[stat_key]} for 🪙 {format_number(total_cost)}.\n"
            f"Now at **{corp.get(stat_key,0)}/{cap}**.",
            ephemeral=True,
        )

    async def _research(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        rd = float(corp.get("r_and_d", 0))
        embed = create_embed(
            "🧬 Research Progress",
            f"Current R&D: **{int(rd)}**",
            guilded.Color.purple(),
        )
        for thresh, tier in sorted(config.CORP_RESEARCH_TIERS.items()):
            status = "✅" if rd >= thresh else "🔒"
            embed.add_field(
                name=f"{status} {tier['name']} (R&D {thresh})",
                value=tier["desc"],
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _branches(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        view = BranchesView(self.cog, self.user_id, self.corp_id)
        await interaction.response.send_message(
            embed=view._make_embed(corp),
            view=view,
            ephemeral=True,
        )

    async def _contracts(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        view = ContractsView(self.cog, self.user_id, self.corp_id)
        await interaction.response.send_message(
            embed=view._make_embed(corp),
            view=view,
            ephemeral=True,
        )

    async def _log(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        history = corp.get("event_history") or []
        embed = create_embed("🗒️ Event Log", f"Last {len(history)} events", guilded.Color.greyple())
        if not history:
            embed.description = "No events recorded yet."
        else:
            for e in history:
                icon = "🎉" if e.get("type") == "positive" else ("⚠️" if e.get("type") == "negative" else "ℹ️")
                embed.add_field(
                    name=f"{icon} {e.get('name','?')}",
                    value=f"{e.get('desc','')}\n*{e.get('at','')}*",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _level(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        view = LevelUpView(self.cog, self.user_id, self.corp_id)
        await interaction.response.send_message(
            embed=view._make_embed(corp),
            view=view,
            ephemeral=True,
        )

    async def _finance(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        reserve = int(corp.get("reserve", 0))
        if reserve < config.CORP_LIMITS["dividend_min"]:
            await interaction.response.send_message(
                f"❌ Reserve is {format_number(reserve)} gold — minimum to withdraw is "
                f"{format_number(config.CORP_LIMITS['dividend_min'])}.", ephemeral=True
            )
            return
        self.cog.db.update_corporation(self.corp_id, {"reserve": 0})
        self.cog.civ_manager.update_resources(self.user_id, {"gold": reserve})
        await interaction.response.send_message(
            f"💰 Withdrew **{format_number(reserve)} gold** from corp reserve.", ephemeral=True
        )

    async def _sell(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        level = int(corp.get("level", 1))
        reserve = int(corp.get("reserve", 0))
        sale_value = int(reserve * 0.7 + level * 50_000 * 0.7)
        view = ConfirmSellView(self.cog, self.user_id, self.corp_id, sale_value)
        await interaction.response.send_message(
            f"⚠️ Sell **{corp['name']}** for 🪙 {format_number(sale_value)} gold?",
            view=view,
            ephemeral=True,
        )


class StaffSubView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        for amt in (5, 25, 100):
            btn = guilded.ui.Button(label=f"Hire {amt}", style=guilded.ButtonStyle.success)
            btn.callback = self._make_hire(amt)
            self.add_item(btn)

        fire_btn = guilded.ui.Button(label="Fire All", style=guilded.ButtonStyle.danger)
        fire_btn.callback = self._fire_all
        self.add_item(fire_btn)

    @staticmethod
    def _make_embed(corp):
        return create_embed(
            f"👥 Staff — {corp['name']}",
            f"Employees: **{corp.get('employees',0)}** / {config.CORP_LIMITS['max_employees']}\n"
            f"Full productivity bonus at 50 employees.\n\n"
            f"*Hiring pulls from your civ's unemployed citizens.*",
            guilded.Color.blue(),
        )

    def _make_hire(self, amount):
        async def callback(interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not yours.", ephemeral=True)
                return
            corp = self.cog.db.get_corporation(self.corp_id)
            civ = self.cog.civ_manager.get_civilization(self.user_id)
            cap = config.CORP_LIMITS["max_employees"]
            current = int(corp.get("employees", 0))
            room = cap - current
            if room <= 0:
                await interaction.response.send_message("❌ Already at max employees.", ephemeral=True)
                return
            employed = civ['population'].get('employed', 0)
            citizens = civ['population']['citizens']
            available = max(0, citizens - employed)
            hire = min(amount, room, available)
            if hire <= 0:
                await interaction.response.send_message("❌ No unemployed citizens available.", ephemeral=True)
                return
            self.cog.db.update_corporation(self.corp_id, {"employees": current + hire})
            await interaction.response.send_message(
                f"✅ Hired **{hire}** employees (corp now has {current + hire}).",
                ephemeral=True,
            )
        return callback

    async def _fire_all(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        n = int(corp.get("employees", 0))
        self.cog.db.update_corporation(self.corp_id, {
            "employees": 0,
            "morale": max(0, int(corp.get("morale", 100)) - 20),
        })
        await interaction.response.send_message(
            f"🔻 Fired all **{n}** employees. Morale −20.", ephemeral=True
        )


class BranchesView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        add_btn = guilded.ui.Button(label="Add Branch", emoji="🌍", style=guilded.ButtonStyle.success)
        add_btn.callback = self._add_branch
        self.add_item(add_btn)

        close_btn = guilded.ui.Button(label="Close Branch", emoji="❌", style=guilded.ButtonStyle.danger)
        close_btn.callback = self._close_branch
        self.add_item(close_btn)

    def _make_embed(self, corp):
        branches = corp.get("branches") or []
        level = int(corp.get("level", 1))
        max_branches = config.CORP_LEVEL_REQUIREMENTS["branch_slots_per_level"][min(level-1, 9)]
        cost = level * config.CORP_BRANCH_COST_MULT
        return create_embed(
            "🌍 Branches",
            f"Level {level} · Slots: **{len(branches)}/{max_branches}**\n"
            f"Each branch adds **+15% production**.\n"
            f"Add branch cost: 🪙 **{format_number(cost)}**\n\n"
            + (f"**Branches:**\n" + "\n".join(f"• {b}" for b in branches) if branches else "*No branches yet.*"),
            guilded.Color.dark_green(),
        )

    async def _add_branch(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        civ = self.cog.civ_manager.get_civilization(self.user_id)
        level = int(corp.get("level", 1))
        branches = list(corp.get("branches") or [])
        max_branches = config.CORP_LEVEL_REQUIREMENTS["branch_slots_per_level"][min(level-1, 9)]
        if len(branches) >= max_branches:
            await interaction.response.send_message(
                f"❌ Max branches for level {level} is {max_branches}.", ephemeral=True
            )
            return
        cost = level * config.CORP_BRANCH_COST_MULT
        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": cost}):
            await interaction.response.send_message(f"❌ Need 🪙 {format_number(cost)}.", ephemeral=True)
            return

        owned = self.cog.db.get_player_territories(self.user_id)
        candidates = [p for p in owned if p not in branches and p != corp.get("location")]
        if not candidates:
            await interaction.response.send_message("❌ No other owned provinces available.", ephemeral=True)
            return
        chosen = random.choice(candidates)

        self.cog.civ_manager.spend_resources(self.user_id, {"gold": cost})
        branches.append(chosen)
        self.cog.db.update_corporation(self.corp_id, {"branches": branches})
        await interaction.response.send_message(
            f"🌍 Branch opened in **{chosen}** for 🪙 {format_number(cost)}.",
            ephemeral=True,
        )

    async def _close_branch(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        branches = list(corp.get("branches") or [])
        if not branches:
            await interaction.response.send_message("❌ No branches to close.", ephemeral=True)
            return
        removed = branches.pop()
        self.cog.db.update_corporation(self.corp_id, {"branches": branches})
        await interaction.response.send_message(
            f"❌ Closed branch in **{removed}**.", ephemeral=True
        )


class ContractsView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        accept_btn = guilded.ui.Button(label="Accept", emoji="✍️", style=guilded.ButtonStyle.success)
        accept_btn.callback = self._accept
        self.add_item(accept_btn)

        fulfill_btn = guilded.ui.Button(label="Fulfill First", emoji="✅", style=guilded.ButtonStyle.primary)
        fulfill_btn.callback = self._fulfill_first
        self.add_item(fulfill_btn)

        cancel_btn = guilded.ui.Button(label="Cancel First", emoji="❌", style=guilded.ButtonStyle.danger)
        cancel_btn.callback = self._cancel_first
        self.add_item(cancel_btn)

    def _make_embed(self, corp):
        active = corp.get("contracts") or []
        research = self.cog._compute_research_bonuses(corp)
        slots = config.CORP_CONTRACT_SLOT_BASE + research["contract_slots"]
        embed = create_embed(
            "📜 Contracts",
            f"Active: **{len(active)}/{slots}**",
            guilded.Color.gold(),
        )
        if not active:
            embed.add_field(name="No active contracts",
                            value="Click **Accept** to grab a random contract.",
                            inline=False)
        else:
            for i, c in enumerate(active, 1):
                exp = c.get("expires_at", "?")
                embed.add_field(
                    name=f"{i}. {c.get('name','Contract')}",
                    value=(f"Deliver: **{format_number(c.get('amount',0))}** {c.get('resource')}\n"
                           f"Reward: 🪙 {format_number(c.get('reward_gold',0))}  ·  "
                           f"Rep +{c.get('reward_rep',0)}\n"
                           f"Expires: {exp[:16]}"),
                    inline=False,
                )
        return embed

    async def _accept(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        active = list(corp.get("contracts") or [])
        research = self.cog._compute_research_bonuses(corp)
        slots = config.CORP_CONTRACT_SLOT_BASE + research["contract_slots"]
        if len(active) >= slots:
            await interaction.response.send_message(
                f"❌ All {slots} contract slots in use.", ephemeral=True
            )
            return

        template = random.choice(config.CORP_CONTRACT_POOL).copy()
        expires_at = (datetime.utcnow() + timedelta(hours=template["hours"])).isoformat()
        template["expires_at"] = expires_at
        active.append(template)
        self.cog.db.update_corporation(self.corp_id, {"contracts": active})
        await interaction.response.send_message(
            f"✍️ Accepted **{template['name']}** — deliver "
            f"{format_number(template['amount'])} {template['resource']} for "
            f"🪙 {format_number(template['reward_gold'])}.",
            ephemeral=True,
        )

    async def _fulfill_first(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        active = list(corp.get("contracts") or [])
        if not active:
            await interaction.response.send_message("❌ No active contracts.", ephemeral=True)
            return
        c = active[0]
        res = c["resource"]
        amt = int(c["amount"])

        if res == "soldiers":
            civ = self.cog.civ_manager.get_civilization(self.user_id)
            if civ["military"]["soldiers"] < amt:
                await interaction.response.send_message(
                    f"❌ You only have {civ['military']['soldiers']} soldiers.", ephemeral=True
                )
                return
            self.cog.civ_manager.update_military(self.user_id, {"soldiers": -amt})
        else:
            if not self.cog.civ_manager.can_afford(self.user_id, {res: amt}):
                await interaction.response.send_message(
                    f"❌ You don't have {format_number(amt)} {res}.", ephemeral=True
                )
                return
            self.cog.civ_manager.spend_resources(self.user_id, {res: amt})

        active.pop(0)
        reserve = int(corp.get("reserve", 0)) + int(c["reward_gold"])
        rep = min(100, float(corp.get("reputation", 50)) + int(c.get("reward_rep", 0)))
        self.cog.db.update_corporation(self.corp_id, {
            "contracts": active,
            "reserve": reserve,
            "reputation": rep,
        })
        self.cog._push_event(corp, {"type": "positive", "name": "Contract Fulfilled",
                                    "desc": f"{c['name']} — +🪙 {format_number(c['reward_gold'])}"})
        await interaction.response.send_message(
            f"✅ Fulfilled **{c['name']}** — earned 🪙 {format_number(c['reward_gold'])}.",
            ephemeral=True,
        )

    async def _cancel_first(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        active = list(corp.get("contracts") or [])
        if not active:
            await interaction.response.send_message("❌ No active contracts.", ephemeral=True)
            return
        removed = active.pop(0)
        rep = max(0, float(corp.get("reputation", 50)) - 3)
        self.cog.db.update_corporation(self.corp_id, {"contracts": active, "reputation": rep})
        await interaction.response.send_message(
            f"❌ Cancelled **{removed['name']}**. Reputation −3.", ephemeral=True
        )


class LevelUpView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        up_btn = guilded.ui.Button(label="Upgrade Level", emoji="⬆️", style=guilded.ButtonStyle.success)
        up_btn.callback = self._upgrade
        self.add_item(up_btn)

    def _make_embed(self, corp):
        level = int(corp.get("level", 1))
        max_level = config.CORP_LIMITS["max_level"]
        if level >= max_level:
            return create_embed("⬆️ Level", f"**Level {level}** — maximum reached.", guilded.Color.green())
        cost = int(config.CORP_LEVEL_REQUIREMENTS["base_cost"] * (level ** config.CORP_LEVEL_REQUIREMENTS["cost_growth"]))
        return create_embed(
            f"⬆️ Level {level}",
            f"Next level cost: 🪙 **{format_number(cost)}**\n"
            f"Level grants:\n"
            f"• +{config.CORP_LEVEL_REQUIREMENTS['output_bonus_per_level']*100:.0f}% output\n"
            f"• +{config.CORP_LEVEL_REQUIREMENTS['employees_per_level']} employees cap\n"
            f"• +{config.CORP_LEVEL_REQUIREMENTS['assets_per_level']} assets cap\n"
            f"• +{config.CORP_LEVEL_REQUIREMENTS['marketing_per_level']} marketing cap\n"
            f"• +{config.CORP_LEVEL_REQUIREMENTS['rd_per_level']} R&D cap",
            guilded.Color.dark_teal(),
        )

    async def _upgrade(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        level = int(corp.get("level", 1))
        if level >= config.CORP_LIMITS["max_level"]:
            await interaction.response.send_message("❌ Already at max level.", ephemeral=True)
            return
        cost = int(config.CORP_LEVEL_REQUIREMENTS["base_cost"] * (level ** config.CORP_LEVEL_REQUIREMENTS["cost_growth"]))
        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": cost}):
            await interaction.response.send_message(f"❌ Need 🪙 {format_number(cost)}.", ephemeral=True)
            return
        self.cog.civ_manager.spend_resources(self.user_id, {"gold": cost})
        self.cog.db.update_corporation(self.corp_id, {"level": level + 1})
        self.cog._push_event(corp, {"type": "positive", "name": "Level Up",
                                    "desc": f"Reached Level {level + 1}"})
        await interaction.response.send_message(f"⬆️ Level **{level} → {level+1}**!", ephemeral=True)


class ConfirmSellView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, sale_value, timeout=60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id
        self.sale_value = sale_value

        confirm = guilded.ui.Button(label="Confirm Sell", style=guilded.ButtonStyle.danger)
        confirm.callback = self._confirm
        self.add_item(confirm)

        cancel = guilded.ui.Button(label="Cancel", style=guilded.ButtonStyle.secondary)
        cancel.callback = self._cancel
        self.add_item(cancel)

    async def _confirm(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        if not corp or str(corp.get("owner_id")) != str(self.user_id):
            await interaction.response.send_message("Corp no longer exists.", ephemeral=True)
            return
        self.cog.civ_manager.update_resources(self.user_id, {"gold": self.sale_value})
        self.cog.db.delete_corporation(self.corp_id)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Sold **{corp['name']}** for 🪙 {format_number(self.sale_value)}.",
            view=self,
        )

    async def _cancel(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Cancelled.", view=self)


class TakeoverView(guilded.ui.View):
    def __init__(self, cog, user_id, target_corp, cost, guaranteed, timeout=120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.target = target_corp
        self.cost = cost
        self.guaranteed = guaranteed
        self.attempted = False

        confirm = guilded.ui.Button(label="Attempt Takeover", emoji="⚔️", style=guilded.ButtonStyle.danger)
        confirm.callback = self._attempt
        self.add_item(confirm)

        cancel = guilded.ui.Button(label="Cancel", style=guilded.ButtonStyle.secondary)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_embed(self):
        ind = config.INDUSTRIES.get(self.target.get("industry"), {})
        owner = self.cog.civ_manager.get_civilization(self.target.get("owner_id"))
        owner_name = owner["name"] if owner else "?"
        return create_embed(
            "⚔️ Hostile Takeover",
            f"Target: {ind.get('emoji','🏢')} **{self.target['name']}** (Lv {self.target.get('level',1)})\n"
            f"Owner: **{owner_name}**\n"
            f"Cost: 🪙 **{format_number(self.cost)}**\n"
            f"Success chance: **{'High' if self.guaranteed else 'Low'}**",
            guilded.Color.dark_red(),
        )

    async def _attempt(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        if self.attempted:
            await interaction.response.send_message("Already attempted.", ephemeral=True)
            return
        self.attempted = True

        target = self.cog.db.get_corporation(self.target["id"])
        if not target or str(target.get("owner_id")) == self.user_id:
            await interaction.response.send_message("Corp no longer available.", ephemeral=True)
            return

        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": self.cost}):
            await interaction.response.send_message("❌ Can't afford takeover cost.", ephemeral=True)
            return

        self.cog.civ_manager.spend_resources(self.user_id, {"gold": self.cost})

        success = self.guaranteed
        if not self.guaranteed and random.random() < 0.40:
            success = True

        if success:
            old_owner = target.get("owner_id")
            self.cog.db.update_corporation(target["id"], {
                "owner_id": str(self.user_id),
                "reputation": max(0, int(target.get("reputation", 50)) - 10),
            })
            try:
                old_user = await self.cog.bot.fetch_user(int(old_owner))
                await old_user.send(
                    f"⚔️ **You lost a corporation!** **{target['name']}** was taken over by another player."
                )
            except Exception:
                pass
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"✅ **{target['name']}** is now yours.",
                embed=None,
                view=self,
            )
        else:
            refund = self.cost // 2
            self.cog.civ_manager.update_resources(self.user_id, {"gold": refund})
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"❌ Takeover failed. Refunded 🪙 {format_number(refund)}.",
                embed=None,
                view=self,
            )

    async def _cancel(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Cancelled.", view=self)


async def setup(bot):
    await bot.add_cog(CorporationsCog(bot))
