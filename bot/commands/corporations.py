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
# LOCAL CONFIG — the four reworked systems
# =====================================================================
MARKETING_CHANNELS = {
    "radio": {
        "name": "Radio Ads", "emoji": "📻",
        "upkeep": 200, "marketing_per_tick": 0.3,
        "effect": {},
        "desc": "Cheap, stable, does nothing else.",
    },
    "newspaper": {
        "name": "Newspaper", "emoji": "📰",
        "upkeep": 500, "marketing_per_tick": 0.5,
        "effect": {"rep_rate": 0.2},
        "desc": "Decent boost, mild reputation growth.",
    },
    "influencer": {
        "name": "Social Influencers", "emoji": "📱",
        "upkeep": 1500, "marketing_per_tick": 1.0,
        "effect": {"viral_chance": 0.05},
        "desc": "Big marketing. 5% chance/tick of +10 viral spike.",
    },
    "tv": {
        "name": "TV Campaign", "emoji": "🎬",
        "upkeep": 3000, "marketing_per_tick": 1.5,
        "effect": {"scandal_chance": 0.05},
        "desc": "Biggest marketing. 5% chance/tick of -10 reputation scandal.",
    },
    "giveaway": {
        "name": "Public Giveaways", "emoji": "🎁",
        "upkeep": 2000, "marketing_per_tick": 0.5,
        "effect": {"faction": ("people", 0.5)},
        "desc": "+0.5 People faction per tick.",
    },
    "lobbying": {
        "name": "Corporate Lobbying", "emoji": "💼",
        "upkeep": 2500, "marketing_per_tick": 0.5,
        "effect": {"faction": ("merchant", 0.5)},
        "desc": "+0.5 Merchant faction per tick.",
    },
}
MARKETING_MAX_CHANNELS = 3
MARKETING_DECAY_PER_TICK = 0.3

ASSETS_TREE = {
    "warehouse": {
        "name": "Warehouse", "emoji": "🏭",
        "levels": [
            {"cost": 40_000, "effect": {"output_mult": 1.05}, "desc": "+5% output"},
            {"cost": 120_000, "effect": {"output_mult": 1.10}, "desc": "+10% output"},
            {"cost": 300_000, "effect": {"output_mult": 1.18}, "desc": "+18% output"},
        ],
    },
    "automation": {
        "name": "Automation Line", "emoji": "🤖",
        "levels": [
            {"cost": 80_000, "effect": {"output_mult": 1.08, "emp_bonus": 0.05}, "desc": "+8% output, +5% emp bonus"},
            {"cost": 250_000, "effect": {"output_mult": 1.12, "emp_bonus": 0.10}, "desc": "+12% output, +10% emp bonus"},
            {"cost": 600_000, "effect": {"output_mult": 1.20, "emp_bonus": 0.15}, "desc": "+20% output, +15% emp bonus"},
        ],
    },
    "qc": {
        "name": "Quality Control", "emoji": "🔍",
        "levels": [
            {"cost": 30_000, "effect": {"rep_rate": 0.3}, "desc": "+0.3 reputation/tick"},
            {"cost": 90_000, "effect": {"rep_rate": 0.6}, "desc": "+0.6 reputation/tick"},
            {"cost": 240_000, "effect": {"rep_rate": 1.0}, "desc": "+1.0 reputation/tick"},
        ],
    },
    "power": {
        "name": "Power Plant", "emoji": "⚡",
        "levels": [
            {"cost": 60_000, "effect": {"input_reduction": 0.05}, "desc": "−5% input consumption"},
            {"cost": 180_000, "effect": {"input_reduction": 0.10}, "desc": "−10% input consumption"},
            {"cost": 450_000, "effect": {"input_reduction": 0.18}, "desc": "−18% input consumption"},
        ],
    },
    "rail": {
        "name": "Rail Spur", "emoji": "🚂",
        "levels": [
            {"cost": 100_000, "effect": {"output_mult": 1.05}, "desc": "+5% output (requires another branch in same subregion)"},
            {"cost": 350_000, "effect": {"output_mult": 1.10}, "desc": "+10% output (requires another branch in same subregion)"},
        ],
    },
    "lab": {
        "name": "Research Lab", "emoji": "🧪",
        "levels": [
            {"cost": 50_000, "effect": {"rd_per_tick": 1}, "desc": "+1 R&D/tick"},
            {"cost": 150_000, "effect": {"rd_per_tick": 2}, "desc": "+2 R&D/tick"},
            {"cost": 400_000, "effect": {"rd_per_tick": 3}, "desc": "+3 R&D/tick"},
        ],
    },
    "vault": {
        "name": "Treasury Vault", "emoji": "🏦",
        "levels": [
            {"cost": 40_000, "effect": {"gold_mult": 1.05}, "desc": "+5% gold income"},
            {"cost": 120_000, "effect": {"gold_mult": 1.10}, "desc": "+10% gold income"},
        ],
    },
}
ASSET_LEVEL_CAP_BASE = 6
ASSET_LEVEL_CAP_PER_CORP_LEVEL = 1

RESEARCH_TREE = {
    "operations": {
        "name": "Operations", "emoji": "⚙️",
        "tiers": [
            {"key": "op1", "cost": 30,  "name": "Overclocked Lines",      "desc": "+5% output",                              "effect": {"output_mult": 1.05}},
            {"key": "op2", "cost": 80,  "name": "Predictive Maintenance", "desc": "+5% output, +1 efficiency floor",         "effect": {"output_mult": 1.05, "eff_floor": 1}},
            {"key": "op3", "cost": 180, "name": "Lean Manufacturing",     "desc": "−10% input consumption",                  "effect": {"input_reduction": 0.10}},
            {"key": "op4", "cost": 400, "name": "Fully Automated Plant",  "desc": "+20% output",                             "effect": {"output_mult": 1.20}},
        ],
    },
    "marketing": {
        "name": "Marketing", "emoji": "📈",
        "tiers": [
            {"key": "mk1", "cost": 30,  "name": "Brand Identity",   "desc": "+1 reputation/tick",                 "effect": {"rep_rate": 1.0}},
            {"key": "mk2", "cost": 80,  "name": "Viral Engine",     "desc": "Channels give +25% marketing",       "effect": {"channel_boost": 1.25}},
            {"key": "mk3", "cost": 180, "name": "Loyalty Program",  "desc": "−30% marketing decay",               "effect": {"decay_reduction": 0.30}},
            {"key": "mk4", "cost": 400, "name": "Global Icon",      "desc": "+3 reputation/tick, +10% output",    "effect": {"rep_rate": 3.0, "output_mult": 1.10}},
        ],
    },
    "science": {
        "name": "Science", "emoji": "🧬",
        "tiers": [
            {"key": "sc1", "cost": 30,  "name": "Data Analytics",     "desc": "+2 R&D/tick",                        "effect": {"rd_per_tick": 2}},
            {"key": "sc2", "cost": 80,  "name": "R&D Grants",         "desc": "Research costs −20%",                "effect": {"research_discount": 0.20}},
            {"key": "sc3", "cost": 180, "name": "Quantum Compute",    "desc": "+5 R&D/tick",                        "effect": {"rd_per_tick": 5}},
            {"key": "sc4", "cost": 400, "name": "Singularity Lab",    "desc": "+15 R&D/tick, +10% output",          "effect": {"rd_per_tick": 15, "output_mult": 1.10}},
        ],
    },
    "security": {
        "name": "Security", "emoji": "🛡️",
        "tiers": [
            {"key": "se1", "cost": 30,  "name": "Internal Audit",     "desc": "−50% scandal & espionage chance",     "effect": {"scandal_reduction": 0.50}},
            {"key": "se2", "cost": 80,  "name": "Insurance Policy",   "desc": "−30% loss on debt default",           "effect": {"default_reduction": 0.30}},
            {"key": "se3", "cost": 180, "name": "Merger Defense",     "desc": "Hostile takeovers against you cost +50%", "effect": {"takeover_cost_mult": 1.50}},
            {"key": "se4", "cost": 400, "name": "Corporate Empire",   "desc": "Immune to hostile takeover, +5% output",  "effect": {"takeover_immune": True, "output_mult": 1.05}},
        ],
    },
}

