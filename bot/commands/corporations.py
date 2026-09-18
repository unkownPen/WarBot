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
# COG
# =====================================================================
class CorporationsCog(commands.Cog):
    """Business management sim. Hourly tick + level/research/contracts/branches."""

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
    # TICK LOOP
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

    def _compute_research_bonuses(self, corp: Dict[str, Any]) -> Dict[str, float]:
        """Return applied bonuses from R&D thresholds."""
        rd = float(corp.get("r_and_d", 0))
        out_mult = 1.0
        eff_floor = 0.0
        contract_slots = 0
        rep_rate = 0.0
        for thresh, tier in sorted(config.CORP_RESEARCH_TIERS.items()):
            if rd >= thresh:
                b = tier.get("bonus", {})
                if "output_mult" in b:
                    # tiers stack multiplicatively — take the highest one only
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

    def _tick_one_corp(self, corp: Dict[str, Any]):
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

        # Even with 0 employees the corp decays a little
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

        # ---- Random event roll ----
        event = None
        event_effects = {}
        if random.random() < 0.15:
            event = random.choice(config.BUSINESS_EVENTS)
            event_effects = event.get("effect", {})

        # ---- Research bonuses ----
        research = self._compute_research_bonuses(corp)

        # ---- Base multipliers ----
        eff = float(corp.get("efficiency", 100))
        morale = float(corp.get("morale", 100))
        assets = float(corp.get("assets", 0))
        rd = float(corp.get("r_and_d", 0))

        # Efficiency decays 1/tick, morale 0.5/tick
        eff = max(0, eff - 1)
        morale = max(0, morale - 0.5)

        # Apply event effects
        if "efficiency" in event_effects:
            eff = max(0, min(100, eff + event_effects["efficiency"]))
        if "morale" in event_effects:
            morale = max(0, min(100, morale + event_effects["morale"]))
        if "r_and_d" in event_effects:
            rd = max(0, min(100, rd + event_effects["r_and_d"]))

        # Efficiency floor from research
        eff = max(eff, research["efficiency_floor"])

        # Employee factor: full bonus at 50+ employees
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

        # ---- Inputs / outputs ----
        skip_production = bool(event_effects.get("skip_production"))
        produced_summary = {}
        consumed_summary = {}

        if not skip_production:
            can_produce = True
            for res, amt in ind.get("consumes", {}).items():
                if civ["resources"].get(res, 0) < amt:
                    can_produce = False
                    break

            if can_produce:
                for res, amt in ind.get("consumes", {}).items():
                    self.civ_manager.update_resources(owner_id, {res: -amt})
                    consumed_summary[res] = consumed_summary.get(res, 0) + amt

                for res, amt in ind.get("produces", {}).items():
                    produced = int(amt * production_mult)
                    if produced <= 0:
                        continue
                    if res == "soldiers":
                        self.civ_manager.update_military(owner_id, {"soldiers": produced})
                    else:
                        self.civ_manager.update_resources(owner_id, {res: produced})
                    produced_summary[res] = produced_summary.get(res, 0) + produced
            else:
                eff = max(0, eff - 5)

        # ---- Wages ----
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

        # ---- Event gold bonus / penalty ----
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

        # ---- Reputation drift + research rep rate ----
        rep = float(corp.get("reputation", 50))
        rep += research["rep_rate"]
        if rep > 50:
            rep = max(50, rep - 0.5)
        elif rep < 50:
            rep = min(50, rep + 0.5)
        rep = max(0, min(100, rep))

        # ---- Contracts expiry ----
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

        # Push event history into the corp doc if there was one
        if event:
            self._push_event(corp, {"type": event["type"], "name": event["name"], "desc": event["desc"]})

        self.db.update_corporation(corp["id"], update)

    def _push_event(self, corp: Dict[str, Any], evt: Dict[str, Any]):
        """Maintain a rolling list of the last 5 events on the corp doc."""
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
    # COMMANDS — main menu + build
    # =================================================================
    @commands.group(name="corp", aliases=["corporation", "biz"],
                    invoke_without_command=True)
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

        # initialize extended fields
        self.db.update_corporation(corp_id, {
            "branches": [],
            "contracts": [],
            "event_history": [],
            "research_unlocks": [],
        })

        await ctx.send(embed=create_embed(
            f"{ind['emoji']} {name} Founded",
            f"**{ind['name']}** corporation established in **{location}**.\n\n"
            f"Manage it with `.corp`.",
            guilded.Color.green(),
        ))

    # =================================================================
    # COMMANDS — leaderboard + takeover
    # =================================================================
    @corp.command(name="leaderboard", aliases=["lb", "top"])
    async def corp_leaderboard(self, ctx):
        corps = self.db.get_all_corporations()
        if not corps:
            await ctx.send("📭 No corporations exist yet.")
            return
        # sort by reserve
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
        """Attempt a hostile takeover of another player's corporation."""
        user_id = str(ctx.author.id)
        attacker_civ = self.civ_manager.get_civilization(user_id)
        if not attacker_civ:
            await ctx.send("❌ Need a civilization first.")
            return
        if not target_name:
            await ctx.send("Usage: `.corp takeover <corp name>`")
            return

        # Find target corp (any owner, exact or substring)
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

        attacker_rep = float(attacker_civ.get("reputation", 50))
        # Reputation isn't on the civ; use corp reputation of the attacker's best corp
        own_corps = self.db.get_user_corporations(user_id)
        if own_corps:
            attacker_rep = max(float(c.get("reputation", 50)) for c in own_corps)

        target_rep = float(target.get("reputation", 50))

        if attacker_rep < config.CORP_TAKEOVER["min_attacker_rep"]:
            await ctx.send(f"❌ Your reputation is too low (**{int(attacker_rep)}**). "
                           f"Minimum {config.CORP_TAKEOVER['min_attacker_rep']} required.")
            return

        # Cost
        level = int(target.get("level", 1))
        cost = int(target.get("reserve", 0)) + level * config.CORP_TAKEOVER["cost_per_level"]
        if not self.civ_manager.can_afford(user_id, {"gold": cost}):
            await ctx.send(f"❌ Takeover cost is 🪙 {format_number(cost)} — you can't afford it.")
            return

        # Success chance
        ratio = attacker_rep / max(1.0, attacker_rep + target_rep)
        success = ratio >= config.CORP_TAKEOVER["success_rep_ratio"]

        # Build view
        view = TakeoverView(self, ctx.author.id, target, cost, success)
        await ctx.send(embed=view._make_embed(), view=view)


