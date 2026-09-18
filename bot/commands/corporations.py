import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import discord as guilded
from discord.ext import commands

from bot.utils import format_number, create_embed
from bot import config

logger = logging.getLogger(__name__)


class CorporationsCog(commands.Cog):
    """Business management sim. Runs an hourly tick loop over all corps."""

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
    # HOURLY TICK LOOP
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
            self.db.update_corporation(corp["id"], {
                "efficiency": new_eff,
                "morale": new_mor,
                "last_event": {"type": "info", "name": "Idle",
                               "desc": "No employees assigned — decaying."},
            })
            return

        # ---- Random event roll ----
        event = None
        event_effects = {}
        if random.random() < 0.15:
            event = random.choice(config.BUSINESS_EVENTS)
            event_effects = event.get("effect", {})

        # ---- Multipliers ----
        eff = float(corp.get("efficiency", 100))
        morale = float(corp.get("morale", 100))
        assets = float(corp.get("assets", 0))
        rd = float(corp.get("r_and_d", 0))

        # Efficiency decays 1/tick, morale 0.5/tick (restored by events/actions)
        eff = max(0, eff - 1)
        morale = max(0, morale - 0.5)

        # Apply event effects that modify stats
        if "efficiency" in event_effects:
            eff = max(0, min(100, eff + event_effects["efficiency"]))
        if "morale" in event_effects:
            morale = max(0, min(100, morale + event_effects["morale"]))

        # Employee factor: full bonus at 50+ employees
        emp_factor = min(1.0, employees / 50.0)

        revenue_mult = float(event_effects.get("revenue_mult", 1.0))
        production_mult = (
            (eff / 100.0)
            * (morale / 100.0)
            * (1 + assets / 100.0)
            * (1 + rd / 200.0)
            * emp_factor
            * revenue_mult
        )

        # ---- Inputs / outputs ----
        skip_production = bool(event_effects.get("skip_production"))
        produced_summary = {}
        consumed_summary = {}

        if not skip_production:
            # Check inputs
            can_produce = True
            for res, amt in ind.get("consumes", {}).items():
                if civ["resources"].get(res, 0) < amt:
                    can_produce = False
                    break

            if can_produce:
                # Consume
                for res, amt in ind.get("consumes", {}).items():
                    self.civ_manager.update_resources(owner_id, {res: -amt})
                    consumed_summary[res] = consumed_summary.get(res, 0) + amt

                # Produce
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
                # Missing inputs — small efficiency hit
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
            # Pull from owner civ treasury
            if civ["resources"].get("gold", 0) >= owed:
                self.civ_manager.update_resources(owner_id, {"gold": -owed})
                new_reserve = 0
                new_debt = int(corp.get("debt", 0))
            else:
                # Can't pay — becomes debt, morale tanks
                new_reserve = 0
                new_debt = int(corp.get("debt", 0)) + owed
                morale = max(0, morale - 15)

        # ---- Gold bonus / penalty from event ----
        bonus = int(event_effects.get("gold_bonus", 0))
        if bonus:
            if bonus > 0:
                new_reserve += bonus
            else:
                # Try reserve first, then debt
                cost = -bonus
                if new_reserve >= cost:
                    new_reserve -= cost
                else:
                    new_debt += (cost - new_reserve)
                    new_reserve = 0

        # Small chance reputation drifts toward 50
        rep = float(corp.get("reputation", 50))
        if rep > 50:
            rep = max(50, rep - 0.5)
        elif rep < 50:
            rep = min(50, rep + 0.5)

        # ---- Persist ----
        update = {
            "efficiency": round(eff, 2),
            "morale": round(morale, 2),
            "reserve": new_reserve,
            "debt": new_debt,
            "reputation": round(rep, 2),
            "last_event": (
                {"type": event["type"], "name": event["name"], "desc": event["desc"]}
                if event else None
            ),
        }
        self.db.update_corporation(corp["id"], update)

    # =================================================================
    # MAIN MENU
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
        await self._show_main_menu(ctx, corps, civ)

    async def _show_main_menu(self, ctx, corps, civ):
        embed = create_embed(
            "🏢 Your Corporations",
            f"Owner: **{civ['name']}**\n"
            f"Slots: **{len(corps)}/{config.CORP_LIMITS['max_per_user']}**",
            guilded.Color.dark_teal(),
        )
        if not corps:
            embed.add_field(
                name="No corporations yet",
                value="Build your first one with the button below.",
                inline=False,
            )
        else:
            for i, c in enumerate(corps, 1):
                ind = config.INDUSTRIES.get(c.get("industry"), {})
                reserve = int(c.get("reserve", 0))
                debt = int(c.get("debt", 0))
                debt_str = f" · 🔻 debt {format_number(debt)}" if debt > 0 else ""
                embed.add_field(
                    name=f"{ind.get('emoji','🏢')} {c['name']} (Lv {c.get('level',1)})",
                    value=(f"{ind.get('name','?')}\n"
                           f"Reserve: 🪙 {format_number(reserve)}{debt_str}\n"
                           f"Efficiency {int(c.get('efficiency',100))}% | "
                           f"Morale {int(c.get('morale',100))}% | "
                           f"Employees {c.get('employees',0)}"),
                    inline=False,
                )

        view = CorpMainMenuView(self, ctx.author.id, corps)
        await ctx.send(embed=embed, view=view)

    # =================================================================
    # BUILD
    # =================================================================
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
                f"Usage: `.corp build <industry> <name>`\n"
                f"Costs and requirements vary by industry.",
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

        # Checks
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
            # refund
            self.civ_manager.update_resources(user_id, {"gold": ind['startup_cost']})
            await ctx.send("❌ Failed to create corporation.")
            return

        await ctx.send(embed=create_embed(
            f"{ind['emoji']} {name} Founded",
            f"**{ind['name']}** corporation established in **{location}**.\n\n"
            f"Assign employees with `.corp manage {name}` → 👥 Staff.",
            guilded.Color.green(),
        ))

    # =================================================================
    # HELPERS
    # =================================================================
    def _find_corp(self, user_id: str, name_or_id: str) -> Optional[Dict[str, Any]]:
        name_or_id = (name_or_id or "").strip().lower()
        for c in self.db.get_user_corporations(user_id):
            if c["id"] == name_or_id: return c
        for c in self.db.get_user_corporations(user_id):
            if c["name"].lower() == name_or_id: return c
        for c in self.db.get_user_corporations(user_id):
            if name_or_id in c["name"].lower(): return c
        return None


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
            # Up to 5 "manage" buttons
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

        staff_btn = guilded.ui.Button(label="Staff", emoji="👥", style=guilded.ButtonStyle.primary)
        staff_btn.callback = self._staff
        self.add_item(staff_btn)

        assets_btn = guilded.ui.Button(label="Assets", emoji="🏗️", style=guilded.ButtonStyle.primary)
        assets_btn.callback = self._assets
        self.add_item(assets_btn)

        mkt_btn = guilded.ui.Button(label="Marketing", emoji="📈", style=guilded.ButtonStyle.primary)
        mkt_btn.callback = self._marketing
        self.add_item(mkt_btn)

        rd_btn = guilded.ui.Button(label="R&D", emoji="🔬", style=guilded.ButtonStyle.primary)
        rd_btn.callback = self._rd
        self.add_item(rd_btn)

        fin_btn = guilded.ui.Button(label="Finance", emoji="💰", style=guilded.ButtonStyle.success)
        fin_btn.callback = self._finance
        self.add_item(fin_btn)

        sell_btn = guilded.ui.Button(label="Sell", emoji="📤", style=guilded.ButtonStyle.danger)
        sell_btn.callback = self._sell
        self.add_item(sell_btn)

    def _make_embed(self, corp):
        ind = config.INDUSTRIES.get(corp.get("industry"), {})
        evt = corp.get("last_event")
        evt_line = ""
        if evt:
            icon = "🎉" if evt.get("type") == "positive" else ("⚠️" if evt.get("type") == "negative" else "ℹ️")
            evt_line = f"\n\n**Last event:** {icon} {evt['name']} — {evt['desc']}"
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
            f"😊 Morale: **{int(corp.get('morale',100))}%**"
            f"{evt_line}",
            guilded.Color.dark_teal(),
        )
        return embed

    async def _staff(self, interaction: guilded.Interaction):
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

    async def _assets(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        await self._buy_stat(interaction, "assets")

    async def _marketing(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        await self._buy_stat(interaction, "marketing")

    async def _rd(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        await self._buy_stat(interaction, "r_and_d")

    async def _buy_stat(self, interaction, stat_key):
        cost_map = {
            "assets": config.CORP_LIMITS["asset_cost_per_point"],
            "marketing": config.CORP_LIMITS["marketing_cost_per_point"],
            "r_and_d": config.CORP_LIMITS["rd_cost_per_point"],
        }
        cap_map = {
            "assets": config.CORP_LIMITS["max_assets"],
            "marketing": config.CORP_LIMITS["max_marketing"],
            "r_and_d": config.CORP_LIMITS["max_r_and_d"],
        }
        labels = {"assets": "Assets 🏗️", "marketing": "Marketing 📈", "r_and_d": "R&D 🔬"}
        unit_cost = cost_map[stat_key]
        cap = cap_map[stat_key]

        corp = self.cog.db.get_corporation(self.corp_id)
        current = int(corp.get(stat_key, 0))
        if current >= cap:
            await interaction.response.send_message(f"❌ {labels[stat_key]} already at cap ({cap}).", ephemeral=True)
            return

        # Buy 5 points at a time
        buy = min(5, cap - current)
        total_cost = unit_cost * buy

        civ = self.cog.civ_manager.get_civilization(self.user_id)
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

    async def _finance(self, interaction: guilded.Interaction):
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
        # Withdraw everything above the dividend minimum
        withdraw = reserve
        self.cog.db.update_corporation(self.corp_id, {"reserve": 0})
        self.cog.civ_manager.update_resources(self.user_id, {"gold": withdraw})
        await interaction.response.send_message(
            f"💰 Withdrew **{format_number(withdraw)} gold** from corp reserve.", ephemeral=True
        )

    async def _sell(self, interaction: guilded.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True)
            return
        corp = self.cog.db.get_corporation(self.corp_id)
        level = int(corp.get("level", 1))
        reserve = int(corp.get("reserve", 0))
        # 70% of reserve + level-based value
        sale_value = int(reserve * 0.7 + level * 50_000 * 0.7)
        # Confirm
        confirm_view = ConfirmSellView(self.cog, self.user_id, self.corp_id, sale_value)
        await interaction.response.send_message(
            f"⚠️ Sell **{corp['name']}** for 🪙 {format_number(sale_value)} gold?\n"
            f"Liquidates the corp permanently.",
            view=confirm_view,
            ephemeral=True,
        )


class StaffSubView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        # Row 1: hire buttons
        for amt in (5, 25, 100):
            btn = guilded.ui.Button(label=f"Hire {amt}", style=guilded.ButtonStyle.success)
            btn.callback = self._make_hire(amt)
            self.add_item(btn)

        # Fire all
        fire_btn = guilded.ui.Button(label="Fire All", style=guilded.ButtonStyle.danger)
        fire_btn.callback = self._fire_all
        self.add_item(fire_btn)

    @staticmethod
    def _make_embed(corp):
        civ_unemp = "—"
        return create_embed(
            f"👥 Staff — {corp['name']}",
            f"Employees: **{corp.get('employees',0)}** / {config.CORP_LIMITS['max_employees']}\n"
            f"Full productivity bonus at 50 employees.\n\n"
            f"*Costs your civ's citizens. Unemployed citizens are auto-assigned.*",
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
            # Available citizens
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
        self.cog.db.update_corporation(self.corp_id, {"employees": 0, "morale": max(0, int(corp.get("morale",100)) - 20)})
        await interaction.response.send_message(
            f"🔻 Fired all **{n}** employees. Morale −20.", ephemeral=True
        )


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


async def setup(bot):
    await bot.add_cog(CorporationsCog(bot))