BRANCH_SUBREGION_BONUSES = {
    "Africa":         {"stone_mult": 1.05, "output_mult": 1.03, "label": "+5% stone, +3% output"},
    "Europe":         {"gold_mult": 1.03, "rd_per_tick": 1, "label": "+3% gold, +1 R&D/tick"},
    "Asia":           {"food_mult": 1.05, "output_mult": 1.02, "label": "+5% food, +2% output"},
    "Middle East":    {"gold_mult": 1.08, "label": "+8% gold"},
    "North America":  {"output_mult": 1.03, "marketing_bonus": 5, "label": "+3% output, +5 marketing"},
    "South America":  {"food_mult": 1.05, "wood_mult": 1.05, "label": "+5% food, +5% wood"},
    "Oceania":        {"output_mult": 1.05, "rep_rate": 3, "label": "+5% output, +3 rep/hr"},
    "Antarctica":     {"rd_per_tick": 2, "research_discount": 0.10, "label": "+2 R&D/tick, +10% research discount"},
}


def _subregion_continent(subregion: str) -> str:
    try:
        from bot.commands.territory import SUBREGION_TO_CONTINENT
        return SUBREGION_TO_CONTINENT.get(subregion, "")
    except Exception:
        return ""


def _province_subregion(province: str) -> str:
    try:
        from bot.commands.territory import PROVINCE_TO_SUBREGION
        return PROVINCE_TO_SUBREGION.get(province, "")
    except Exception:
        return ""


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
# DAILY VIEWS (unchanged)
# =====================================================================
class DailyMathView(guilded.ui.View):
    def __init__(self, cog, user_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.questions: List[Tuple[str, int, List[int]]] = []
        self.current_idx = 0
        self.correct_count = 0
        self.done = False
        for _ in range(3):
            self.questions.append(self._gen_q())
        self._rebuild_buttons()

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
            if offset == 0: continue
            cand = correct + offset
            if cand > 0: s.add(cand)
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
        async def callback(interaction):
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
    def __init__(self, cog, user_id: int, choices, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.choice_result = None
        for c in choices:
            btn = guilded.ui.Button(label=c["label"], emoji=c.get("emoji"),
                                    style=guilded.ButtonStyle.primary)
            btn.callback = self._make_cb(c)
            self.add_item(btn)

    def _make_cb(self, choice):
        async def callback(interaction):
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
    # HOURLY TICK
    # =================================================================
    async def _tick_loop(self):
        await self.bot.wait_until_ready()
        logger.info("Corporation tick loop started")
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(3600)
                await self._run_tick()
            except asyncio.CancelledError:
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
        """Read from research_unlocked list. Everything returns from the tree."""
        unlocked = set(corp.get("research_unlocked", []))
        b = {
            "output_mult": 1.0,
            "eff_floor": 0,
            "input_reduction": 0.0,
            "rep_rate": 0.0,
            "rd_per_tick": 0.0,
            "channel_boost": 1.0,
            "decay_reduction": 0.0,
            "scandal_reduction": 0.0,
            "default_reduction": 0.0,
            "takeover_cost_mult": 1.0,
            "takeover_immune": False,
            "research_discount": 0.0,
        }
        for branch in RESEARCH_TREE.values():
            for tier in branch["tiers"]:
                if tier["key"] not in unlocked:
                    continue
                for k, v in tier.get("effect", {}).items():
                    if k == "output_mult":       b["output_mult"] *= v
                    elif k == "eff_floor":       b["eff_floor"] = max(b["eff_floor"], v)
                    elif k == "input_reduction": b["input_reduction"] += v
                    elif k == "rep_rate":        b["rep_rate"] += v
                    elif k == "rd_per_tick":     b["rd_per_tick"] += v
                    elif k == "channel_boost":   b["channel_boost"] *= v
                    elif k == "decay_reduction": b["decay_reduction"] += v
                    elif k == "scandal_reduction": b["scandal_reduction"] += v
                    elif k == "default_reduction": b["default_reduction"] += v
                    elif k == "takeover_cost_mult": b["takeover_cost_mult"] *= v
                    elif k == "takeover_immune": b["takeover_immune"] = bool(v)
                    elif k == "research_discount": b["research_discount"] += v
        return b

    def _compute_asset_bonuses(self, corp):
        """Sum all asset effects. Returns dict of multipliers/flat bonuses."""
        built = corp.get("assets_built", {}) or {}
        b = {
            "output_mult": 1.0,
            "gold_mult": 1.0,
            "input_reduction": 0.0,
            "rep_rate": 0.0,
            "rd_per_tick": 0.0,
            "emp_bonus": 0.0,
        }
        for asset_key, level in built.items():
            tree = ASSETS_TREE.get(asset_key)
            if not tree:
                continue
            level = int(level)
            for i in range(min(level, len(tree["levels"]))):
                for k, v in tree["levels"][i].get("effect", {}).items():
                    if k == "output_mult":       b["output_mult"] *= v
                    elif k == "gold_mult":       b["gold_mult"] *= v
                    elif k == "input_reduction": b["input_reduction"] += v
                    elif k == "rep_rate":        b["rep_rate"] += v
                    elif k == "rd_per_tick":     b["rd_per_tick"] += v
                    elif k == "emp_bonus":       b["emp_bonus"] += v
        return b

    def _compute_branch_bonuses(self, corp):
        """Subregion flavor + adjacency bonus."""
        branches = corp.get("branches") or []
        b = {
            "output_mult": 1.0,
            "stone_mult": 1.0,
            "food_mult": 1.0,
            "wood_mult": 1.0,
            "gold_mult": 1.0,
            "rd_per_tick": 0.0,
            "rep_rate": 0.0,
            "marketing_bonus": 0.0,
            "research_discount": 0.0,
        }
        subregion_count = {}
        for province in branches:
            subregion = _province_subregion(province)
            continent = _subregion_continent(subregion) if subregion else ""
            subregion_count[subregion] = subregion_count.get(subregion, 0) + 1
            bonus = BRANCH_SUBREGION_BONUSES.get(continent)
            if not bonus:
                continue
            for k, v in bonus.items():
                if k == "label":
                    continue
                if k.endswith("_mult"):
                    b[k] = b.get(k, 1.0) * v
                elif k in ("rd_per_tick", "rep_rate", "marketing_bonus"):
                    b[k] = b.get(k, 0) + v
                elif k == "research_discount":
                    b["research_discount"] = b.get("research_discount", 0) + v
        # Adjacency: same-subregion branches give +5% output each
        adjacency_bonus = 0.0
        for sub, count in subregion_count.items():
            if count >= 2:
                adjacency_bonus += 0.05 * (count - 1)
        b["output_mult"] *= (1 + adjacency_bonus)
        return b

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
            self.db.update_corporation(corp["id"], {"efficiency": new_eff, "morale": new_mor})
            return

        # Base random event
        event = None
        event_effects = {}
        if random.random() < 0.15:
            event = random.choice(config.BUSINESS_EVENTS)
            event_effects = event.get("effect", {})

        # Bonus aggregates
        research = self._compute_research_bonuses(corp)
        assets   = self._compute_asset_bonuses(corp)
        branch   = self._compute_branch_bonuses(corp)

        eff = float(corp.get("efficiency", 100))
        morale = float(corp.get("morale", 100))
        rd_points = float(corp.get("r_and_d", 0))
        marketing = float(corp.get("marketing", 0))
        rep = float(corp.get("reputation", 50))
        channels = list(corp.get("marketing_channels") or [])

        # Efficiency + morale drift
        eff = max(0, eff - 1)
        morale = max(0, morale - 0.5)

        if "efficiency" in event_effects:
            eff = max(0, min(100, eff + event_effects["efficiency"]))
        if "morale" in event_effects:
            morale = max(0, min(100, morale + event_effects["morale"]))

        # Research efficiency floor (from ops tier 2)
        eff = max(eff, float(research.get("eff_floor", 0)))

        # ---- R&D accumulation ----
        base_rd = employees / 20.0
        rd_gain = base_rd + assets["rd_per_tick"] + research["rd_per_tick"] + branch["rd_per_tick"]
        rd_points += rd_gain

        # ---- Marketing accumulation + decay ----
        channel_boost = research["channel_boost"]
        channel_marketing = 0.0
        channel_upkeep = 0
        for c in channels:
            ch = MARKETING_CHANNELS.get(c)
            if not ch:
                continue
            channel_marketing += ch["marketing_per_tick"] * channel_boost
            channel_upkeep += ch["upkeep"]

        decay = MARKETING_DECAY_PER_TICK * (1 - research["decay_reduction"])
        marketing = max(0, min(100, marketing + channel_marketing - decay))
        marketing += branch["marketing_bonus"]

        # ---- Channel side effects ----
        channel_faction_drift = dict(corp.get("channel_faction_drift") or {"military": 0, "merchant": 0, "people": 0})
        for c in channels:
            ch = MARKETING_CHANNELS.get(c)
            if not ch:
                continue
            eff_e = ch.get("effect", {})
            if "rep_rate" in eff_e:
                rep += eff_e["rep_rate"]
            if "viral_chance" in eff_e:
                chance = eff_e["viral_chance"] * (1 - research["scandal_reduction"])
                if random.random() < chance:
                    marketing = min(100, marketing + 10)
                    self._push_event(corp, {"type": "positive", "name": "Viral Spike",
                                            "desc": "+10 marketing this tick"})
            if "scandal_chance" in eff_e:
                chance = eff_e["scandal_chance"] * (1 - research["scandal_reduction"])
                if random.random() < chance:
                    rep = max(0, rep - 10)
                    self._push_event(corp, {"type": "negative", "name": "Scandal",
                                            "desc": "−10 reputation"})
            if "faction" in eff_e:
                fname, delta = eff_e["faction"]
                channel_faction_drift[fname] = channel_faction_drift.get(fname, 0) + delta

        # Flush whole faction points
        for fname in list(channel_faction_drift.keys()):
            v = channel_faction_drift[fname]
            if abs(v) >= 1:
                whole = int(v)
                self.civ_manager.update_faction(owner_id, fname, whole)
                channel_faction_drift[fname] = v - whole

        # ---- Production ----
        emp_factor = min(1.0, employees / 50.0) + assets["emp_bonus"]
        emp_factor = min(1.5, emp_factor)

        revenue_mult = float(event_effects.get("revenue_mult", 1.0))
        level_mult = 1 + (level - 1) * config.CORP_LEVEL_REQUIREMENTS["output_bonus_per_level"]
        branch_count = len(corp.get("branches") or [])
        branch_flat_mult = 1 + 0.15 * branch_count

        # Channel synergy: 3+ active channels → +10%
        channel_synergy = 1.10 if len(channels) >= 3 else 1.0

        production_mult = (
            (eff / 100.0)
            * (morale / 100.0)
            * (1 + (marketing / 100.0) * 0.5)   # marketing gives up to +50%
            * emp_factor
            * revenue_mult
            * level_mult
            * branch_flat_mult
            * channel_synergy
            * research["output_mult"]
            * assets["output_mult"]
            * branch["output_mult"]
        )

        skip_production = bool(event_effects.get("skip_production"))
        if not skip_production:
            can_produce = True
            for res, amt in ind.get("consumes", {}).items():
                reduced = amt * (1 - min(0.9, assets["input_reduction"] + research["input_reduction"]))
                if civ["resources"].get(res, 0) < reduced:
                    can_produce = False
                    break
            if can_produce:
                for res, amt in ind.get("consumes", {}).items():
                    reduced = int(amt * (1 - min(0.9, assets["input_reduction"] + research["input_reduction"])))
                    self.civ_manager.update_resources(owner_id, {res: -reduced})
                for res, amt in ind.get("produces", {}).items():
                    produced = int(amt * production_mult)
                    if res == "gold":
                        produced = int(produced * assets["gold_mult"] * branch["gold_mult"])
                    elif res == "food":
                        produced = int(produced * branch["food_mult"])
                    elif res == "stone":
                        produced = int(produced * branch["stone_mult"])
                    elif res == "wood":
                        produced = int(produced * branch["wood_mult"])
                    if produced <= 0:
                        continue
                    if res == "soldiers":
                        self.civ_manager.update_military(owner_id, {"soldiers": produced})
                    else:
                        self.civ_manager.update_resources(owner_id, {res: produced})
            else:
                eff = max(0, eff - 5)

        # ---- Wages + channel upkeep ----
        wage_per_emp = ind.get("base_wage", 2)
        wages = int(employees * wage_per_emp * (1 + (level - 1) * 0.15))
        total_due = wages + channel_upkeep
        reserve = int(corp.get("reserve", 0))

        if reserve >= total_due:
            new_reserve = reserve - total_due
            new_debt = int(corp.get("debt", 0))
        else:
            owed = total_due - reserve
            if civ["resources"].get("gold", 0) >= owed:
                self.civ_manager.update_resources(owner_id, {"gold": -owed})
                new_reserve = 0
                new_debt = int(corp.get("debt", 0))
            else:
                new_reserve = 0
                new_debt = int(corp.get("debt", 0)) + owed
                morale = max(0, morale - 15)

        # Event gold bonus
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

        # Reputation drift (research + assets + branch + default)
        rep += assets["rep_rate"] + research["rep_rate"] + branch["rep_rate"]
        if rep > 50:
            rep = max(50, rep - 0.5)
        elif rep < 50:
            rep = min(50, rep + 0.5)
        rep = max(0, min(100, rep))

        # Contract expiry
        contracts = list(corp.get("contracts") or [])
        now = datetime.utcnow()
        still_valid = []
        for c in contracts:
            exp = c.get("expires_at")
            try:
                if exp and datetime.fromisoformat(exp) > now:
                    still_valid.append(c)
                else:
                    self._push_event(corp, {"type": "info", "name": "Contract Expired",
                                            "desc": c.get("name", "Contract")})
            except Exception:
                still_valid.append(c)

        update = {
            "efficiency": round(eff, 2),
            "morale": round(morale, 2),
            "reserve": new_reserve,
            "debt": new_debt,
            "reputation": round(rep, 2),
            "r_and_d": round(rd_points, 2),
            "marketing": round(marketing, 2),
            "contracts": still_valid,
            "channel_faction_drift": channel_faction_drift,
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
            logger.error(f"_push_event failed: {e}")

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
        corps = await asyncio.to_thread(self.db.get_user_corporations, user_id)
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
            embed.add_field(name="No corporations yet",
                            value="Use `.corp build <industry> <name>` to found one.",
                            inline=False)
        else:
            for c in corps:
                ind = config.INDUSTRIES.get(c.get("industry"), {})
                reserve = int(c.get("reserve", 0))
                debt = int(c.get("debt", 0))
                debt_str = f" · 🔻 debt {format_number(debt)}" if debt > 0 else ""
                branches = len(c.get("branches") or [])
                contracts = len(c.get("contracts") or [])
                channels = len(c.get("marketing_channels") or [])
                assets_levels = sum((c.get("assets_built") or {}).values())
                rp = int(c.get("r_and_d", 0))
                embed.add_field(
                    name=f"{ind.get('emoji','🏢')} {c['name']} (Lv {c.get('level',1)})",
                    value=(f"{ind.get('name','?')}\n"
                           f"Reserve: 🪙 {format_number(reserve)}{debt_str}\n"
                           f"Eff {int(c.get('efficiency',100))}% · Morale {int(c.get('morale',100))}% · "
                           f"Mkt {int(c.get('marketing',0))}\n"
                           f"Channels {channels} · Assets {assets_levels} · Branches {branches} · "
                           f"R&D {rp}pt · Contracts {contracts}"),
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
            embed = create_embed("🏢 Build a Corporation",
                                 "Usage: `.corp build <industry> <name>`",
                                 guilded.Color.dark_teal())
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
        if await asyncio.to_thread(self.db.count_user_corporations, user_id) >= lim["max_per_user"]:
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
        corp_id = await asyncio.to_thread(
            self.db.create_corporation, user_id, name, industry, location
        )
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
        corps = await asyncio.to_thread(self.db.get_all_corporations)
        if not corps:
            await ctx.send("📭 No corporations exist yet.")
            return
        def score(c):
            return int(c.get("reserve", 0)) + int(c.get("level", 1)) * 50_000
        top = sorted(corps, key=score, reverse=True)[:10]

        embed = create_embed("🏆 Top Corporations", "Ranked by value", guilded.Color.gold())
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
        all_corps = await asyncio.to_thread(self.db.get_all_corporations)
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

        own_corps = await asyncio.to_thread(self.db.get_user_corporations, user_id)
        attacker_rep = 50.0
        if own_corps:
            attacker_rep = max(float(c.get("reputation", 50)) for c in own_corps)
        target_rep = float(target.get("reputation", 50))

        # Security tree immunity
        target_research = self._compute_research_bonuses(target)
        if target_research.get("takeover_immune"):
            await ctx.send(f"🛡️ **{target['name']}** has a Corporate Empire — hostile takeovers cannot touch them.")
            return

        if attacker_rep < config.CORP_TAKEOVER["min_attacker_rep"]:
            await ctx.send(f"❌ Your reputation is too low (**{int(attacker_rep)}**). "
                           f"Minimum {config.CORP_TAKEOVER['min_attacker_rep']} required.")
            return

        level = int(target.get("level", 1))
        base_cost = int(target.get("reserve", 0)) + level * config.CORP_TAKEOVER["cost_per_level"]
        cost = int(base_cost * target_research.get("takeover_cost_mult", 1.0))
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

        state = await asyncio.to_thread(self.db.get_daily_state, user_id) or {}

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
                        description=(f"{BANNER}\n"
                                     f"🔥 Streak: **{streak}** days\n"
                                     f"⏰ Next daily in: **{hrs}h {mins}m**\n"
                                     f"{BANNER}\n\n"
                                     f"*Come back tomorrow, President.*"),
                        color=_hype_color("good"),
                    )
                    await ctx.send(embed=embed)
                    return
            except Exception:
                pass

        challenge = random.choice(["math", "decision", "gamble"])
        streak = int(state.get("streak", 0))
        next_streak = streak + 1

        if challenge == "math":
            embed = guilded.Embed(
                title=_hype_title("DAILY: MATH SPRINT 🧮", "great"),
                description=(f"{BANNER}\n"
                             f"🔥 Streak: **{streak}** → **{next_streak}**\n"
                             f"🎯 **3 questions** · **30 seconds**\n"
                             f"⚡ *Answer fast, answer right.*\n"
                             f"{BANNER}"),
                color=_hype_color("great"),
            )
            await ctx.send(embed=embed)
            view = DailyMathView(self, ctx.author.id, timeout=30.0)
            q, _, _ = view.questions[0]
            await ctx.send(f"**Q1/3:** What is **{q}**?", view=view)
            await view.wait()
            passed = view.correct_count >= 2
            await self._complete_daily(ctx, user_id, civ, passed,
                                       detail=f"Correct: **{view.correct_count}/3**")
            return

        if challenge == "decision":
            scenario, choices = self._roll_decision()
            embed = guilded.Embed(
                title=_hype_title("DAILY: DECISION 🎯", "great"),
                description=(f"{BANNER}\n"
                             f"🔥 Streak: **{streak}** → **{next_streak}**\n"
                             f"{BANNER}\n\n"
                             f"**{scenario}**\n\n"
                             f"*There's no wrong answer — only consequences.*"),
                color=_hype_color("great"),
            )
            view = DailyDecisionView(self, ctx.author.id, choices)
            await ctx.send(embed=embed, view=view)
            await view.wait()
            if view.choice_result is None:
                await ctx.send("⏰ Timed out. Try again next time.")
                return
            await self._apply_decision(user_id, view.choice_result)
            await self._complete_daily(ctx, user_id, civ, True,
                                       detail=f"Chose: **{view.choice_result['label']}**")
            return

        embed = guilded.Embed(
            title=_hype_title("DAILY: HIGH STAKES GAMBLE 🎲", "epic"),
            description=(f"{BANNER}\n"
                         f"🔥 Streak: **{streak}** → **{next_streak}**\n"
                         f"{BANNER}\n\n"
                         f"🎰 **Free spin.** Win **1k–10k gold** or nothing.\n"
                         f"💸 *No cost to you either way.*"),
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

    async def _apply_decision(self, user_id: str, choice):
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

    def _streak_reward(self, streak: int):
        base_gold = config.DAILY["base_gold"]
        base_food = config.DAILY["base_food"]
        mult = 1.0
        bonus_gold = 0
        bonus_item = None
        milestone_label = None
        for day in sorted(config.DAILY["milestones"].keys()):
            if streak >= day:
                m = config.DAILY["milestones"][day]
                mult = m["mult"]
                milestone_label = m.get("label")
                if streak == day:
                    bonus_gold = m.get("gold", 0)
                    bonus_item = m.get("item")
        mult = min(mult, config.DAILY["max_multiplier"])
        return {
            "gold": int(base_gold * mult) + bonus_gold,
            "food": int(base_food * mult),
            "mult": mult,
            "bonus_gold": bonus_gold,
            "bonus_item": bonus_item,
            "milestone_label": milestone_label,
        }

    async def _complete_daily(self, ctx, user_id, civ, passed, detail="", extra_gold=0):
        state = await asyncio.to_thread(self.db.get_daily_state, user_id) or {}
        streak = int(state.get("streak", 0))
        best = int(state.get("best_streak", 0))
        total = int(state.get("total_completed", 0))

        if not passed:
            state["streak"] = 0
            state["last_completed_at"] = datetime.utcnow().isoformat()
            await asyncio.to_thread(self.db.save_daily_state, user_id, state)
            embed = guilded.Embed(
                title=_hype_title("DAILY FAILED 💀", "common"),
                description=(f"{BANNER}\n{detail}\n\n"
                             f"🔥 Streak reset: **{streak} → 0**\n"
                             f"*You'll get 'em tomorrow, President.*"),
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
        await asyncio.to_thread(self.db.save_daily_state, user_id, state)

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
            description=(f"{BANNER}\n"
                         f"🔥 **Streak:** `{streak}` → **`{new_streak}`**  *(best: {best})*\n"
                         f"⚡ **Multiplier:** ×**{reward['mult']:.2f}**\n"
                         f"{BANNER}\n"
                         f"💰 **Gold:** +{format_number(total_gold)}\n"
                         f"🌾 **Food:** +{format_number(total_food)}"
                         f"{item_line}"
                         f"{milestone_line}\n\n"
                         f"*{detail}*"),
            color=_hype_color(tier),
        )
        embed.set_footer(text=f"Total completed: {total} days")
        await ctx.send(embed=embed)

    @commands.command(name="streak", aliases=["mystreak"])
    async def streak_info(self, ctx):
        user_id = str(ctx.author.id)
        state = await asyncio.to_thread(self.db.get_daily_state, user_id) or {}
        streak = int(state.get("streak", 0))
        best = int(state.get("best_streak", 0))
        total = int(state.get("total_completed", 0))
        last = state.get("last_completed_at")

        embed = guilded.Embed(
            title=_hype_title("YOUR STREAK", "great"),
            description=(f"{BANNER}\n"
                         f"🔥 **Current:** `{streak}` days\n"
                         f"🏆 **Best:** `{best}` days\n"
                         f"📊 **Total:** `{total}` days\n"
                         f"{BANNER}"),
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
                    embed.add_field(name="⏰ Next daily", value=f"**{hrs}h {mins}m**", inline=False)
                else:
                    embed.add_field(name="✅ Daily ready", value="Use `.daily` to claim it!", inline=False)
            except Exception:
                pass

        next_ms = None
        for day in sorted(config.DAILY["milestones"].keys()):
            if day > streak:
                next_ms = day
                break
        if next_ms:
            m = config.DAILY["milestones"][next_ms]
            embed.add_field(
                name=f"🎯 Next milestone — Day {next_ms}",
                value=(f"**{m.get('label','—')}** · ×{m['mult']:.2f} multiplier + "
                       f"🪙 {format_number(m['gold'])}"
                       + (f" + *{m['item']}* item" if m.get("item") else "")),
                inline=False,
            )

        await ctx.send(embed=embed)


# =====================================================================
# CORP VIEWS
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
            for c in corps[:5]:
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
            await interaction.response.defer(ephemeral=True)
            corp = await asyncio.to_thread(self.cog.db.get_corporation, corp_id)
            if not corp or str(corp.get("owner_id")) != str(self.user_id):
                await interaction.followup.send("Corporation not found.", ephemeral=True)
                return
            view = CorpManageView(self.cog, self.user_id, corp_id)
            await interaction.followup.send(embed=view.make_embed(corp), view=view, ephemeral=True)
        return callback


class CorpManageView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=600):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        # Row 0
        self._add("Staff",     "👥", self._staff)
        self._add("Marketing", "📈", self._marketing)
        self._add("Assets",    "🏗️", self._assets)

        # Row 1
        self._add("R&D Tree",  "🧬", self._research_tree)
        self._add("Branches",  "🌍", self._branches)
        self._add("Contracts", "📜", self._contracts)

        # Row 2
        self._add("Log",       "🗒️", self._log)
        self._add("Level Up",  "⬆️", self._level)
        self._add("Finance",   "💰", self._finance, style=guilded.ButtonStyle.success)

        # Row 3
        self._add("Sell",      "📤", self._sell, style=guilded.ButtonStyle.danger)

    def _add(self, label, emoji, cb, style=guilded.ButtonStyle.primary):
        btn = guilded.ui.Button(label=label, emoji=emoji, style=style)
        btn.callback = cb
        self.add_item(btn)

    def make_embed(self, corp):
        ind = config.INDUSTRIES.get(corp.get("industry"), {})
        evt = corp.get("last_event")
        evt_line = ""
        if evt:
            icon = "🎉" if evt.get("type") == "positive" else ("⚠️" if evt.get("type") == "negative" else "ℹ️")
            evt_line = f"\n\n**Last event:** {icon} {evt['name']} — {evt['desc']}"
        branches = corp.get("branches") or []
        channels = corp.get("marketing_channels") or []
        assets_built = corp.get("assets_built") or {}
        asset_levels = sum(assets_built.values())
        unlocked = corp.get("research_unlocked") or []
        rp = int(corp.get("r_and_d", 0))

        ch_names = ", ".join(MARKETING_CHANNELS.get(c, {}).get("name", c) for c in channels) or "None"

        embed = create_embed(
            f"{ind.get('emoji','🏢')} {corp['name']}",
            f"**{ind.get('name','?')}** · Lv {corp.get('level',1)} · {corp.get('location','?')}\n\n"
            f"💰 Reserve: **{format_number(int(corp.get('reserve',0)))}**"
            + (f"  ·  🔻 Debt: **{format_number(int(corp.get('debt',0)))}**" if corp.get('debt',0) else "")
            + f"\n👥 Employees: **{corp.get('employees',0)}**\n"
            f"⚙️ Efficiency: **{int(corp.get('efficiency',100))}%**  ·  "
            f"😊 Morale: **{int(corp.get('morale',100))}%**\n"
            f"📈 Marketing: **{int(corp.get('marketing',0))}**  ·  "
            f"⭐ Reputation: **{int(corp.get('reputation',50))}**\n"
            f"🧬 R&D points: **{rp}**  ·  Unlocked: **{len(unlocked)}/16**\n"
            f"🏗️ Assets: **{asset_levels}** levels\n"
            f"📻 Channels: {ch_names}\n"
            f"🌍 Branches: **{len(branches)}**  ·  📜 Contracts: **{len(corp.get('contracts') or [])}**"
            f"{evt_line}",
            guilded.Color.dark_teal(),
        )
        return embed

    async def _staff(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        view = StaffSubView(self.cog, self.user_id, self.corp_id)
        await interaction.followup.send(embed=StaffSubView.make_embed(corp), view=view, ephemeral=True)

    async def _marketing(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        view = MarketingChannelsView(self.cog, self.user_id, self.corp_id)
        await interaction.followup.send(embed=view.make_embed(corp), view=view, ephemeral=True)

    async def _assets(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        view = AssetsBuildView(self.cog, self.user_id, self.corp_id)
        await interaction.followup.send(embed=view.make_embed(corp), view=view, ephemeral=True)

    async def _research_tree(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        view = ResearchTreeView(self.cog, self.user_id, self.corp_id)
        await interaction.followup.send(embed=view.make_embed(corp), view=view, ephemeral=True)

    async def _branches(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        view = BranchesView(self.cog, self.user_id, self.corp_id)
        await interaction.followup.send(embed=view.make_embed(corp), view=view, ephemeral=True)

    async def _contracts(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        view = ContractsView(self.cog, self.user_id, self.corp_id)
        await interaction.followup.send(embed=view.make_embed(corp), view=view, ephemeral=True)

    async def _log(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        history = corp.get("event_history") or []
        embed = create_embed("🗒️ Event Log", f"Last {len(history)} events", guilded.Color.greyple())
        if not history:
            embed.description = "No events recorded yet."
        else:
            for e in history:
                icon = "🎉" if e.get("type") == "positive" else ("⚠️" if e.get("type") == "negative" else "ℹ️")
                embed.add_field(name=f"{icon} {e.get('name','?')}",
                                value=f"{e.get('desc','')}\n*{e.get('at','')}*", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _level(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        view = LevelUpView(self.cog, self.user_id, self.corp_id)
        await interaction.followup.send(embed=view.make_embed(corp), view=view, ephemeral=True)

    async def _finance(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        reserve = int(corp.get("reserve", 0))
        if reserve < config.CORP_LIMITS["dividend_min"]:
            await interaction.followup.send(
                f"❌ Reserve is {format_number(reserve)} gold — minimum to withdraw is "
                f"{format_number(config.CORP_LIMITS['dividend_min'])}.", ephemeral=True)
            return
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {"reserve": 0})
        self.cog.civ_manager.update_resources(self.user_id, {"gold": reserve})
        await interaction.followup.send(
            f"💰 Withdrew **{format_number(reserve)} gold** from corp reserve.", ephemeral=True)

    async def _sell(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        level = int(corp.get("level", 1))
        reserve = int(corp.get("reserve", 0))
        sale_value = int(reserve * 0.7 + level * 50_000 * 0.7)
        view = ConfirmSellView(self.cog, self.user_id, self.corp_id, sale_value)
        await interaction.followup.send(
            f"⚠️ Sell **{corp['name']}** for 🪙 {format_number(sale_value)} gold?",
            view=view, ephemeral=True)


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
    def make_embed(corp):
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
                await interaction.response.send_message("Not yours.", ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
            civ = self.cog.civ_manager.get_civilization(self.user_id)
            cap = config.CORP_LIMITS["max_employees"]
            current = int(corp.get("employees", 0))
            room = cap - current
            if room <= 0:
                await interaction.followup.send("❌ Already at max employees.", ephemeral=True); return
            employed = civ['population'].get('employed', 0)
            citizens = civ['population']['citizens']
            available = max(0, citizens - employed)
            hire = min(amount, room, available)
            if hire <= 0:
                await interaction.followup.send("❌ No unemployed citizens available.", ephemeral=True); return
            await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {"employees": current + hire})
            await interaction.followup.send(
                f"✅ Hired **{hire}** employees (corp now has {current + hire}).", ephemeral=True)
        return callback

    async def _fire_all(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        n = int(corp.get("employees", 0))
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {
            "employees": 0,
            "morale": max(0, int(corp.get("morale", 100)) - 20),
        })
        await interaction.followup.send(f"🔻 Fired all **{n}** employees. Morale −20.", ephemeral=True)


# =====================================================================
# MARKETING CHANNELS
# =====================================================================
class MarketingChannelsView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        options = []
        for key, ch in MARKETING_CHANNELS.items():
            options.append(guilded.SelectOption(
                label=f"{ch['emoji']} {ch['name']}",
                value=key,
                description=f"{ch['upkeep']}g/hr · +{ch['marketing_per_tick']} mkt/tick",
            ))
        select = guilded.ui.Select(
            placeholder=f"Pick up to {MARKETING_MAX_CHANNELS} channels",
            options=options,
            min_values=0,
            max_values=MARKETING_MAX_CHANNELS,
            row=0,
        )
        select.callback = self._update
        self.add_item(select)

        # Cleanup button — clears all channels
        clear_btn = guilded.ui.Button(label="Clear All Channels", emoji="❌",
                                       style=guilded.ButtonStyle.danger, row=1)
        clear_btn.callback = self._clear
        self.add_item(clear_btn)

    def make_embed(self, corp):
        channels = list(corp.get("marketing_channels") or [])
        marketing = float(corp.get("marketing", 0))
        research = self.cog._compute_research_bonuses(corp)
        decay = MARKETING_DECAY_PER_TICK * (1 - research["decay_reduction"])
        boost = research["channel_boost"]

        total_mkt = sum(MARKETING_CHANNELS[c]["marketing_per_tick"] * boost
                        for c in channels if c in MARKETING_CHANNELS)
        total_upkeep = sum(MARKETING_CHANNELS[c]["upkeep"]
                           for c in channels if c in MARKETING_CHANNELS)

        embed = create_embed(
            "📈 Marketing Channels",
            f"Current marketing: **{int(marketing)}**/100\n"
            f"Decay/tick: **-{decay:.2f}**  ·  Your gain: **+{total_mkt:.2f}/tick**\n"
            f"Upkeep: **{format_number(total_upkeep)}g/hr**\n"
            f"Active: **{len(channels)}/{MARKETING_MAX_CHANNELS}**",
            guilded.Color.purple(),
        )

        for key, ch in MARKETING_CHANNELS.items():
            active = "✅ " if key in channels else ""
            eff_desc = ""
            e = ch.get("effect", {})
            if "rep_rate" in e: eff_desc = f" · +{e['rep_rate']} rep/tick"
            elif "viral_chance" in e: eff_desc = f" · {int(e['viral_chance']*100)}% viral spike"
            elif "scandal_chance" in e: eff_desc = f" · {int(e['scandal_chance']*100)}% scandal"
            elif "faction" in e:
                fname, delta = e["faction"]
                eff_desc = f" · +{delta} {fname}/tick"
            embed.add_field(
                name=f"{active}{ch['emoji']} {ch['name']}",
                value=f"*{ch['desc']}*\n{ch['upkeep']}g/hr · +{ch['marketing_per_tick']} mkt/tick{eff_desc}",
                inline=False,
            )

        # Synergy hint
        if len(channels) >= 3:
            embed.set_footer(text="🔥 3-channel synergy active: +10% output")
        elif len(channels) > 0:
            embed.set_footer(text=f"{MARKETING_MAX_CHANNELS - len(channels)} more channel(s) for synergy bonus")

        return embed

    async def _update(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        new_channels = [v for v in interaction.data.get("values", []) if v in MARKETING_CHANNELS]
        new_channels = new_channels[:MARKETING_MAX_CHANNELS]
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id,
                                {"marketing_channels": new_channels})
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        try:
            await interaction.message.edit(embed=self.make_embed(corp), view=self)
        except Exception:
            pass
        await interaction.followup.send(f"✅ Set channels: {', '.join(new_channels) or 'none'}.", ephemeral=True)

    async def _clear(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id,
                                {"marketing_channels": []})
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        try:
            await interaction.message.edit(embed=self.make_embed(corp), view=self)
        except Exception:
            pass
        await interaction.followup.send("❌ All channels cleared.", ephemeral=True)


# =====================================================================
# ASSETS BUILD MENU
# =====================================================================
class AssetsBuildView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        # Select an asset
        options = []
        for key, asset in ASSETS_TREE.items():
            options.append(guilded.SelectOption(
                label=f"{asset['emoji']} {asset['name']}",
                value=key,
                description=f"{len(asset['levels'])} levels available",
            ))
        select = guilded.ui.Select(placeholder="Pick an asset to build", options=options, row=0)
        select.callback = self._pick_asset
        self.add_item(select)

    def _level_cap(self, corp):
        return ASSET_LEVEL_CAP_BASE + (int(corp.get("level", 1)) - 1) * ASSET_LEVEL_CAP_PER_CORP_LEVEL

    def _used_levels(self, corp):
        return sum((corp.get("assets_built") or {}).values())

    def make_embed(self, corp):
        built = corp.get("assets_built") or {}
        used = self._used_levels(corp)
        cap = self._level_cap(corp)
        bonus = self.cog._compute_asset_bonuses(corp)

        embed = create_embed(
            "🏗️ Assets",
            f"Asset slots: **{used}/{cap}**\n"
            f"Current bonuses:\n"
            f"• Output: ×{bonus['output_mult']:.2f}\n"
            f"• Gold: ×{bonus['gold_mult']:.2f}\n"
            f"• Input reduction: {int(bonus['input_reduction']*100)}%\n"
            f"• Rep/tick: +{bonus['rep_rate']:.2f}\n"
            f"• R&D/tick: +{bonus['rd_per_tick']:.0f}",
            guilded.Color.dark_teal(),
        )

        for key, asset in ASSETS_TREE.items():
            lvl = int(built.get(key, 0))
            max_lvl = len(asset["levels"])
            if lvl >= max_lvl:
                bar = "🟩" * max_lvl
                status = f"**MAXED** · {bar}"
                next_cost = "—"
            else:
                bar = "🟩" * lvl + "⬜" * (max_lvl - lvl)
                nxt = asset["levels"][lvl]
                next_cost = f"Next: 🪙 {format_number(nxt['cost'])} → {nxt['desc']}"
                status = f"Lv {lvl}/{max_lvl} · {bar}"
            embed.add_field(
                name=f"{asset['emoji']} {asset['name']}",
                value=f"{status}\n{next_cost}",
                inline=False,
            )

        embed.set_footer(text=f"Level {corp.get('level',1)} · Asset cap {cap}")
        return embed

    async def _pick_asset(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        asset_key = interaction.data.get("values", [None])[0]
        if not asset_key or asset_key not in ASSETS_TREE:
            await interaction.response.defer(); return
        view = AssetUpgradeView(self.cog, self.user_id, self.corp_id, asset_key)
        await interaction.response.send_message(
            embed=view.make_embed(await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)),
            view=view, ephemeral=True,
        )


class AssetUpgradeView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, asset_key, timeout=180):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id
        self.asset_key = asset_key

        buy_btn = guilded.ui.Button(label="Buy Next Level", emoji="⬆️",
                                     style=guilded.ButtonStyle.success)
        buy_btn.callback = self._buy
        self.add_item(buy_btn)

    def _level_cap(self, corp):
        return ASSET_LEVEL_CAP_BASE + (int(corp.get("level", 1)) - 1) * ASSET_LEVEL_CAP_PER_CORP_LEVEL

    def _used_levels(self, corp):
        return sum((corp.get("assets_built") or {}).values())

    def make_embed(self, corp):
        asset = ASSETS_TREE[self.asset_key]
        built = corp.get("assets_built") or {}
        lvl = int(built.get(self.asset_key, 0))
        max_lvl = len(asset["levels"])

        embed = create_embed(
            f"{asset['emoji']} {asset['name']}",
            f"Current level: **{lvl}/{max_lvl}**\n"
            f"Asset slots: **{self._used_levels(corp)}/{self._level_cap(corp)}**",
            guilded.Color.dark_teal(),
        )

        for i, level in enumerate(asset["levels"]):
            marker = "✅" if i < lvl else "⬜"
            embed.add_field(
                name=f"{marker} Level {i+1}",
                value=f"🪙 {format_number(level['cost'])}\n{level['desc']}",
                inline=False,
            )
        return embed

    async def _buy(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)

        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        asset = ASSETS_TREE[self.asset_key]
        built = dict(corp.get("assets_built") or {})
        lvl = int(built.get(self.asset_key, 0))
        if lvl >= len(asset["levels"]):
            await interaction.followup.send("❌ Already at max level for this asset.", ephemeral=True); return
        if self._used_levels(corp) >= self._level_cap(corp):
            await interaction.followup.send(
                f"❌ Asset slot cap reached ({self._level_cap(corp)}). "
                f"Level up your corporation to buy more.", ephemeral=True); return

        next_level = asset["levels"][lvl]
        cost = next_level["cost"]
        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": cost}):
            await interaction.followup.send(f"❌ Need 🪙 {format_number(cost)}.", ephemeral=True); return

        self.cog.civ_manager.spend_resources(self.user_id, {"gold": cost})
        built[self.asset_key] = lvl + 1
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {"assets_built": built})

        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        try:
            await interaction.message.edit(embed=self.make_embed(corp), view=self)
        except Exception:
            pass
        await interaction.followup.send(
            f"✅ Bought **{asset['name']}** Level {lvl + 1} for 🪙 {format_number(cost)}.",
            ephemeral=True)


# =====================================================================
# RESEARCH TREE
# =====================================================================
class ResearchTreeView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        options = []
        for key, branch in RESEARCH_TREE.items():
            options.append(guilded.SelectOption(
                label=f"{branch['emoji']} {branch['name']}",
                value=key,
                description=" · ".join(f"{t['cost']}pt" for t in branch["tiers"]),
            ))
        select = guilded.ui.Select(placeholder="Pick a research branch", options=options, row=0)
        select.callback = self._pick
        self.add_item(select)

    def make_embed(self, corp):
        rp = int(corp.get("r_and_d", 0))
        unlocked = set(corp.get("research_unlocked") or [])
        embed = create_embed(
            "🧬 Research Tree",
            f"**R&D Points:** {rp}\n"
            f"**Unlocked:** {len(unlocked)}/16\n\n"
            f"Pick a branch to view its tiers.",
            guilded.Color.purple(),
        )
        for key, branch in RESEARCH_TREE.items():
            lines = []
            for tier in branch["tiers"]:
                if tier["key"] in unlocked:
                    lines.append(f"✅ {tier['name']} — {tier['desc']}")
                else:
                    lines.append(f"⬜ {tier['name']} ({tier['cost']}pt) — {tier['desc']}")
            embed.add_field(
                name=f"{branch['emoji']} {branch['name']}",
                value="\n".join(lines),
                inline=False,
            )
        return embed

    async def _pick(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        branch_key = interaction.data.get("values", [None])[0]
        if not branch_key or branch_key not in RESEARCH_TREE:
            await interaction.response.defer(); return
        view = ResearchBranchView(self.cog, self.user_id, self.corp_id, branch_key)
        await interaction.response.send_message(
            embed=view.make_embed(await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)),
            view=view, ephemeral=True,
        )


class ResearchBranchView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, branch_key, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id
        self.branch_key = branch_key

        branch = RESEARCH_TREE[branch_key]
        for tier in branch["tiers"]:
            btn = guilded.ui.Button(
                label=f"{tier['name']} ({tier['cost']}pt)",
                style=guilded.ButtonStyle.success,
                row=min(4, len(self.children)),
            )
            btn.callback = self._make_unlock(tier)
            self.add_item(btn)

    def make_embed(self, corp):
        branch = RESEARCH_TREE[self.branch_key]
        rp = int(corp.get("r_and_d", 0))
        unlocked = set(corp.get("research_unlocked") or [])
        # Research discount from corp assets / branches
        assets = self.cog._compute_asset_bonuses(corp)
        research_b = self.cog._compute_research_bonuses(corp)
        branch_b = self.cog._compute_branch_bonuses(corp)
        discount = research_b.get("research_discount", 0) + branch_b.get("research_discount", 0)
        discount = min(0.75, discount)

        embed = create_embed(
            f"{branch['emoji']} {branch['name']}",
            f"**R&D Points:** {rp}\n"
            f"**Discount:** {int(discount*100)}%\n\n"
            f"Click a tier to unlock it. Tiers must be unlocked in order.",
            guilded.Color.purple(),
        )
        for i, tier in enumerate(branch["tiers"]):
            actual_cost = int(tier["cost"] * (1 - discount))
            if tier["key"] in unlocked:
                status = "✅ Unlocked"
            else:
                # Check tier ordering: previous tier must be unlocked
                if i == 0 or branch["tiers"][i - 1]["key"] in unlocked:
                    status = f"🔓 Available — {actual_cost}pt"
                else:
                    status = f"🔒 Locked (finish previous tier)"
            embed.add_field(
                name=f"{tier['name']}",
                value=f"{tier['desc']}\n{status}",
                inline=False,
            )
        return embed

    def _make_unlock(self, tier):
        async def callback(interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not yours.", ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
            unlocked = list(corp.get("research_unlocked") or [])
            rp = float(corp.get("r_and_d", 0))

            if tier["key"] in unlocked:
                await interaction.followup.send("❌ Already unlocked.", ephemeral=True); return

            branch = RESEARCH_TREE[self.branch_key]
            idx = branch["tiers"].index(tier)
            if idx > 0 and branch["tiers"][idx - 1]["key"] not in unlocked:
                await interaction.followup.send("❌ Finish the previous tier first.", ephemeral=True); return

            research_b = self.cog._compute_research_bonuses(corp)
            branch_b = self.cog._compute_branch_bonuses(corp)
            discount = min(0.75, research_b.get("research_discount", 0) + branch_b.get("research_discount", 0))
            cost = int(tier["cost"] * (1 - discount))

            if rp < cost:
                await interaction.followup.send(
                    f"❌ Need **{cost}** R&D points. You have **{int(rp)}**.", ephemeral=True); return

            unlocked.append(tier["key"])
            new_rp = rp - cost
            await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {
                "research_unlocked": unlocked,
                "r_and_d": round(new_rp, 2),
            })

            corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
            try:
                await interaction.message.edit(embed=self.make_embed(corp), view=self)
            except Exception:
                pass
            await interaction.followup.send(
                f"✅ Unlocked **{tier['name']}** for {cost} points.\n*{tier['desc']}*",
                ephemeral=True)
        return callback


# =====================================================================
# BRANCHES (fixed)
# =====================================================================
class BranchesView(guilded.ui.View):
    def __init__(self, cog, user_id, corp_id, timeout=300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.corp_id = corp_id

        add_btn = guilded.ui.Button(label="Add Branch", emoji="🌍",
                                     style=guilded.ButtonStyle.success)
        add_btn.callback = self._add_branch
        self.add_item(add_btn)

        close_btn = guilded.ui.Button(label="Close Last Branch", emoji="❌",
                                       style=guilded.ButtonStyle.danger)
        close_btn.callback = self._close_branch
        self.add_item(close_btn)

    def _max_branches(self, corp):
        level = int(corp.get("level", 1))
        return config.CORP_LEVEL_REQUIREMENTS["branch_slots_per_level"][min(level-1, 9)]

    def make_embed(self, corp):
        branches = list(corp.get("branches") or [])
        level = int(corp.get("level", 1))
        max_branches = self._max_branches(corp)
        cost = level * config.CORP_BRANCH_COST_MULT
        upkeep = int(corp.get("employees", 0) * 0.2)  # rough display

        # Subregion counts
        subregion_count = {}
        for province in branches:
            sub = _province_subregion(province)
            subregion_count[sub] = subregion_count.get(sub, 0) + 1

        # Build branch display with flavor
        branch_lines = []
        for province in branches:
            sub = _province_subregion(province)
            continent = _subregion_continent(sub) if sub else ""
            bonus = BRANCH_SUBREGION_BONUSES.get(continent)
            label = f" • *{bonus['label']}*" if bonus else ""
            branch_lines.append(f"• **{province}**{label}")

        # Adjacency bonus
        adjacency_notes = []
        for sub, count in subregion_count.items():
            if count >= 2 and sub:
                adjacency_notes.append(f"• {sub}: **{count}** branches → +{5*(count-1)}% output")

        embed = create_embed(
            "🌍 Branches",
            f"Level {level} · Slots: **{len(branches)}/{max_branches}**\n"
            f"Each branch adds **+15% production**.\n"
            f"Add branch cost: 🪙 **{format_number(cost)}**\n\n"
            + ("**Branches:**\n" + "\n".join(branch_lines) if branch_lines else "*No branches yet.*")
            + ("\n\n**Adjacency bonuses:**\n" + "\n".join(adjacency_notes) if adjacency_notes else ""),
            guilded.Color.dark_green(),
        )
        return embed

    async def _add_branch(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)

        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        level = int(corp.get("level", 1))
        branches = list(corp.get("branches") or [])
        max_branches = self._max_branches(corp)

        if len(branches) >= max_branches:
            await interaction.followup.send(
                f"❌ Max branches for Level {level} is **{max_branches}**. Level up your corp.",
                ephemeral=True)
            return

        cost = level * config.CORP_BRANCH_COST_MULT
        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": cost}):
            await interaction.followup.send(f"❌ Need 🪙 {format_number(cost)}.", ephemeral=True); return

        # FIXED: case-insensitive matching
        owned = self.cog.db.get_player_territories(self.user_id)
        branches_lower = {b.lower() for b in branches}
        loc_lower = (corp.get("location") or "").lower()
        candidates = [
            p for p in owned
            if p.lower() not in branches_lower and p.lower() != loc_lower
        ]

        if not candidates:
            await interaction.followup.send(
                f"❌ No other owned provinces available.\n"
                f"You own {len(owned)} · Already branched: {len(branches)} · HQ: {corp.get('location','?')}",
                ephemeral=True)
            return

        # Show selection menu
        options = []
        for p in candidates[:25]:
            sub = _province_subregion(p)
            continent = _subregion_continent(sub) if sub else ""
            bonus = BRANCH_SUBREGION_BONUSES.get(continent)
            hint = bonus["label"] if bonus else sub or "unknown region"
            options.append(guilded.SelectOption(label=p[:100], value=p, description=hint[:100]))

        select = guilded.ui.Select(placeholder="Pick a province for the branch", options=options)
        view = guilded.ui.View(timeout=60)
        view.add_item(select)

        async def on_pick(i2):
            if i2.user.id != self.user_id:
                await i2.response.send_message("Not yours.", ephemeral=True); return
            chosen = i2.data.get("values", [None])[0]
            if not chosen:
                await i2.response.defer(); return
            if not self.cog.civ_manager.can_afford(self.user_id, {"gold": cost}):
                await i2.response.send_message(f"❌ Need 🪙 {format_number(cost)}.", ephemeral=True); return
            self.cog.civ_manager.spend_resources(self.user_id, {"gold": cost})
            new_branches = branches + [chosen]
            await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id,
                                    {"branches": new_branches})
            corp2 = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
            await i2.response.send_message(
                f"🌍 Branch opened in **{chosen}** for 🪙 {format_number(cost)}.",
                ephemeral=True)
            try:
                await interaction.edit_original_response(
                    embed=self.make_embed(corp2), view=self)
            except Exception:
                pass

        select.callback = on_pick
        await interaction.followup.send("Pick a province for the new branch:", view=view, ephemeral=True)

    async def _close_branch(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        branches = list(corp.get("branches") or [])
        if not branches:
            await interaction.followup.send("❌ No branches to close.", ephemeral=True); return
        removed = branches.pop()
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {"branches": branches})
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        try:
            await interaction.message.edit(embed=self.make_embed(corp), view=self)
        except Exception:
            pass
        await interaction.followup.send(
            f"❌ Closed branch in **{removed}**. No refund.", ephemeral=True)


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

    def make_embed(self, corp):
        active = corp.get("contracts") or []
        research = self.cog._compute_research_bonuses(corp)
        slots = config.CORP_CONTRACT_SLOT_BASE + int(research.get("contract_slots", 0))
        embed = create_embed("📜 Contracts", f"Active: **{len(active)}/{slots}**", guilded.Color.gold())
        if not active:
            embed.add_field(name="No active contracts",
                            value="Click **Accept** to grab a random contract.", inline=False)
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
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        active = list(corp.get("contracts") or [])
        research = self.cog._compute_research_bonuses(corp)
        slots = config.CORP_CONTRACT_SLOT_BASE + int(research.get("contract_slots", 0))
        if len(active) >= slots:
            await interaction.followup.send(f"❌ All {slots} contract slots in use.", ephemeral=True); return
        template = random.choice(config.CORP_CONTRACT_POOL).copy()
        template["expires_at"] = (datetime.utcnow() + timedelta(hours=template["hours"])).isoformat()
        active.append(template)
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {"contracts": active})
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        try:
            await interaction.message.edit(embed=self.make_embed(corp), view=self)
        except Exception:
            pass
        await interaction.followup.send(
            f"✍️ Accepted **{template['name']}** — deliver "
            f"{format_number(template['amount'])} {template['resource']} for "
            f"🪙 {format_number(template['reward_gold'])}.", ephemeral=True)

    async def _fulfill_first(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        active = list(corp.get("contracts") or [])
        if not active:
            await interaction.followup.send("❌ No active contracts.", ephemeral=True); return
        c = active[0]
        res = c["resource"]; amt = int(c["amount"])
        if res == "soldiers":
            civ = self.cog.civ_manager.get_civilization(self.user_id)
            if civ["military"]["soldiers"] < amt:
                await interaction.followup.send(
                    f"❌ You only have {civ['military']['soldiers']} soldiers.", ephemeral=True); return
            self.cog.civ_manager.update_military(self.user_id, {"soldiers": -amt})
        else:
            if not self.cog.civ_manager.can_afford(self.user_id, {res: amt}):
                await interaction.followup.send(
                    f"❌ You don't have {format_number(amt)} {res}.", ephemeral=True); return
            self.cog.civ_manager.spend_resources(self.user_id, {res: amt})
        active.pop(0)
        reserve = int(corp.get("reserve", 0)) + int(c["reward_gold"])
        rep = min(100, float(corp.get("reputation", 50)) + int(c.get("reward_rep", 0)))
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {
            "contracts": active, "reserve": reserve, "reputation": rep,
        })
        self.cog._push_event(corp, {"type": "positive", "name": "Contract Fulfilled",
                                    "desc": f"{c['name']} — +🪙 {format_number(c['reward_gold'])}"})
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        try:
            await interaction.message.edit(embed=self.make_embed(corp), view=self)
        except Exception:
            pass
        await interaction.followup.send(
            f"✅ Fulfilled **{c['name']}** — earned 🪙 {format_number(c['reward_gold'])}.", ephemeral=True)

    async def _cancel_first(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        active = list(corp.get("contracts") or [])
        if not active:
            await interaction.followup.send("❌ No active contracts.", ephemeral=True); return
        removed = active.pop(0)
        rep = max(0, float(corp.get("reputation", 50)) - 3)
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id,
                                {"contracts": active, "reputation": rep})
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        try:
            await interaction.message.edit(embed=self.make_embed(corp), view=self)
        except Exception:
            pass
        await interaction.followup.send(
            f"❌ Cancelled **{removed['name']}**. Reputation −3.", ephemeral=True)


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

    def make_embed(self, corp):
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
            f"• +1 asset slot\n"
            f"• +1 branch slot (up to level 10)",
            guilded.Color.dark_teal(),
        )

    async def _upgrade(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        level = int(corp.get("level", 1))
        if level >= config.CORP_LIMITS["max_level"]:
            await interaction.followup.send("❌ Already at max level.", ephemeral=True); return
        cost = int(config.CORP_LEVEL_REQUIREMENTS["base_cost"] * (level ** config.CORP_LEVEL_REQUIREMENTS["cost_growth"]))
        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": cost}):
            await interaction.followup.send(f"❌ Need 🪙 {format_number(cost)}.", ephemeral=True); return
        self.cog.civ_manager.spend_resources(self.user_id, {"gold": cost})
        await asyncio.to_thread(self.cog.db.update_corporation, self.corp_id, {"level": level + 1})
        self.cog._push_event(corp, {"type": "positive", "name": "Level Up",
                                    "desc": f"Reached Level {level + 1}"})
        await interaction.followup.send(f"⬆️ Level **{level} → {level+1}**!", ephemeral=True)


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

    async def _confirm(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        corp = await asyncio.to_thread(self.cog.db.get_corporation, self.corp_id)
        if not corp or str(corp.get("owner_id")) != str(self.user_id):
            await interaction.followup.send("Corp no longer exists.", ephemeral=True); return
        self.cog.civ_manager.update_resources(self.user_id, {"gold": self.sale_value})
        await asyncio.to_thread(self.cog.db.delete_corporation, self.corp_id)
        await interaction.followup.send(
            f"✅ Sold **{corp['name']}** for 🪙 {format_number(self.sale_value)}.", ephemeral=True)

    async def _cancel(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.send_message("❌ Cancelled.", ephemeral=True)


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

    async def _attempt(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        if self.attempted:
            await interaction.response.send_message("Already attempted.", ephemeral=True); return
        self.attempted = True
        await interaction.response.defer(ephemeral=True)

        target = await asyncio.to_thread(self.cog.db.get_corporation, self.target["id"])
        if not target or str(target.get("owner_id")) == self.user_id:
            await interaction.followup.send("Corp no longer available.", ephemeral=True); return
        if not self.cog.civ_manager.can_afford(self.user_id, {"gold": self.cost}):
            await interaction.followup.send("❌ Can't afford takeover cost.", ephemeral=True); return

        self.cog.civ_manager.spend_resources(self.user_id, {"gold": self.cost})
        success = self.guaranteed
        if not self.guaranteed and random.random() < 0.40:
            success = True

        if success:
            old_owner = target.get("owner_id")
            await asyncio.to_thread(self.cog.db.update_corporation, target["id"], {
                "owner_id": str(self.user_id),
                "reputation": max(0, int(target.get("reputation", 50)) - 10),
            })
            try:
                old_user = await self.cog.bot.fetch_user(int(old_owner))
                await old_user.send(f"⚔️ **You lost a corporation!** **{target['name']}** was taken over.")
            except Exception:
                pass
            await interaction.followup.send(f"✅ **{target['name']}** is now yours.", ephemeral=True)
        else:
            refund = self.cost // 2
            self.cog.civ_manager.update_resources(self.user_id, {"gold": refund})
            await interaction.followup.send(
                f"❌ Takeover failed. Refunded 🪙 {format_number(refund)}.", ephemeral=True)

    async def _cancel(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not yours.", ephemeral=True); return
        await interaction.response.send_message("❌ Cancelled.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(CorporationsCog(bot))