# =====================================================================
# VIEWS
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

    async def _build(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Use `.corp build <industry> <name>` to found a corporation.",
            ephemeral=True,
        )

    def _make_manage(self, corp_id):
        async def callback(interaction: guilded.Interaction):
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

        # Row 0
        self._add("Staff", "👥", self._staff)
        self._add("Assets", "🏗️", lambda i: self._buy_stat(i, "assets"))
        self._add("Marketing", "📈", lambda i: self._buy_stat(i, "marketing"))

        # Row 1
        self._add("R&D", "🔬", lambda i: self._buy_stat(i, "r_and_d"))
        self._add("Research", "🧬", self._research)
        self._add("Branches", "🌍", self._branches)

        # Row 2
        self._add("Contracts", "📜", self._contracts)
        self._add("Log", "🗒️", self._log)
        self._add("Level Up", "⬆️", self._level)

        # Row 3
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
        research = self.cog._compute_research_bonuses(corp)
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

    # ---- sub-view openers ----
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


# =====================================================================
# STAFF
# =====================================================================
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
        async def callback(interaction: guilded.Interaction):
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

    async def _fire_all(self, interaction: guilded.Interaction):
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


# =====================================================================
# BRANCHES
# =====================================================================
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

    async def _add_branch(self, interaction: guilded.Interaction):
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

    async def _close_branch(self, interaction: guilded.Interaction):
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


# =====================================================================
# CONTRACTS
# =====================================================================
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

    async def _accept(self, interaction: guilded.Interaction):
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

    async def _fulfill_first(self, interaction: guilded.Interaction):
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

        # Check availability
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
        # Add reward to corp reserve
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

    async def _cancel_first(self, interaction: guilded.Interaction):
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


# =====================================================================
# LEVEL UP
# =====================================================================
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

    async def _upgrade(self, interaction: guilded.Interaction):
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


# =====================================================================
# SELL
# =====================================================================
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

    async def _confirm(self, interaction: guilded.Interaction):
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

    async def _cancel(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Cancelled.", view=self)


# =====================================================================
# TAKEOVER
# =====================================================================
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

    async def _attempt(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        if self.attempted:
            await interaction.response.send_message("Already attempted.", ephemeral=True)
            return
        self.attempted = True

        # Re-verify corp still exists and belongs to someone else
        target = self.cog.db.get_corporation(self.target["id"])
        if not target or str(target.get("owner_id")) == self.user_id:
            await interaction.response.send_message("Corp no longer available.", ephemeral=True)
            return

        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": self.cost}):
            await interaction.response.send_message("❌ Can't afford takeover cost.", ephemeral=True)
            return

        self.cog.civ_manager.spend_resources(self.user_id, {"gold": self.cost})

        # Guaranteed success path — attacker rep was >= threshold
        success = self.guaranteed
        if not self.guaranteed and random.random() < 0.40:
            success = True

        if success:
            old_owner = target.get("owner_id")
            self.cog.db.update_corporation(target["id"], {
                "owner_id": str(self.user_id),
                "reputation": max(0, int(target.get("reputation", 50)) - 10),
            })
            # notify old owner
            try:
                old_civ = self.cog.civ_manager.get_civilization(old_owner)
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
            # Refund half
            refund = self.cost // 2
            self.cog.civ_manager.update_resources(self.user_id, {"gold": refund})
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"❌ Takeover failed. Refunded 🪙 {format_number(refund)}.",
                embed=None,
                view=self,
            )

    async def _cancel(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Cancelled.", view=self)


async def setup(bot):
    await bot.add_cog(CorporationsCog(bot))
