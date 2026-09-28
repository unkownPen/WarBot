import os
import random
import re
import json
import logging
import math
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

import aiohttp
import discord as guilded
from discord.ext import commands

from bot.utils import format_number, create_embed
from bot import config

# Territory data (for province capture)
try:
    from bot.commands.territory import (
        PROVINCE_AREAS, PROVINCE_TO_SUBREGION, SUBREGION_DATA,
    )
except Exception:
    PROVINCE_AREAS = {}
    PROVINCE_TO_SUBREGION = {}
    SUBREGION_DATA = {}

logger = logging.getLogger(__name__)

# =====================================================================
# AI KEYS + ENDPOINTS
# =====================================================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL_PRIMARY = "openai/gpt-oss-20b"
AI_MODEL_FALLBACK = "meta-llama/llama-3.3-70b-instruct"

# ---- CONSTANTS ----
SHIP_TYPES = {
    "frigate": {"name": "Frigate", "cost_gold": config.MILITARY["ship_costs"]["frigate"]["gold"], "cost_wood": config.MILITARY["ship_costs"]["frigate"]["wood"], "cost_stone": config.MILITARY["ship_costs"]["frigate"]["stone"], "strength": 10, "counters": [], "weak_against": ["destroyer", "aircraft_carrier"], "description": "Light escort ship."},
    "destroyer": {"name": "Destroyer", "cost_gold": config.MILITARY["ship_costs"]["destroyer"]["gold"], "cost_wood": config.MILITARY["ship_costs"]["destroyer"]["wood"], "cost_stone": config.MILITARY["ship_costs"]["destroyer"]["stone"], "strength": 20, "counters": ["frigate", "submarine"], "weak_against": ["battleship"], "description": "Anti-submarine and anti-aircraft."},
    "battleship": {"name": "Battleship", "cost_gold": config.MILITARY["ship_costs"]["battleship"]["gold"], "cost_wood": config.MILITARY["ship_costs"]["battleship"]["wood"], "cost_stone": config.MILITARY["ship_costs"]["battleship"]["stone"], "strength": 40, "counters": ["destroyer", "submarine"], "weak_against": ["aircraft_carrier"], "description": "Heavily armed."},
    "aircraft_carrier": {"name": "Aircraft Carrier", "cost_gold": config.MILITARY["ship_costs"]["aircraft_carrier"]["gold"], "cost_wood": config.MILITARY["ship_costs"]["aircraft_carrier"]["wood"], "cost_stone": config.MILITARY["ship_costs"]["aircraft_carrier"]["stone"], "strength": 50, "counters": ["frigate", "destroyer", "submarine"], "weak_against": ["battleship"], "description": "Project power."},
    "submarine": {"name": "Submarine", "cost_gold": config.MILITARY["ship_costs"]["submarine"]["gold"], "cost_wood": config.MILITARY["ship_costs"]["submarine"]["wood"], "cost_stone": config.MILITARY["ship_costs"]["submarine"]["stone"], "strength": 15, "counters": ["battleship"], "weak_against": ["destroyer", "aircraft_carrier"], "description": "Stealth."}
}

PLANE_TYPES = {
    "fighter": {"name": "Fighter", "cost_gold": config.MILITARY["plane_costs"]["fighter"]["gold"], "cost_wood": config.MILITARY["plane_costs"]["fighter"]["wood"], "cost_stone": config.MILITARY["plane_costs"]["fighter"]["stone"], "range": 0, "strength": 15, "description": "Short-range air superiority."},
    "attacker": {"name": "Attacker", "cost_gold": config.MILITARY["plane_costs"]["attacker"]["gold"], "cost_wood": config.MILITARY["plane_costs"]["attacker"]["wood"], "cost_stone": config.MILITARY["plane_costs"]["attacker"]["stone"], "range": 1, "strength": 25, "description": "Medium-range ground attack."},
    "bomber": {"name": "Bomber", "cost_gold": config.MILITARY["plane_costs"]["bomber"]["gold"], "cost_wood": config.MILITARY["plane_costs"]["bomber"]["wood"], "cost_stone": config.MILITARY["plane_costs"]["bomber"]["stone"], "range": 2, "strength": 40, "description": "Long-range heavy bomber."}
}

TRAINING_LEVELS = [1.0, 3.0, 10.0, 30.0, 100.0]
TRAINING_LEVEL_NAMES = ["Recruit", "Regular", "Veteran", "Elite", "SUPER ELITE"]
MAX_TRAINING_LEVEL = len(TRAINING_LEVELS) - 1
MAX_BOOSTED_SOLDIERS = 1000

SPY_BUY_COST = 50
DEFAULT_STEALTH_TIMER = 8.0

# =====================================================================
# BANK RAID TUNABLES — skill-driven, no cooldown
# =====================================================================
BANKRAID = {
    "min_spies": 25,
    "min_tech": 3,
    "min_target_deposits": 10_000,
    "min_steal_fraction": 0.05,
    "max_steal_fraction": 0.20,
    "max_steal_absolute": 10_000_000,
    "spy_loss_on_fail_min": 0.10,
    "spy_loss_on_fail_max": 0.45,
    "spy_loss_on_partial_min": 0.02,
    "spy_loss_on_partial_max": 0.15,
    "detection_sanction_hours": 12,
    # AI-rated plan is the *main* driver — stat modifiers are secondary.
    "ai_weight": 0.75,
    "stat_weight": 0.25,
    "min_success": 0.02,
    "max_success": 0.90,
}

# =====================================================================
# PROVINCE CAPTURE TUNABLES
# =====================================================================
PROVINCE_CAPTURE = {
    "enabled": True,
    # No cap. No last-province protection. Defender can be fully conquered.
    "ratio_thresholds": [(6.0, 5), (4.5, 4), (3.0, 3), (2.0, 2), (1.0, 1)],
    "exploitation_bonus": {
        "pursue": 1, "encircle": 2,
        "consolidate": 0, "fortify": 0, "withdraw": -99,
    },
    # ---- Per-province resistance roll ----
    "base_capture_chance": 0.65,
    "defender_doctrine_defense_bonus": {
        "defense_in_depth":   -0.20,
        "superior_firepower": -0.10,
        "grand_battleplan":   -0.05,
        "mobile_warfare":     -0.05,
        "mass_assault":        0.00,
        "asymmetric":          0.05,
    },
    "defender_border_bonus": -0.15,
    "big_ratio_bonus": 0.15,
    "huge_ratio_bonus": 0.25,
    "province_size_penalty": {
        "huge_area_threshold": 2_000_000,
        "large_area_threshold": 1_000_000,
        "huge_penalty": -0.15,
        "large_penalty": -0.08,
    },
    "min_chance": 0.15,
    "max_chance": 0.95,
}

ROLE_BRANCH_SYMBOLS = {
    "infantry":   "o",
    "armor":      "s",
    "artillery":  "P",
    "airborne":   "^",
    "mechanized": "D",
}


# =====================================================================
# STEALTH QUESTION VIEW
# =====================================================================
class StealthQuestionView(guilded.ui.View):
    def __init__(self, user_id: int, question: str, correct: int,
                 choices: List[int], timeout: float = DEFAULT_STEALTH_TIMER):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.correct = correct
        self.answered = False
        self.correct_answer = None
        random.shuffle(choices)
        for choice in choices:
            button = guilded.ui.Button(label=str(choice), style=guilded.ButtonStyle.primary)
            button.callback = self._make_callback(choice)
            self.add_item(button)

    def _make_callback(self, choice):
        async def callback(interaction: guilded.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your mission!", ephemeral=True)
                return
            if self.answered:
                await interaction.response.send_message("Already answered!", ephemeral=True)
                return
            self.answered = True
            self.correct_answer = (choice == self.correct)
            for item in self.children:
                item.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                pass
            self.stop()
        return callback


def _generate_stealth_question() -> Tuple[str, int, List[int]]:
    kind = random.choice(["add", "sub", "mul"])
    if kind == "add":
        a = random.randint(50, 250); b = random.randint(30, 200)
        question = f"What is {a} + {b}?"; correct = a + b
    elif kind == "sub":
        a = random.randint(150, 400); b = random.randint(30, 140)
        question = f"What is {a} - {b}?"; correct = a - b
    else:
        a = random.randint(6, 15); b = random.randint(4, 12)
        question = f"What is {a} × {b}?"; correct = a * b
    choices = {correct}
    while len(choices) < 4:
        offset = random.randint(-20, 20)
        if offset == 0: continue
        candidate = correct + offset
        if candidate <= 0: continue
        choices.add(candidate)
    return question, correct, list(choices)


# =====================================================================
# AI STRATEGY MODAL — tactic panel free-text rating
# =====================================================================
class AITacticModal(guilded.ui.Modal, title="Describe Your Battle Plan"):
    def __init__(self, parent_panel):
        super().__init__()
        self.parent_panel = parent_panel
        self.plan_input = guilded.ui.TextInput(
            label="Your tactical plan",
            style=guilded.TextStyle.paragraph,
            placeholder="e.g. Feint on the left flank, mass breakthrough armor through the "
                        "center at dawn, exploit with paratroopers on the enemy supply depots.",
            min_length=20,
            max_length=500,
            required=True,
        )
        self.add_item(self.plan_input)

    async def on_submit(self, interaction: guilded.Interaction):
        if interaction.user.id != self.parent_panel.user_id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return
        plan_text = str(self.plan_input.value).strip()
        await interaction.response.defer(ephemeral=True)

        rating = await self.parent_panel.cog._ai_rate_tactic(
            plan_text,
            self.parent_panel._build_ai_context(),
        )
        if rating is None:
            await interaction.followup.send(
                "⚠️ AI unavailable. Falling back to a neutral +0% plan rating.",
                ephemeral=True,
            )
            self.parent_panel.ai_plan_score = 0.5
            self.parent_panel.ai_plan_text = plan_text
            self.parent_panel.ai_plan_notes = "AI unavailable."
            return

        self.parent_panel.ai_plan_score = float(rating.get("score", 0.5))
        self.parent_panel.ai_plan_text = plan_text
        self.parent_panel.ai_plan_notes = rating.get("reasoning", "")

        bonus_pct = (self.parent_panel.ai_plan_score - 0.5) * 50  # +/− 25%
        verdict = rating.get("verdict", "—")
        await interaction.followup.send(
            embed=create_embed(
                "🧠 AI Battle Plan Reviewed",
                f"**Score:** {self.parent_panel.ai_plan_score*100:.0f}/100\n"
                f"**Verdict:** {verdict}\n"
                f"**Reasoning:** {rating.get('reasoning','—')}\n"
                f"**Attack modifier:** {bonus_pct:+.1f}%\n\n"
                f"*Applied when you launch.*",
                guilded.Color.purple(),
            ),
            ephemeral=True,
        )


# =====================================================================
# MILITARY COMMANDS
# =====================================================================
class MilitaryCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self.cooldowns = {}
        self.blockades = {}
        self._blockade_cleanup_task = None
        self._bankraid_history: Dict[str, Dict[str, str]] = {}

    async def cog_load(self):
        self._blockade_cleanup_task = asyncio.create_task(self._cleanup_blockades())

    async def cog_unload(self):
        if self._blockade_cleanup_task:
            self._blockade_cleanup_task.cancel()

    async def _cleanup_blockades(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(60)
            now = datetime.utcnow()
            expired = [uid for uid, data in self.blockades.items() if data["expires"] <= now]
            for uid in expired:
                del self.blockades[uid]
                logger.info(f"Blockade against {uid} expired.")

    # =================================================================
    # AI HELPERS
    # =================================================================
    async def _ai_rate_text(self, system_prompt: str, user_prompt: str,
                             max_tokens: int = 400, temperature: float = 0.7) -> Optional[str]:
        """Call Groq (openai/gpt-oss-20b) with OpenRouter fallback.

        Returns the raw assistant text, or None on total failure.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # --- GROQ ---
        if GROQ_API_KEY:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        GROQ_URL,
                        headers={
                            "Authorization": f"Bearer {GROQ_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": AI_MODEL_PRIMARY,
                            "messages": messages,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                        },
                        timeout=30,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            try:
                                return data["choices"][0]["message"]["content"]
                            except (KeyError, IndexError):
                                pass
                        else:
                            txt = await resp.text()
                            logger.warning(f"Groq non-200 ({resp.status}): {txt[:200]}")
            except Exception as e:
                logger.warning(f"Groq request failed: {e}")

        # --- OPENROUTER FALLBACK ---
        if OPENROUTER_KEY:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        OPENROUTER_URL,
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": AI_MODEL_FALLBACK,
                            "messages": messages,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                        },
                        timeout=45,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            try:
                                return data["choices"][0]["message"]["content"]
                            except (KeyError, IndexError):
                                pass
                        else:
                            txt = await resp.text()
                            logger.warning(f"OpenRouter non-200 ({resp.status}): {txt[:200]}")
            except Exception as e:
                logger.warning(f"OpenRouter request failed: {e}")

        return None

    @staticmethod
    def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    async def _ai_rate_tactic(self, plan: str, context: str) -> Optional[Dict[str, Any]]:
        """Rate a battle plan. Returns dict with score (0-1), verdict, reasoning."""
        system = (
            "You are a military strategy evaluator for a civilization game. "
            "Rate the commander's plan strictly and fairly. "
            "Reward: concentration of force, clear sequencing, exploitation, "
            "supply awareness, deception, combined arms. "
            "Penalize: vague goals, contradictions, ignoring enemy strength, "
            "single-axis thinking. "
            "Return ONLY valid JSON, no prose."
        )
        user = (
            f"CONTEXT:\n{context}\n\n"
            f"PLAN:\n\"{plan}\"\n\n"
            "Return JSON with:\n"
            "{\n"
            '  "score": float 0.0-1.0,\n'
            '  "verdict": "one short sentence",\n'
            '  "reasoning": "one sentence citing strengths/weaknesses"\n'
            "}"
        )
        raw = await self._ai_rate_text(system, user, max_tokens=220, temperature=0.5)
        data = self._extract_json_block(raw)
        if not data:
            return None
        try:
            score = float(data.get("score", 0.5))
        except Exception:
            score = 0.5
        data["score"] = max(0.0, min(1.0, score))
        return data

    async def _ai_rate_heist(self, plan: str, context: str) -> Optional[Dict[str, Any]]:
        """Rate a bank heist plan. Higher weight than stats."""
        system = (
            "You are a heist planner rating a bank robbery plan for a strategy game. "
            "Reward: recon, disguises, insider access, staggered entry, emergency exit, "
            "cover-up, distraction, understanding of vault mechanics. "
            "Penalize: brute force, no escape plan, leaving witnesses, vague steps. "
            "Return ONLY valid JSON, no prose."
        )
        user = (
            f"TARGET INTEL:\n{context}\n\n"
            f"PLAN:\n\"{plan}\"\n\n"
            "Return JSON with:\n"
            "{\n"
            '  "score": float 0.0-1.0,\n'
            '  "verdict": "one short phrase",\n'
            '  "reasoning": "one sentence",\n'
            '  "spy_loss_mult": float 0.5-1.5\n'
            "}"
        )
        raw = await self._ai_rate_text(system, user, max_tokens=220, temperature=0.55)
        data = self._extract_json_block(raw)
        if not data:
            return None
        try:
            score = float(data.get("score", 0.5))
        except Exception:
            score = 0.5
        data["score"] = max(0.0, min(1.0, score))
        try:
            slm = float(data.get("spy_loss_mult", 1.0))
        except Exception:
            slm = 1.0
        data["spy_loss_mult"] = max(0.4, min(1.6, slm))
        return data

    # =================================================================
    # FIRESTORE / CIV HELPERS
    # =================================================================
    def _get_navy(self, user_id: str) -> Dict[str, int]:
        return self.db.get_navy(user_id)
    def _update_navy(self, user_id: str, updates: Dict[str, int]) -> bool:
        return self.db.update_navy(user_id, updates)
    def _get_airforce(self, user_id: str) -> Dict[str, int]:
        return self.db.get_airforce(user_id)
    def _update_airforce(self, user_id: str, updates: Dict[str, int]) -> bool:
        return self.db.update_airforce(user_id, updates)
    def _get_military_tech(self, user_id: str) -> Dict[str, int]:
        return self.db.get_military_tech(user_id)
    def _update_military_tech(self, user_id: str, updates: Dict[str, int]) -> bool:
        return self.db.update_military_tech(user_id, updates)
    def _get_training(self, user_id: str) -> Dict[str, int]:
        return self.db.get_training(user_id)
    def _update_training(self, user_id: str, updates: Dict[str, int]) -> bool:
        return self.db.update_training(user_id, updates)

    def _get_border_info(self, user_id: str) -> Dict[str, Any]:
        doc = self.db.client.collection("borders").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            return {
                "has_border": data.get("has_border", False),
                "border_strength": data.get("border_strength", 0),
                "border_soldiers": data.get("border_soldiers", 0),
            }
        return {"has_border": False, "border_strength": 0, "border_soldiers": 0}

    def _update_border(self, user_id: str, updates: Dict[str, Any]) -> bool:
        try:
            doc_ref = self.db.client.collection("borders").document(user_id)
            doc = doc_ref.get()
            if doc.exists:
                current = doc.to_dict()
                for k, v in updates.items():
                    current[k] = v
                doc_ref.set(current)
            else:
                doc_ref.set(updates)
            return True
        except Exception as e:
            logger.error(f"_update_border error for {user_id}: {e}")
            return False

    def _check_war(self, attacker_id: str, defender_id: str) -> bool:
        for war in self.db.get_wars(status="ongoing"):
            a = war.get("attacker_id"); d = war.get("defender_id")
            if (a == attacker_id and d == defender_id) or (a == defender_id and d == attacker_id):
                return True
        return False

    def _do_attackers_border_defender(self, attacker_id: str, defender_id: str) -> bool:
        territory_cog = self.bot.get_cog("TerritoryCog")
        if not territory_cog:
            return False
        attacker_provinces = territory_cog._get_owned_provinces(attacker_id)
        defender_provinces = territory_cog._get_owned_provinces(defender_id)
        if not attacker_provinces or not defender_provinces:
            return False
        try:
            from bot.commands.territory import PROVINCE_TO_SUBREGION as _P2S, SUBREGION_DATA as _SD
        except Exception:
            return False
        attacker_subregions = {_P2S.get(p) for p in attacker_provinces if _P2S.get(p)}
        defender_subregions = {_P2S.get(p) for p in defender_provinces if _P2S.get(p)}
        for att_sub in attacker_subregions:
            for def_sub in defender_subregions:
                if def_sub in _SD.get(att_sub, {}).get("neighbours", []):
                    return True
        return False

    def _has_completed_industrial(self, user_id: str) -> bool:
        data = self.db.get_industrial_revolution(user_id)
        return data and data.get("completed", False) == 1

    def _is_sanctioned(self, user_id: str) -> bool:
        try:
            civ = self.civ_manager.get_civilization(user_id)
            if not civ: return False
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

    def _has_hyperitem(self, user_id: str, item_name: str) -> bool:
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            return False
        return item_name in civ.get('hyper_items', [])

    def _consume_hyperitem(self, user_id: str, item_name: str) -> bool:
        try:
            return self.civ_manager.use_hyper_item(user_id, item_name)
        except Exception:
            return False

    # =================================================================
    # STRENGTH CALCULATIONS
    # =================================================================
    def _calculate_military_strength(self, civ: dict, navy_counts: dict = None,
                                     air_counts: dict = None, training: dict = None) -> float:
        tech = self._get_military_tech(civ['user_id'])
        naval_tech = tech.get("naval_tech", 1)
        air_tech = tech.get("air_tech", 1)

        if training is None:
            training = self._get_training(civ['user_id'])
        training_level = min(training.get("level", 0), MAX_TRAINING_LEVEL)
        multiplier = TRAINING_LEVELS[training_level]

        soldiers = civ['military']['soldiers']
        boosted = min(soldiers, MAX_BOOSTED_SOLDIERS)
        normal = soldiers - boosted
        effective_soldiers = normal + (boosted * multiplier)
        ground_power = effective_soldiers * 10

        spies = civ['military']['spies']
        spy_power = spies * 5

        if navy_counts is None:
            navy_counts = self._get_navy(civ['user_id'])
        navy_power = sum(count * SHIP_TYPES.get(st, {}).get("strength", 0) * naval_tech
                         for st, count in navy_counts.items())

        if air_counts is None:
            air_counts = self._get_airforce(civ['user_id'])
        air_power = sum(count * PLANE_TYPES.get(pt, {}).get("strength", 0) * air_tech
                        for pt, count in air_counts.items())

        territory_bonus = civ['territory']['land_size'] / 10000
        return ground_power + spy_power + navy_power + air_power + territory_bonus

    def _get_naval_strength(self, user_id: str) -> float:
        navy = self._get_navy(user_id); naval_tech = self._get_military_tech(user_id).get("naval_tech", 1)
        return sum(count * SHIP_TYPES.get(st, {}).get("strength", 0) * naval_tech
                   for st, count in navy.items())

    def _get_air_strength(self, user_id: str) -> float:
        air = self._get_airforce(user_id); air_tech = self._get_military_tech(user_id).get("air_tech", 1)
        return sum(count * PLANE_TYPES.get(pt, {}).get("strength", 0) * air_tech
                   for pt, count in air.items())

    # =================================================================
    # COOLDOWN HELPERS
    # =================================================================
    def _check_cooldown(self, user_id: str, command: str, seconds: int) -> bool:
        key = f"{user_id}_{command}"
        return not (key in self.cooldowns and datetime.utcnow() < self.cooldowns[key])

    def _start_cooldown(self, user_id: str, command: str, seconds: int) -> None:
        self.cooldowns[f"{user_id}_{command}"] = datetime.utcnow() + timedelta(seconds=seconds)

    def _get_cooldown_remaining(self, user_id: str, command: str) -> int:
        key = f"{user_id}_{command}"
        if key in self.cooldowns and datetime.utcnow() < self.cooldowns[key]:
            return max(0, int((self.cooldowns[key] - datetime.utcnow()).total_seconds()))
        return 0

    # =================================================================
    # PROVINCE CAPTURE HELPERS
    # =================================================================
    def _get_verified_provinces(self, user_id: str) -> List[str]:
        try:
            all_territories = self.db.get_all_territories()
        except Exception:
            return []
        owned = []
        for province_name, data in all_territories.items():
            if str(data.get("owner_id")) == str(user_id):
                owned.append(province_name)
        return owned

    def _is_rebel_held(self, defender_id: str, province: str) -> bool:
        try:
            state = self.civ_manager.get_civil_war_state(defender_id)
            if not state:
                return False
            return province in set(state.get("rebel_territories", []) or [])
        except Exception:
            return False

    def _sort_provinces_by_adjacency(self, attacker_id: str, provinces: List[str]) -> List[str]:
        if not provinces:
            return []
        attacker_provs = self._get_verified_provinces(attacker_id)
        attacker_subregions = {
            PROVINCE_TO_SUBREGION.get(p) for p in attacker_provs
            if PROVINCE_TO_SUBREGION.get(p)
        }
        adjacent_subregions: set = set()
        for sub in attacker_subregions:
            for nb in SUBREGION_DATA.get(sub, {}).get("neighbours", []):
                adjacent_subregions.add(nb)

        tier1, tier2, tier3 = [], [], []
        for prov in provinces:
            sub = PROVINCE_TO_SUBREGION.get(prov)
            if sub in attacker_subregions:
                tier1.append(prov)
            elif sub in adjacent_subregions:
                tier2.append(prov)
            else:
                tier3.append(prov)

        random.shuffle(tier1); random.shuffle(tier2); random.shuffle(tier3)
        return tier1 + tier2 + tier3

    def _calculate_capture_count(self, ratio: float, exploitation: Optional[str]) -> int:
        """How many provinces can the attacker seize this battle? No cap."""
        if not PROVINCE_CAPTURE["enabled"]:
            return 0
        bonus = PROVINCE_CAPTURE["exploitation_bonus"].get(exploitation or "", 0)
        if bonus < 0:
            return 0

        base = 0
        for threshold, count in PROVINCE_CAPTURE["ratio_thresholds"]:
            if ratio >= threshold:
                base = count
                break
        if base == 0:
            return 0

        return max(0, base + bonus)

    def _get_capturable_provinces(self, attacker_id: str, defender_id: str) -> List[str]:
        defender_provs = self._get_verified_provinces(defender_id)
        if not defender_provs:
            return []
        # Civil war: exclude rebel-held provinces
        defender_provs = [p for p in defender_provs
                          if not self._is_rebel_held(defender_id, p)]
        # Exclude anything attacker already owns (paranoia)
        attacker_owned = set(self._get_verified_provinces(attacker_id))
        defender_provs = [p for p in defender_provs if p not in attacker_owned]
        return defender_provs

    def _roll_capture(self, ratio: float, defender_doctrine: Optional[str],
                      defender_id: str, province: str) -> bool:
        """Per-province resistance roll."""
        chance = PROVINCE_CAPTURE["base_capture_chance"]
        chance += PROVINCE_CAPTURE["defender_doctrine_defense_bonus"].get(
            defender_doctrine or "", 0.0
        )
        border = self._get_border_info(defender_id)
        if border.get("has_border"):
            chance += PROVINCE_CAPTURE["defender_border_bonus"]
        if ratio >= 5.0:
            chance += PROVINCE_CAPTURE["huge_ratio_bonus"]
        elif ratio >= 3.0:
            chance += PROVINCE_CAPTURE["big_ratio_bonus"]

        area = int(PROVINCE_AREAS.get(province, 1000))
        psp = PROVINCE_CAPTURE["province_size_penalty"]
        if area >= psp["huge_area_threshold"]:
            chance += psp["huge_penalty"]
        elif area >= psp["large_area_threshold"]:
            chance += psp["large_penalty"]

        chance = max(PROVINCE_CAPTURE["min_chance"],
                     min(PROVINCE_CAPTURE["max_chance"], chance))
        return random.random() < chance

    def _transfer_province(self, attacker_id: str, defender_id: str, province: str) -> bool:
        try:
            ok = self.db.conquer_territory(attacker_id, defender_id, province)
            if not ok:
                return False
            area = int(PROVINCE_AREAS.get(province, 1000))
            self.civ_manager.update_territory(attacker_id, {"land_size": area})
            self.civ_manager.update_territory(defender_id, {"land_size": -area})
            try:
                self.civ_manager._invalidate_civ(attacker_id)
                self.civ_manager._invalidate_civ(defender_id)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"_transfer_province error {province}: {e}")
            return False

    async def _capture_provinces(self, ctx, attacker_id: str, defender_id: str,
                                  ratio: float, exploitation: Optional[str],
                                  attacker_civ: dict, defender_civ: dict) -> List[str]:
        count = self._calculate_capture_count(ratio, exploitation)
        if count <= 0:
            return []

        candidates = self._get_capturable_provinces(attacker_id, defender_id)
        if not candidates:
            return []

        candidates = self._sort_provinces_by_adjacency(attacker_id, candidates)
        targets = candidates[:count]
        defender_doctrine = defender_civ.get("doctrine")

        captured, resisted = [], []
        for prov in targets:
            if self._roll_capture(ratio, defender_doctrine, defender_id, prov):
                if self._transfer_province(attacker_id, defender_id, prov):
                    captured.append(prov)
                else:
                    resisted.append(prov)
            else:
                resisted.append(prov)

        if not captured and not resisted:
            return []

        embed = create_embed(
            "🏴 Territory Resolution",
            f"**{attacker_civ['name']}** vs **{defender_civ['name']}**",
            guilded.Color.dark_gold() if captured else guilded.Color.dark_red(),
        )
        if captured:
            embed.add_field(
                name=f"✅ Captured ({len(captured)})",
                value="\n".join(f"• 🏴 **{p}**" for p in captured),
                inline=False,
            )
        if resisted:
            embed.add_field(
                name=f"🛡️ Held by Defender ({len(resisted)})",
                value="\n".join(f"• **{p}** — garrison held" for p in resisted),
                inline=False,
            )
        embed.set_footer(text=f"Battle ratio ×{ratio:.2f}  ·  Exploitation: {exploitation or 'none'}")
        await ctx.send(embed=embed)

        if captured:
            try:
                self.db.log_event(attacker_id, "province_capture", "Provinces Captured",
                                  f"Took {', '.join(captured)} from {defender_civ['name']}.")
                self.db.log_event(defender_id, "province_lost", "Provinces Lost",
                                  f"Lost {', '.join(captured)} to {attacker_civ['name']}.")
            except Exception:
                pass
            try:
                tu = await self.bot.fetch_user(int(defender_id))
                await tu.send(f"🏴 **You lost territory!** {attacker_civ['name']} captured: "
                              f"{', '.join(captured)}")
            except Exception:
                pass
            try:
                self.civ_manager.apply_faction_effects(attacker_id, "reclaim_win")
                self.civ_manager.apply_faction_effects(defender_id, "lost_province")
            except Exception:
                pass

        return captured

    # =================================================================
    # CIVIL WAR GATE
    # =================================================================
    async def check_civil_war_and_proceed(self, ctx, user_id: str) -> bool:
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
            cause_label = {"military": "the armed forces", "merchant": "the merchant guilds",
                           "people": "the common people"}.get(cause, "rebels")
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
            return False
        except Exception as e:
            logger.error(f"Error checking civil war for {user_id}: {e}")
            return True

    # =================================================================
    # DOCTRINE
    # =================================================================
    @commands.command(name='doctrine')
    async def doctrine_cmd(self, ctx, doctrine_name: str = None):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        current = civ.get("doctrine")

        if not doctrine_name:
            embed = create_embed(
                "📖 Operational Doctrine",
                f"**Current:** {config.DOCTRINES[current]['emoji']} **{config.DOCTRINES[current]['name']}**"
                if current else "**Current:** *None selected*",
                guilded.Color.dark_blue()
            )
            for key, d in config.DOCTRINES.items():
                marker = "✅ " if key == current else ""
                embed.add_field(
                    name=f"{marker}{d['emoji']} {d['name']}",
                    value=(f"*{d['desc']}*\n"
                           f"ATK ×{d['attack_mult']} | DEF ×{d['defense_mult']} | "
                           f"MOB ×{d['mobility_mult']} | SUP ×{d['supply_mult']} | "
                           f"CAS ×{d['casualty_mult']}\n"
                           f"Roles: {len(d['allowed_roles'])} | Instructions: {len(d['allowed_instructions'])}"),
                    inline=False
                )
            embed.set_footer(text=f"Switch cost: {config.DOCTRINE_SWITCH_COST:,} gold")
            await ctx.send(embed=embed)
            return

        doctrine_name = doctrine_name.lower().strip()
        if doctrine_name not in config.DOCTRINES:
            await ctx.send(f"❌ Unknown doctrine. Options: {', '.join(config.DOCTRINES.keys())}")
            return
        if current == doctrine_name:
            await ctx.send(f"✅ You already follow **{config.DOCTRINES[current]['name']}**.")
            return
        if current is not None:
            cost = config.DOCTRINE_SWITCH_COST
            if not self.civ_manager.can_afford(user_id, {"gold": cost}):
                await ctx.send(f"❌ Switching costs **{cost:,} gold**. You don't have enough.")
                return
            self.civ_manager.spend_resources(user_id, {"gold": cost})

        self.db.update_civilization(user_id, {"doctrine": doctrine_name})
        self.civ_manager._invalidate_civ(user_id)
        d = config.DOCTRINES[doctrine_name]
        embed = create_embed(
            f"{d['emoji']} Doctrine Adopted — {d['name']}",
            f"*{d['desc']}*\n\n"
            f"**Stat multipliers:**\n"
            f"ATK ×{d['attack_mult']} | DEF ×{d['defense_mult']}\n"
            f"MOB ×{d['mobility_mult']} | SUP ×{d['supply_mult']} | CAS ×{d['casualty_mult']}\n\n"
            f"**Available roles:** {', '.join(config.DIVISION_ROLES[r]['name'] for r in d['allowed_roles'] if r in config.DIVISION_ROLES)}",
            guilded.Color.gold()
        )
        await ctx.send(embed=embed)

    # =================================================================
    # DIVISIONS
    # =================================================================
    def _division_cap_reached(self, user_id: str) -> bool:
        try:
            return self.db.count_user_divisions(user_id) >= config.DIVISION_LIMITS["max_per_user"]
        except Exception:
            return True

    def _division_size_ok(self, size: int) -> Tuple[bool, str]:
        lim = config.DIVISION_LIMITS
        if size < lim["min_size"]:
            return False, f"Minimum size is **{lim['min_size']:,}** soldiers."
        if size > lim["max_size"]:
            return False, f"Maximum size is **{lim['max_size']:,}** soldiers."
        return True, ""

    @commands.command(name='createdivision', aliases=['cd', 'mkdiv'])
    async def create_division_cmd(self, ctx, role: str = None, size: int = None, *, name: str = None):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        doctrine = civ.get("doctrine")
        if not doctrine:
            await ctx.send("❌ You must pick a doctrine first: `.doctrine <name>`")
            return
        allowed = config.DOCTRINES[doctrine]["allowed_roles"]
        if not role or size is None or not name:
            role_lines = []
            for k in allowed:
                r = config.DIVISION_ROLES.get(k)
                if not r: continue
                role_lines.append(f"`{k}` — {r['name']} ({r['cost_gold']}g/{r['cost_food']}f) — {r['desc']}")
            await ctx.send(
                f"⚔️ **Create Division** — doctrine: {config.DOCTRINES[doctrine]['emoji']} "
                f"**{config.DOCTRINES[doctrine]['name']}**\n"
                f"Usage: `.createdivision <role> <size> <name>`\n"
                f"Example: `.createdivision line_infantry 5000 1st Rifles`\n\n"
                f"**Allowed roles:**\n" + "\n".join(role_lines)
            )
            return
        role = role.lower()
        if role not in config.DIVISION_ROLES:
            await ctx.send(f"❌ Unknown role. Options: {', '.join(config.DIVISION_ROLES.keys())}")
            return
        if role not in allowed:
            await ctx.send(
                f"❌ Your doctrine **{config.DOCTRINES[doctrine]['name']}** does not permit "
                f"**{config.DIVISION_ROLES[role]['name']}**."
            )
            return
        ok, msg = self._division_size_ok(size)
        if not ok:
            await ctx.send(f"❌ {msg}")
            return
        name = name.strip()
        lim = config.DIVISION_LIMITS
        if not (lim["min_name_length"] <= len(name) <= lim["max_name_length"]):
            await ctx.send(f"❌ Name must be {lim['min_name_length']}–{lim['max_name_length']} chars.")
            return
        if self._division_cap_reached(user_id):
            await ctx.send(f"❌ You already have {config.DIVISION_LIMITS['max_per_user']} divisions.")
            return
        if civ['military']['soldiers'] < size:
            await ctx.send(f"❌ You only have {format_number(civ['military']['soldiers'])} soldiers.")
            return
        r = config.DIVISION_ROLES[role]
        gold_cost = size * r["cost_gold"]
        food_cost = size * r["cost_food"]
        if not self.civ_manager.can_afford(user_id, {"gold": gold_cost, "food": food_cost}):
            await ctx.send(f"❌ Need 🪙 {format_number(gold_cost)} gold and 🌾 {format_number(food_cost)} food.")
            return
        owned = self.db.get_player_territories(user_id)
        if not owned:
            await ctx.send("❌ You need at least one province to station a division.")
            return
        location = owned[0]
        self.civ_manager.spend_resources(user_id, {"gold": gold_cost, "food": food_cost})
        self.civ_manager.update_military(user_id, {"soldiers": -size})
        division_id = self.db.create_division(user_id, name, role, size, location)
        if not division_id:
            self.civ_manager.update_resources(user_id, {"gold": gold_cost, "food": food_cost})
            self.civ_manager.update_military(user_id, {"soldiers": size})
            await ctx.send("❌ Failed to create division.")
            return
        self.civ_manager.apply_faction_effects(user_id, "train_soldiers")
        embed = create_embed(f"⚔️ Division Formed — {name}",
                             f"**{name}** ({r['name']}) is ready.",
                             guilded.Color.green())
        embed.add_field(name="Size", value=f"👥 {format_number(size)}", inline=True)
        embed.add_field(name="Stationed", value=location, inline=True)
        embed.add_field(name="Cost", value=f"🪙 {format_number(gold_cost)}\n🌾 {format_number(food_cost)}", inline=True)
        embed.add_field(name="Division ID", value=f"`{division_id}`", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='divisions', aliases=['mydivisions'])
    async def list_divisions_cmd(self, ctx, target: guilded.Member = None):
        user_id = str(target.id) if target else str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ That user has no civilization.")
            return
        divisions = self.db.get_user_divisions(user_id)
        if not divisions:
            await ctx.send(f"📭 **{civ['name']}** has no divisions.")
            return
        embed = create_embed(f"⚔️ Divisions of {civ['name']}",
                             f"Total: {len(divisions)} / {config.DIVISION_LIMITS['max_per_user']}",
                             guilded.Color.dark_red())
        for d in divisions:
            role_key = d.get("type", "")
            r = config.DIVISION_ROLES.get(role_key, {})
            general = ""
            if d.get("general_id"):
                g = self.db.get_general(d["general_id"])
                if g: general = f"\n🎖️ {g['name']}"
            embed.add_field(
                name=f"{r.get('symbol','⚔')} {d['name']}",
                value=(f"**Role:** {r.get('name','Unknown')}\n"
                       f"**Size:** {format_number(d.get('size', 0))}\n"
                       f"**Location:** {d.get('location','?')}\n"
                       f"**Morale:** {d.get('morale', 100)} | "
                       f"**Vet:** {d.get('veterancy','green')}"
                       f"{general}"),
                inline=True
            )
        await ctx.send(embed=embed)

    @commands.command(name='deletedivision', aliases=['rmdiv'])
    async def delete_division_cmd(self, ctx, *, name_or_id: str = None):
        if not name_or_id:
            await ctx.send("Usage: `.deletedivision <name or id>`")
            return
        user_id = str(ctx.author.id)
        division = self._find_division(user_id, name_or_id)
        if not division:
            await ctx.send("❌ Division not found.")
            return
        await ctx.send(f"⚠️ Disbanding **{division['name']}**. Type `confirm` within 30s.")
        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.strip().lower() == "confirm"
        try:
            await self.bot.wait_for("message", timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send("❌ Cancelled.")
            return
        if self.db.delete_division(division["id"]):
            await ctx.send(f"🗑️ **{division['name']}** disbanded.")
        else:
            await ctx.send("❌ Failed.")

    @commands.command(name='renamedivision', aliases=['rndiv'])
    async def rename_division_cmd(self, ctx, name_or_id: str = None, *, new_name: str = None):
        if not name_or_id or not new_name:
            await ctx.send("Usage: `.renamedivision <name or id> <new name>`")
            return
        user_id = str(ctx.author.id)
        division = self._find_division(user_id, name_or_id)
        if not division:
            await ctx.send("❌ Division not found.")
            return
        new_name = new_name.strip()
        lim = config.DIVISION_LIMITS
        if not (lim["min_name_length"] <= len(new_name) <= lim["max_name_length"]):
            await ctx.send(f"❌ Name must be {lim['min_name_length']}–{lim['max_name_length']} chars.")
            return
        if self.db.rename_division(division["id"], new_name):
            await ctx.send(f"✏️ Renamed to **{new_name}**.")

    @commands.command(name='movedivision', aliases=['mvdiv'])
    async def move_division_cmd(self, ctx, name_or_id: str = None, *, province: str = None):
        if not name_or_id or not province:
            await ctx.send("Usage: `.movedivision <name or id> <province>`")
            return
        user_id = str(ctx.author.id)
        division = self._find_division(user_id, name_or_id)
        if not division:
            await ctx.send("❌ Division not found.")
            return
        owned = self.db.get_player_territories(user_id)
        matched = next((p for p in owned if p.lower() == province.strip().lower()), None) \
                  or next((p for p in owned if province.strip().lower() in p.lower()), None)
        if not matched:
            await ctx.send(f"❌ You don't own a province matching `{province}`.")
            return
        if self.db.move_division(division["id"], matched):
            await ctx.send(f"🚚 **{division['name']}** moved to **{matched}**.")

    def _find_division(self, user_id: str, name_or_id: str) -> Optional[Dict[str, Any]]:
        name_or_id = (name_or_id or "").strip()
        divisions = self.db.get_user_divisions(user_id)
        for d in divisions:
            if d["id"] == name_or_id: return d
        for d in divisions:
            if d["name"].lower() == name_or_id.lower(): return d
        for d in divisions:
            if name_or_id.lower() in d["name"].lower(): return d
        return None

    # =================================================================
    # GENERALS
    # =================================================================
    def _general_cap_reached(self, user_id: str) -> bool:
        try:
            return self.db.count_user_generals(user_id) >= config.GENERAL_LIMITS["max_per_user"]
        except Exception:
            return True

    @commands.command(name='creategeneral', aliases=['mkgen'])
    async def create_general_cmd(self, ctx, *, name: str = None):
        if not name:
            await ctx.send(f"🎖️ **Create General**\nUsage: `.creategeneral <name>`")
            return
        user_id = str(ctx.author.id)
        if not self.civ_manager.get_civilization(user_id):
            await ctx.send("❌ You need a civilization first!")
            return
        name = name.strip()
        lim = config.GENERAL_LIMITS
        if not (lim["min_name_length"] <= len(name) <= lim["max_name_length"]):
            await ctx.send(f"❌ Name must be {lim['min_name_length']}–{lim['max_name_length']} chars.")
            return
        if self._general_cap_reached(user_id):
            await ctx.send(f"❌ You already have {lim['max_per_user']} generals.")
            return
        pos_key = random.choice(list(config.GENERAL_POSITIVE_TRAITS.keys()))
        neg_key = random.choice(list(config.GENERAL_NEGATIVE_TRAITS.keys()))
        tech_key = random.choice(list(config.TECHNIQUES.keys()))
        general_id = self.db.create_general(user_id, name, pos_key, neg_key, tech_key)
        if not general_id:
            await ctx.send("❌ Failed to create general.")
            return
        pos = config.GENERAL_POSITIVE_TRAITS[pos_key]
        neg = config.GENERAL_NEGATIVE_TRAITS[neg_key]
        tech = config.TECHNIQUES[tech_key]
        embed = create_embed(f"🎖️ General Commissioned — {name}",
                             "A new commander joins your staff.", guilded.Color.gold())
        embed.add_field(name=f"✅ {pos['name']}", value=pos["description"], inline=False)
        embed.add_field(name=f"⚠️ {neg['name']}", value=neg["description"], inline=False)
        embed.add_field(name=f"🎯 Preferred: {tech['emoji']} {tech['name']}",
                        value=tech["desc"], inline=False)
        embed.add_field(name="General ID", value=f"`{general_id}`", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='generals')
    async def list_generals_cmd(self, ctx, target: guilded.Member = None):
        user_id = str(target.id) if target else str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ That user has no civilization.")
            return
        generals = self.db.get_user_generals(user_id)
        if not generals:
            await ctx.send(f"📭 **{civ['name']}** has no generals.")
            return
        embed = create_embed(f"🎖️ Generals of {civ['name']}",
                             f"Total: {len(generals)} / {config.GENERAL_LIMITS['max_per_user']}",
                             guilded.Color.gold())
        for g in generals:
            pos = config.GENERAL_POSITIVE_TRAITS.get(g.get("positive_trait"), {})
            neg = config.GENERAL_NEGATIVE_TRAITS.get(g.get("negative_trait"), {})
            tech = config.TECHNIQUES.get(g.get("preferred_technique"), {})
            embed.add_field(
                name=f"🎖️ {g['name']} (Rank {g.get('rank',1)})",
                value=(f"✅ {pos.get('name','?')} · ⚠️ {neg.get('name','?')}\n"
                       f"🎯 {tech.get('emoji','')} {tech.get('name','?')}\n"
                       f"🏆 {g.get('battles_won',0)}W / 💀 {g.get('battles_lost',0)}L"),
                inline=True
            )
        await ctx.send(embed=embed)

    @commands.command(name='deletegeneral', aliases=['rmgen'])
    async def delete_general_cmd(self, ctx, *, name_or_id: str = None):
        if not name_or_id:
            await ctx.send("Usage: `.deletegeneral <name or id>`")
            return
        user_id = str(ctx.author.id)
        general = self._find_general(user_id, name_or_id)
        if not general:
            await ctx.send("❌ General not found.")
            return
        if self.db.delete_general(general["id"]):
            await ctx.send(f"🗑️ General **{general['name']}** dismissed.")

    @commands.command(name='assigngeneral', aliases=['assigngen'])
    async def assign_general_cmd(self, ctx, general_name: str = None, *, division_name: str = None):
        if not general_name or not division_name:
            await ctx.send("Usage: `.assigngeneral <general> <division>`")
            return
        user_id = str(ctx.author.id)
        general = self._find_general(user_id, general_name)
        division = self._find_division(user_id, division_name)
        if not general or not division:
            await ctx.send("❌ General or division not found.")
            return
        if self.db.assign_general_to_division(division["id"], general["id"]):
            await ctx.send(f"🎖️ **{general['name']}** now commands **{division['name']}**.")

    @commands.command(name='unassigngeneral', aliases=['unassigngen'])
    async def unassign_general_cmd(self, ctx, *, division_name: str = None):
        if not division_name:
            await ctx.send("Usage: `.unassigngeneral <division>`")
            return
        user_id = str(ctx.author.id)
        division = self._find_division(user_id, division_name)
        if not division or not division.get("general_id"):
            await ctx.send("❌ No general assigned to that division.")
            return
        if self.db.unassign_general(division["id"]):
            await ctx.send(f"🎖️ General removed from **{division['name']}**.")

    def _find_general(self, user_id: str, name_or_id: str) -> Optional[Dict[str, Any]]:
        name_or_id = (name_or_id or "").strip()
        generals = self.db.get_user_generals(user_id)
        for g in generals:
            if g["id"] == name_or_id: return g
        for g in generals:
            if g["name"].lower() == name_or_id.lower(): return g
        for g in generals:
            if name_or_id.lower() in g["name"].lower(): return g
        return None

    # =================================================================
    # TRAIN / TECH
    # =================================================================
    @commands.command(name='train')
    async def train_soldiers(self, ctx, unit_type: str = None, amount: int = None):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("train", 2) * 60
            if not self._check_cooldown(user_id, 'train', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'train')
                await ctx.send(f"⏳ Wait {remaining // 60}m {remaining % 60}s.")
                return
            if not unit_type:
                embed = create_embed("⚔️ Military Training", "Train units!", guilded.Color.blue())
                embed.add_field(name="Available",
                                value=f"`soldiers` ({config.MILITARY['train_cost_soldier_gold']}g, {config.MILITARY['train_cost_soldier_food']}f each)\n"
                                      f"`spies` ({config.MILITARY['train_cost_spy_gold']}g, {config.MILITARY['train_cost_spy_food']}f each)")
                await ctx.send(embed=embed)
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                await ctx.send("❌ Need a civilization.")
                return
            unit_type = unit_type.lower()
            if unit_type not in ('soldiers', 'spies') or amount is None or amount < 1:
                await ctx.send("❌ Use `soldiers` or `spies`, amount ≥ 1.")
                return
            if unit_type == 'soldiers':
                gold_cost = amount * config.MILITARY['train_cost_soldier_gold']
                food_cost = amount * config.MILITARY['train_cost_soldier_food']
            else:
                gold_cost = amount * config.MILITARY['train_cost_spy_gold']
                food_cost = amount * config.MILITARY['train_cost_spy_food']
            if not self.civ_manager.can_afford(user_id, {"gold": gold_cost, "food": food_cost}):
                await ctx.send(f"❌ Need 🪙 {format_number(gold_cost)} / 🌾 {format_number(food_cost)}.")
                return
            self._start_cooldown(user_id, 'train', cooldown_seconds)
            mod = self.civ_manager.get_ideology_modifier(user_id, "soldier_training_speed")
            bonus_units = penalty_units = 0
            if mod > 1.0 and random.random() < (mod - 1.0) * 0.5:
                bonus_units = max(1, amount // 10); amount += bonus_units
            elif mod < 1.0 and random.random() < (1.0 - mod) * 0.5:
                penalty_units = max(1, amount // 10); amount = max(1, amount - penalty_units)
            self.civ_manager.spend_resources(user_id, {"gold": gold_cost, "food": food_cost})
            self.civ_manager.update_military(user_id, {unit_type: amount})
            self.civ_manager.apply_faction_effects(user_id, "train_soldiers" if unit_type == 'soldiers' else "train_spies")
            embed = create_embed("⚔️ Training Complete",
                                 f"Trained {format_number(amount)} {unit_type}.",
                                 guilded.Color.green())
            embed.add_field(name="Cost", value=f"🪙 {format_number(gold_cost)}\n🌾 {format_number(food_cost)}", inline=True)
            if bonus_units: embed.add_field(name="Bonus", value=f"+{bonus_units}", inline=True)
            if penalty_units: embed.add_field(name="Penalty", value=f"-{penalty_units}", inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"train error: {e}", exc_info=True)

    @commands.command(name='trainboost')
    async def train_boost(self, ctx, amount: int = 1):
        try:
            user_id = str(ctx.author.id)
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                await ctx.send("❌ Need a civilization.")
                return
            t = self._get_training(user_id)
            cur = t.get("level", 0)
            if cur >= MAX_TRAINING_LEVEL:
                await ctx.send(f"❌ Max training level ({TRAINING_LEVEL_NAMES[MAX_TRAINING_LEVEL]}).")
                return
            new = min(cur + amount, MAX_TRAINING_LEVEL)
            inc = new - cur
            if inc <= 0:
                await ctx.send("❌ Already maxed.")
                return
            cost = config.MILITARY['tech_upgrade_cost'] * [1, 5, 25, 100, 500][new] * inc
            if not self.civ_manager.can_afford(user_id, {"gold": cost}):
                await ctx.send(f"❌ Need {format_number(cost)} gold.")
                return
            self.civ_manager.spend_resources(user_id, {"gold": cost})
            self._update_training(user_id, {"level": inc})
            embed = create_embed("⚔️ Training Level Up",
                                 f"**{TRAINING_LEVEL_NAMES[cur]}** → **{TRAINING_LEVEL_NAMES[new]}**\n"
                                 f"Multiplier: **{TRAINING_LEVELS[cur]}x → {TRAINING_LEVELS[new]}x**",
                                 guilded.Color.gold())
            if new == MAX_TRAINING_LEVEL:
                embed.add_field(name="🏆 SUPER ELITE",
                                value=f"1 soldier fights as {TRAINING_LEVELS[new]:.0f}.", inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"trainboost error: {e}", exc_info=True)

    @commands.command(name='tech')
    async def upgrade_tech(self, ctx, branch: str = None, amount: int = 1):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        if not branch:
            embed = create_embed("🔬 Tech Upgrade",
                                 f"{config.MILITARY['tech_upgrade_cost']} gold per level.",
                                 guilded.Color.blue())
            embed.add_field(name="Branches", value="`ground` / `naval` / `air` / `status`", inline=False)
            await ctx.send(embed=embed)
            return
        if branch == "status":
            t = self._get_military_tech(user_id)
            await ctx.send(embed=create_embed("🔬 Tech",
                                              f"Ground: **{t['ground_tech']}**\n"
                                              f"Naval: **{t['naval_tech']}**\n"
                                              f"Air: **{t['air_tech']}**",
                                              guilded.Color.blue()))
            return
        if branch not in ("ground", "naval", "air"):
            await ctx.send("❌ Choose ground / naval / air.")
            return
        t = self._get_military_tech(user_id)
        cur = t.get(f"{branch}_tech", 1)
        if cur + amount > 10:
            await ctx.send("❌ Tech cap is 10.")
            return
        cost = config.MILITARY['tech_upgrade_cost'] * amount
        if not self.civ_manager.can_afford(user_id, {"gold": cost}):
            await ctx.send(f"❌ Need {format_number(cost)} gold.")
            return
        self.civ_manager.spend_resources(user_id, {"gold": cost})
        self._update_military_tech(user_id, {f"{branch}_tech": amount})
        await ctx.send(f"🔬 {branch.capitalize()} tech {cur} → {cur + amount}.")

    # =================================================================
    # DECLARE WAR
    # =================================================================
    @commands.command(name='declare')
    async def declare_war(self, ctx, target: guilded.Member = None):
        try:
            if not target:
                await ctx.send("⚔️ Usage: `.declare <user>`")
                return
            user_id = str(ctx.author.id)
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                await ctx.send("❌ Need a civilization.")
                return
            target_id = str(target.id)
            if target_id == user_id:
                await ctx.send("❌ Can't declare war on yourself.")
                return
            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target has no civilization.")
                return
            if self._check_war(user_id, target_id):
                await ctx.send("❌ Already at war.")
                return
            self.db.declare_war(user_id, target_id, "declared")
            self.db.log_event(user_id, "war_declaration", "War Declared",
                              f"{civ['name']} → {target_civ['name']}")
            self.civ_manager.apply_faction_effects(user_id, "declare_war")
            embed = create_embed("⚔️ War Declared!",
                                 f"**{civ['name']}** has declared war on **{target_civ['name']}**!",
                                 guilded.Color.red())
            embed.add_field(name="Next", value="Use `.tactics @user` to plan your offensive.", inline=False)
            await ctx.send(embed=embed)
            try:
                await ctx.send(f"{target.mention} ⚔️ **WAR DECLARED!** {civ['name']} (by {ctx.author.display_name}) has declared war on you!")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"declare error: {e}", exc_info=True)

    # =================================================================
    # TACTICS PANEL
    # =================================================================
    class TacticsPanelView(guilded.ui.View):
        def __init__(self, cog, ctx, attacker_id: str, defender_id: str, timeout: float = 300.0):
            super().__init__(timeout=timeout)
            self.cog = cog
            self.bot = cog.bot
            self.ctx = ctx
            self.attacker_id = attacker_id
            self.defender_id = defender_id
            self.user_id = int(attacker_id)

            self.direction: Optional[str] = None
            self.mentality: Optional[str] = None
            self.technique: Optional[str] = None
            self.divisions: List[str] = []

            self.general_id: Optional[str] = None
            self.instructions: List[str] = []
            self.phase_opening: Optional[str] = None
            self.phase_main: Optional[str] = None
            self.phase_exploitation: Optional[str] = None

            # AI tactic fields (new)
            self.ai_plan_score: Optional[float] = None
            self.ai_plan_text: Optional[str] = None
            self.ai_plan_notes: Optional[str] = None

            civ = cog.civ_manager.get_civilization(attacker_id)
            self.doctrine = (civ or {}).get("doctrine")
            self.divisions_owned = cog.db.get_user_divisions(attacker_id)

            self._build_selects()

        def _build_ai_context(self) -> str:
            civ = self.cog.civ_manager.get_civilization(self.attacker_id)
            target_civ = self.cog.civ_manager.get_civilization(self.defender_id)
            if not civ or not target_civ:
                return "No context available."
            return (
                f"Attacker: {civ.get('name','?')} "
                f"(soldiers {civ['military'].get('soldiers',0):,}, "
                f"spies {civ['military'].get('spies',0):,}, "
                f"tech {civ['military'].get('tech_level',0)})\n"
                f"Defender: {target_civ.get('name','?')} "
                f"(soldiers {target_civ['military'].get('soldiers',0):,}, "
                f"spies {target_civ['military'].get('spies',0):,}, "
                f"tech {target_civ['military'].get('tech_level',0)})\n"
                f"Attacker doctrine: {self.doctrine or 'none'}\n"
                f"Defender doctrine: {target_civ.get('doctrine') or 'none'}\n"
                f"Chosen direction: {self.direction or 'unset'}\n"
                f"Chosen technique: {self.technique or 'unset'}\n"
                f"Chosen mentality: {self.mentality or 'unset'}\n"
                f"Divisions committed: {len(self.divisions)}"
            )

        def _build_selects(self):
            dir_options = [
                guilded.SelectOption(
                    label=f"{d['emoji']} {d['name']}",
                    value=k,
                    description=f"Attack from the {d['name'].lower()}"
                )
                for k, d in config.ATTACK_DIRECTIONS.items()
            ]
            self.direction_select = guilded.ui.Select(
                placeholder="📍 Direction of attack",
                options=dir_options, row=0,
            )
            self.direction_select.callback = self._on_direction
            self.add_item(self.direction_select)

            ment_options = [
                guilded.SelectOption(
                    label=f"{m['emoji']} {m['name']}",
                    value=k, description=m['desc']
                )
                for k, m in config.MENTALITIES.items()
            ]
            self.mentality_select = guilded.ui.Select(
                placeholder="🧠 Mentality",
                options=ment_options, row=1,
            )
            self.mentality_select.callback = self._on_mentality
            self.add_item(self.mentality_select)

            tech_options = []
            for tk, t in config.TECHNIQUES.items():
                if self.doctrine and tk in config.TECHNIQUES:
                    if self.doctrine in t.get("doctrines", []):
                        tech_options.append(guilded.SelectOption(
                            label=f"{t['emoji']} {t['name']}",
                            value=tk, description=t['desc'][:100],
                        ))
            if not tech_options:
                tech_options = [guilded.SelectOption(label="No techniques available", value="_none")]
            self.technique_select = guilded.ui.Select(
                placeholder="🎯 Technique",
                options=tech_options[:25], row=2,
            )
            self.technique_select.callback = self._on_technique
            self.add_item(self.technique_select)

            div_options = []
            for d in self.divisions_owned[:25]:
                role = config.DIVISION_ROLES.get(d.get("type", ""), {})
                div_options.append(guilded.SelectOption(
                    label=f"{role.get('symbol','⚔')} {d['name']}",
                    value=d["id"],
                    description=f"{role.get('name','?')} | {d.get('size',0)} soldiers | {d.get('location','?')}"[:100],
                ))
            if not div_options:
                div_options = [guilded.SelectOption(label="No divisions yet", value="_none")]
            self.divisions_select = guilded.ui.Select(
                placeholder="⚔️ Divisions to commit (multi)",
                options=div_options[:25],
                min_values=0,
                max_values=min(10, len(div_options)),
                row=3,
            )
            self.divisions_select.callback = self._on_divisions
            self.add_item(self.divisions_select)

            launch_btn = guilded.ui.Button(
                label="LAUNCH ATTACK", emoji="⚔️",
                style=guilded.ButtonStyle.danger, row=4,
            )
            launch_btn.callback = self._on_launch
            self.add_item(launch_btn)

            ai_btn = guilded.ui.Button(
                label="AI Tactic", emoji="🧠",
                style=guilded.ButtonStyle.success, row=4,
            )
            ai_btn.callback = self._on_ai_tactic
            self.add_item(ai_btn)

            advanced_btn = guilded.ui.Button(
                label="Advanced", emoji="⚙️",
                style=guilded.ButtonStyle.primary, row=4,
            )
            advanced_btn.callback = self._on_advanced
            self.add_item(advanced_btn)

            cancel_btn = guilded.ui.Button(
                label="Cancel", emoji="❌",
                style=guilded.ButtonStyle.secondary, row=4,
            )
            cancel_btn.callback = self._on_cancel
            self.add_item(cancel_btn)

        async def _on_direction(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.direction = self.direction_select.values[0]
            await interaction.response.defer()

        async def _on_mentality(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.mentality = self.mentality_select.values[0]
            await interaction.response.defer()

        async def _on_technique(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.technique = self.technique_select.values[0]
            await interaction.response.defer()

        async def _on_divisions(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.divisions = [v for v in self.divisions_select.values if v != "_none"]
            await interaction.response.defer()

        async def _on_ai_tactic(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            await interaction.response.send_modal(AITacticModal(self))

        async def _on_advanced(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            sub = MilitaryCommands.AdvancedTacticsView(
                self.cog, self.ctx, self.attacker_id, self.defender_id, self
            )
            await interaction.response.send_message(
                "⚙️ **Advanced Options** — configure general, instructions, and battle phases.",
                view=sub, ephemeral=True
            )

        async def _on_cancel(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            for item in self.children:
                item.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                pass
            await interaction.followup.send("❌ Attack cancelled.", ephemeral=True)
            self.stop()

        async def _on_launch(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your panel.", ephemeral=True); return

            if not self.direction:
                await interaction.response.send_message("❌ Pick a direction first.", ephemeral=True); return
            if not self.mentality:
                await interaction.response.send_message("❌ Pick a mentality first.", ephemeral=True); return
            if not self.technique or self.technique == "_none":
                await interaction.response.send_message("❌ Pick a technique first.", ephemeral=True); return
            if not self.divisions:
                await interaction.response.send_message("❌ Commit at least one division.", ephemeral=True); return

            t = config.TECHNIQUES.get(self.technique, {})
            cost = t.get("cost", {})
            if not self.cog.civ_manager.can_afford(self.attacker_id, cost):
                cost_str = ", ".join(f"{v} {k}" for k, v in cost.items())
                await interaction.response.send_message(f"❌ Cannot afford technique: {cost_str}.", ephemeral=True)
                return

            order = {
                "attacker_id": self.attacker_id,
                "defender_id": self.defender_id,
                "direction": self.direction,
                "mentality": self.mentality,
                "technique": self.technique,
                "division_ids": self.divisions,
                "general_id": self.general_id,
                "instructions": self.instructions,
                "phase_opening": self.phase_opening,
                "phase_main": self.phase_main,
                "phase_exploitation": self.phase_exploitation,
                # AI tactic (new)
                "ai_plan_score": self.ai_plan_score,
                "ai_plan_text": self.ai_plan_text,
                "ai_plan_notes": self.ai_plan_notes,
                "created_at": datetime.utcnow().isoformat(),
                "status": "pending",
            }
            attack_id = f"atk_{random.randint(1000000, 9999999)}"
            saved = self.cog.db.save_pending_attack(attack_id, order)

            for item in self.children:
                item.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                pass

            if saved:
                ai_line = ""
                if self.ai_plan_score is not None:
                    bonus_pct = (self.ai_plan_score - 0.5) * 50
                    ai_line = f"\n**AI Plan Score:** {self.ai_plan_score*100:.0f}/100 ({bonus_pct:+.1f}% attack)"
                await interaction.followup.send(
                    embed=create_embed(
                        "⚔️ Attack Plan Locked In",
                        f"Order `{attack_id}` submitted.\n"
                        f"**Direction:** {config.ATTACK_DIRECTIONS[self.direction]['emoji']} {config.ATTACK_DIRECTIONS[self.direction]['name']}\n"
                        f"**Mentality:** {config.MENTALITIES[self.mentality]['emoji']} {config.MENTALITIES[self.mentality]['name']}\n"
                        f"**Technique:** {t.get('emoji','')} {t.get('name','?')}\n"
                        f"**Divisions:** {len(self.divisions)}"
                        f"{ai_line}\n\n"
                        f"Use `.attackresolve {attack_id}` to resolve the engagement.",
                        guilded.Color.dark_red()
                    )
                )
            else:
                await interaction.followup.send("❌ Failed to save the order.", ephemeral=True)
            self.stop()

    # ---- Advanced sub-panel ----
    class AdvancedTacticsView(guilded.ui.View):
        def __init__(self, cog, ctx, attacker_id: str, defender_id: str, parent_view, timeout: float = 300.0):
            super().__init__(timeout=timeout)
            self.cog = cog
            self.bot = cog.bot
            self.ctx = ctx
            self.attacker_id = attacker_id
            self.defender_id = defender_id
            self.parent = parent_view
            self._build()

        def _build(self):
            civ = self.cog.civ_manager.get_civilization(self.attacker_id)
            doctrine = (civ or {}).get("doctrine")

            generals = self.cog.db.get_user_generals(self.attacker_id)
            g_options = []
            for g in generals[:25]:
                pos = config.GENERAL_POSITIVE_TRAITS.get(g.get("positive_trait"), {})
                g_options.append(guilded.SelectOption(
                    label=f"🎖️ {g['name']}",
                    value=g["id"],
                    description=f"Rank {g.get('rank',1)} | +{pos.get('name','?')}"[:100],
                ))
            if not g_options:
                g_options = [guilded.SelectOption(label="No generals", value="_none")]
            self.general_select = guilded.ui.Select(
                placeholder="🎖️ Assign commander",
                options=g_options[:25], row=0,
            )
            self.general_select.callback = self._on_general
            self.add_item(self.general_select)

            allowed_instr = config.DOCTRINES.get(doctrine, {}).get("allowed_instructions", [])
            i_options = []
            for k in allowed_instr[:25]:
                ins = config.OPERATIONAL_INSTRUCTIONS.get(k)
                if not ins: continue
                i_options.append(guilded.SelectOption(
                    label=f"{ins['emoji']} {ins['name']}",
                    value=k, description=ins['desc'][:100],
                ))
            if not i_options:
                i_options = [guilded.SelectOption(label="No instructions available", value="_none")]
            self.instructions_select = guilded.ui.Select(
                placeholder="📋 Operational instructions (multi)",
                options=i_options[:25], min_values=0,
                max_values=min(5, len(i_options)), row=1,
            )
            self.instructions_select.callback = self._on_instructions
            self.add_item(self.instructions_select)

            opening = config.BATTLE_PHASES["opening"]["options"]
            o_options = [
                guilded.SelectOption(
                    label=f"{opening[k]['name']}", value=k,
                    description=", ".join(f"{kk} {vv:+.2f}" for kk, vv in opening[k]["effect"].items())[:100],
                ) for k in opening
            ]
            self.opening_select = guilded.ui.Select(
                placeholder="🎬 Opening phase",
                options=o_options[:25], row=2,
            )
            self.opening_select.callback = self._on_opening
            self.add_item(self.opening_select)

            main = config.BATTLE_PHASES["main"]["options"]
            m_options = [
                guilded.SelectOption(
                    label=f"{main[k]['name']}", value=k,
                    description=", ".join(f"{kk} {vv:+.2f}" for kk, vv in main[k]["effect"].items())[:100],
                ) for k in main
            ]
            self.main_select = guilded.ui.Select(
                placeholder="⚔️ Main phase",
                options=m_options[:25], row=3,
            )
            self.main_select.callback = self._on_main
            self.add_item(self.main_select)

            exploit = config.BATTLE_PHASES["exploitation"]["options"]
            e_options = [
                guilded.SelectOption(
                    label=f"{exploit[k]['name']}", value=k,
                    description=", ".join(f"{kk} {vv:+.2f}" for kk, vv in exploit[k]["effect"].items())[:100],
                ) for k in exploit
            ]
            self.exploitation_select = guilded.ui.Select(
                placeholder="🏆 Exploitation phase",
                options=e_options[:25], row=4,
            )
            self.exploitation_select.callback = self._on_exploitation
            self.add_item(self.exploitation_select)

        async def _on_general(self, interaction):
            if interaction.user.id != int(self.attacker_id):
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            v = self.general_select.values[0]
            self.parent.general_id = None if v == "_none" else v
            await interaction.response.defer()

        async def _on_instructions(self, interaction):
            if interaction.user.id != int(self.attacker_id):
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.parent.instructions = [v for v in self.instructions_select.values if v != "_none"]
            await interaction.response.defer()

        async def _on_opening(self, interaction):
            if interaction.user.id != int(self.attacker_id):
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.parent.phase_opening = self.opening_select.values[0]
            await interaction.response.defer()

        async def _on_main(self, interaction):
            if interaction.user.id != int(self.attacker_id):
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.parent.phase_main = self.main_select.values[0]
            await interaction.response.defer()

        async def _on_exploitation(self, interaction):
            if interaction.user.id != int(self.attacker_id):
                await interaction.response.send_message("Not your panel.", ephemeral=True); return
            self.parent.phase_exploitation = self.exploitation_select.values[0]
            await interaction.response.defer()

    @commands.command(name='tactics')
    async def tactics_cmd(self, ctx, target: guilded.Member = None):
        if not target:
            await ctx.send("⚔️ Usage: `.tactics <user>`\nOpens the tactical planning panel.")
            return
        user_id = str(ctx.author.id)
        target_id = str(target.id)
        if user_id == target_id:
            await ctx.send("❌ Can't attack yourself.")
            return
        civ = self.civ_manager.get_civilization(user_id)
        target_civ = self.civ_manager.get_civilization(target_id)
        if not civ or not target_civ:
            await ctx.send("❌ Both parties need a civilization.")
            return
        if not civ.get("doctrine"):
            await ctx.send("❌ Pick a doctrine first: `.doctrine <name>`")
            return
        if not self._check_war(user_id, target_id):
            await ctx.send("❌ You must declare war first: `.declare @user`")
            return
        divisions = self.db.get_user_divisions(user_id)
        if not divisions:
            await ctx.send("❌ You need at least one division. Use `.createdivision`.")
            return

        panel = MilitaryCommands.TacticsPanelView(self, ctx, user_id, target_id)
        embed = create_embed(
            "🎯 Tactical Planning",
            f"Attacker: **{civ['name']}**\nDefender: **{target_civ['name']}**\n\n"
            f"**Doctrine:** {config.DOCTRINES[civ['doctrine']]['emoji']} "
            f"{config.DOCTRINES[civ['doctrine']]['name']}\n\n"
            f"Configure your attack, then press **LAUNCH ATTACK**.\n"
            f"Use **Advanced** for general, instructions, and battle phases.\n"
            f"Use **🧠 AI Tactic** to describe your overall plan in your own words — "
            f"the AI will rate it and apply a battle modifier.\n\n"
            f"⚠️ **On victory you can capture provinces** — count scales with your "
            f"power ratio and your exploitation phase. No cap.",
            guilded.Color.dark_red()
        )
        await ctx.send(embed=embed, view=panel)

    # =================================================================
    # BANK RAID — Skill driven, no cooldown
    # =================================================================
    @commands.command(name='bankraid', aliases=['braid'])
    async def bank_raid(self, ctx, target: guilded.Member = None):
        """Skill-based heist. Describe your plan; the AI rates it. No cooldown."""
        try:
            user_id = str(ctx.author.id)

            if not target:
                embed = create_embed(
                    "🏦 Bank Raid — Write Your Heist",
                    "**Usage:** `.bankraid @user`\n\n"
                    "**How it works:**\n"
                    "You'll be asked to describe your heist plan in your own words. "
                    "The AI rates your plan on creativity, plausibility, escape plan, "
                    "and execution. **Your plan is the main driver of success.**\n\n"
                    "**Requirements:**\n"
                    f"• At least **{BANKRAID['min_spies']} spies**\n"
                    f"• **Tech {BANKRAID['min_tech']}+**\n"
                    f"• Target must have **{BANKRAID['min_target_deposits']:,}+ gold in the bank**\n\n"
                    "**Rewards:** Steal **5–20%** of target deposits (max 10M)\n"
                    "**Risks:** Lose spies, get sanctioned, get detected\n\n"
                    "**No cooldown.** Great plans win. Bad plans fail. Stats help, but skill decides.",
                    guilded.Color.dark_red(),
                )
                await ctx.send(embed=embed)
                return

            target_id = str(target.id)
            if target_id == user_id:
                await ctx.send("❌ You can't raid your own bank, President.")
                return

            civ = self.civ_manager.get_civilization(user_id)
            target_civ = self.civ_manager.get_civilization(target_id)
            if not civ or not target_civ:
                await ctx.send("❌ Both parties need a civilization.")
                return

            if civ['military']['spies'] < BANKRAID["min_spies"]:
                await ctx.send(f"❌ You need at least **{BANKRAID['min_spies']} spies**. "
                               f"You have {civ['military']['spies']}.")
                return
            attacker_tech = civ['military']['tech_level']
            if attacker_tech < BANKRAID["min_tech"]:
                await ctx.send(f"❌ You need **Tech {BANKRAID['min_tech']}** for a bank raid.")
                return

            target_bank = target_civ.get('bank') or {}
            target_deposits = int(target_bank.get('deposits', 0))
            if target_deposits < BANKRAID["min_target_deposits"]:
                await ctx.send(f"❌ **{target_civ['name']}** only has "
                               f"🪙 {format_number(target_deposits)} in the bank — "
                               f"minimum is {BANKRAID['min_target_deposits']:,}.")
                return

            target_has_mirror = self._has_hyperitem(target_id, "Mirror")
            target_has_shield = self._has_hyperitem(target_id, "Anti-Nuke Shield")

            # ---- Prompt for the plan ----
            intel = (
                f"Target: {target_civ['name']}\n"
                f"Bank deposits: {target_deposits:,} gold\n"
                f"Target spies: {target_civ['military'].get('spies',0):,}\n"
                f"Target tech level: {target_civ['military'].get('tech_level',0)}\n"
                f"Target credit score: {int(target_bank.get('credit_score',100))}/100\n"
                f"Attacker spies: {civ['military'].get('spies',0):,}\n"
                f"Attacker tech: {attacker_tech}"
            )
            prompt_embed = create_embed(
                "🏦 Write Your Heist Plan",
                f"**Target:** {target_civ['name']} — 🪙 {format_number(target_deposits)} in the vault\n\n"
                f"Describe your heist in **2–4 sentences** in this channel. "
                f"Cover **entry, execution, and escape** for the best score.\n\n"
                f"Type `cancel` to abort. You have **2 minutes**.",
                guilded.Color.dark_gold(),
            )
            await ctx.send(embed=prompt_embed)

            def check(m):
                return (m.author.id == ctx.author.id and m.channel.id == ctx.channel.id
                        and not m.author.bot)
            try:
                msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("🛑 Heist cancelled (timeout).")
                return

            plan_text = (msg.content or "").strip()
            if plan_text.lower() in ("cancel", "abort", "stop"):
                await ctx.send("🛑 Heist cancelled.")
                return
            if len(plan_text) < 15:
                await ctx.send("❌ Plan too short. Describe it properly next time.")
                return

            # ---- AI rate the plan ----
            async with ctx.typing():
                rating = await self._ai_rate_heist(plan_text, intel)

            if rating is None:
                await ctx.send("⚠️ AI evaluator unavailable. Heist aborted — no resources lost.")
                return

            ai_score = float(rating.get("score", 0.5))
            spy_loss_mult = float(rating.get("spy_loss_mult", 1.0))

            # ---- Stat modifier ----
            spy_swing = (civ['military']['spies'] - target_civ['military']['spies']) / 500.0
            spy_swing = max(-0.30, min(0.30, spy_swing))
            tech_swing = max(-0.15, min(0.20, (attacker_tech - target_civ['military']['tech_level']) * 0.03))
            ideo_bonus = 0.0
            if civ.get('ideology') == 'terrorism':
                ideo_bonus += 0.10
            elif civ.get('ideology') == 'anarchy':
                ideo_bonus += 0.05

            stat_score = max(0.0, min(1.0, 0.5 + spy_swing + tech_swing + ideo_bonus))

            combined = (ai_score * BANKRAID["ai_weight"]) + (stat_score * BANKRAID["stat_weight"])
            success_chance = max(BANKRAID["min_success"],
                                 min(BANKRAID["max_success"], combined))

            # Show the review
            review_embed = create_embed(
                "🧠 Heist Plan Reviewed",
                f"**Your Plan:** *\"{plan_text[:200]}\"*\n\n"
                f"**AI Score:** {ai_score*100:.0f}/100\n"
                f"**Verdict:** {rating.get('verdict','—')}\n"
                f"**Reasoning:** {rating.get('reasoning','—')}\n\n"
                f"**Stat Score:** {stat_score*100:.0f}/100\n"
                f"**Final Success Chance:** **{success_chance*100:.1f}%**",
                guilded.Color.purple(),
            )
            await ctx.send(embed=review_embed)

            # ---- Defense resolution ----
            if target_has_mirror:
                self._consume_hyperitem(target_id, "Mirror")
                spy_loss = int(civ['military']['spies'] * random.uniform(0.20, 0.35) * spy_loss_mult)
                spy_loss = max(1, spy_loss)
                self.civ_manager.update_military(user_id, {"spies": -spy_loss})
                self.civ_manager.update_population(user_id, {"happiness": -15})
                await ctx.send(embed=create_embed(
                    "🪞 BANK RAID REFLECTED!",
                    f"**{target_civ['name']}**'s **Mirror** caught your crew mid-heist.\n"
                    f"**Spies lost:** 🕵️ {format_number(spy_loss)}\n"
                    f"**Stolen:** 0 gold",
                    guilded.Color.purple(),
                ))
                try:
                    tu = await self.bot.fetch_user(int(target_id))
                    await tu.send(f"🪞 **Bank Raid Reflected!** {civ['name']} tried to raid your bank "
                                  f"but your Mirror caught them.")
                except Exception:
                    pass
                return

            if target_has_shield:
                self._consume_hyperitem(target_id, "Anti-Nuke Shield")
                spy_loss = int(civ['military']['spies'] * random.uniform(0.05, 0.15) * spy_loss_mult)
                spy_loss = max(1, spy_loss)
                self.civ_manager.update_military(user_id, {"spies": -spy_loss})
                await ctx.send(embed=create_embed(
                    "🛡️ BANK RAID BLOCKED!",
                    f"**{target_civ['name']}**'s **Anti-Nuke Shield** sealed the vault.\n"
                    f"**Spies lost:** 🕵️ {format_number(spy_loss)}\n"
                    f"**Stolen:** 0 gold",
                    guilded.Color.blue(),
                ))
                try:
                    tu = await self.bot.fetch_user(int(target_id))
                    await tu.send(f"🛡️ **Bank Raid Blocked!** {civ['name']} tried to raid your bank "
                                  f"but your Anti-Nuke Shield stopped them.")
                except Exception:
                    pass
                return

            # ---- Roll ----
            if random.random() < success_chance:
                steal_frac = random.uniform(BANKRAID["min_steal_fraction"], BANKRAID["max_steal_fraction"])
                raw_steal = int(target_deposits * steal_frac)
                steal = min(raw_steal, BANKRAID["max_steal_absolute"])

                new_target_bank = dict(target_bank)
                new_target_bank['deposits'] = max(0, target_deposits - steal)
                self.db.update_civilization(target_id, {"bank": new_target_bank})
                self.civ_manager._invalidate_civ(target_id)

                self.civ_manager.update_resources(user_id, {"gold": steal})
                self.civ_manager.update_population(user_id, {"happiness": 8})
                self.civ_manager.update_population(target_id, {"happiness": -10})
                self.civ_manager.apply_faction_effects(user_id, "raidcaravan")

                # Small spy loss even on success (escape isn't free)
                residual_loss = int(civ['military']['spies'] * random.uniform(0.0, 0.05) * spy_loss_mult)
                if residual_loss > 0:
                    self.civ_manager.update_military(user_id, {"spies": -residual_loss})

                self.db.log_event(user_id, "bank_raid_success", "Bank Raid Successful",
                                  f"Stole {steal:,} gold from {target_civ['name']}'s bank.")
                self.db.log_event(target_id, "bank_raid_victim", "Bank Raid Victim",
                                  f"{civ['name']} raided their bank for {steal:,} gold.")

                embed = create_embed(
                    "🏦💰 THE IMPOSSIBLE HEIST — SUCCESS!",
                    f"Your plan worked. **{civ['name']}** walks out with the vault.\n\n"
                    f"**{target_civ['name']}** will remember this.",
                    guilded.Color.gold(),
                )
                embed.add_field(name="Stolen", value=f"🪙 **{format_number(steal)}** ({steal_frac*100:.1f}%)",
                                inline=True)
                embed.add_field(name="Remaining",
                                value=f"🪙 {format_number(new_target_bank['deposits'])}",
                                inline=True)
                if residual_loss:
                    embed.add_field(name="Spies lost", value=f"🕵️ {residual_loss}", inline=True)
                embed.set_footer(text="In your pocket — not your bank. Counter-raids can't touch it.")
                await ctx.send(embed=embed)

                try:
                    tu = await self.bot.fetch_user(int(target_id))
                    await tu.send(f"🏦💀 **YOUR BANK WAS RAIDED!** {civ['name']} stole "
                                  f"**{format_number(steal)} gold** from your vault.")
                except Exception:
                    pass

            else:
                spy_loss = int(civ['military']['spies'] *
                               random.uniform(BANKRAID["spy_loss_on_fail_min"],
                                              BANKRAID["spy_loss_on_fail_max"]) * spy_loss_mult)
                spy_loss = max(1, spy_loss)
                self.civ_manager.update_military(user_id, {"spies": -spy_loss})
                self.civ_manager.update_population(user_id, {"happiness": -12})

                try:
                    sanctions = target_civ.get('imposed_sanctions') or []
                    expires = (datetime.utcnow() +
                               timedelta(hours=BANKRAID["detection_sanction_hours"])).isoformat()
                    sanctions.append({
                        "target_id": user_id,
                        "expires_at": expires,
                        "reason": "Bank raid retaliation",
                    })
                    self.db.update_civilization(target_id, {"imposed_sanctions": sanctions})
                    received = civ.get('received_sanctions') or []
                    received.append({
                        "imposer_id": target_id,
                        "expires_at": expires,
                        "reason": "Bank raid retaliation",
                    })
                    self.db.update_civilization(user_id, {"received_sanctions": received})
                    self.civ_manager._invalidate_civ(user_id)
                    self.civ_manager._invalidate_civ(target_id)
                except Exception as e:
                    logger.error(f"Failed to auto-sanction after failed bankraid: {e}")

                self.db.log_event(user_id, "bank_raid_fail", "Bank Raid Failed",
                                  f"Failed to raid {target_civ['name']}. Lost {spy_loss} spies.")

                embed = create_embed(
                    "🏦💀 THE HEIST FAILED",
                    f"Alarms scream. Guards flood the halls.\n\n"
                    f"**{target_civ['name']}** was ready.\n\n"
                    f"**Spies lost:** 🕵️ {format_number(spy_loss)}\n"
                    f"**Happiness:** -12\n"
                    f"**Retaliation:** {target_civ['name']} has sanctioned you for "
                    f"{BANKRAID['detection_sanction_hours']}h",
                    guilded.Color.dark_red(),
                )
                await ctx.send(embed=embed)

                try:
                    tu = await self.bot.fetch_user(int(target_id))
                    await tu.send(f"🏦🚨 **Bank Raid Attempt Detected!** {civ['name']} tried to raid "
                                  f"your bank and failed. You've sanctioned them. "
                                  f"They lost {format_number(spy_loss)} spies.")
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"bankraid error: {e}", exc_info=True)
            await ctx.send("❌ The heist went wrong on our end. Nothing was stolen.")

    # =================================================================
    # STEALTH BATTLE
    # =================================================================
    @commands.command(name='stealthbattle')
    async def stealth_battle(self, ctx, target: guilded.Member = None, timer: float = None):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("stealthbattle", 4) * 60
            if not self._check_cooldown(user_id, 'stealthbattle', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'stealthbattle')
                await ctx.send(f"⏳ Wait {remaining // 60}m {remaining % 60}s.")
                return
            if not target:
                await ctx.send("🕵️ `.stealthbattle <user> [timer]`")
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                await ctx.send("❌ Need a civilization.")
                return
            if civ['military']['spies'] < 3:
                await ctx.send("❌ Need at least 3 spies.")
                return
            target_id = str(target.id)
            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target has no civilization.")
                return
            effective_timer = DEFAULT_STEALTH_TIMER
            if timer is not None and 3.0 <= timer <= 30.0:
                effective_timer = float(timer)
            question, correct, choices = _generate_stealth_question()
            intro = create_embed("🕵️ **INFILTRATION**",
                                 f"**Question:** {question}\n\n"
                                 f"⏱️ Answer within **{effective_timer:.0f} seconds**.",
                                 guilded.Color.dark_blue())
            view = StealthQuestionView(ctx.author.id, question, correct, choices, timeout=effective_timer)
            await ctx.send(embed=intro, view=view)
            await view.wait()
            if view.correct_answer is not True:
                spy_losses = random.randint(1, 2)
                self.civ_manager.update_military(user_id, {"spies": -spy_losses})
                self.civ_manager.apply_faction_effects(user_id, "stealthbattle")
                self._start_cooldown(user_id, 'stealthbattle', cooldown_seconds)
                reason = ("❌ Wrong answer." if view.correct_answer is False
                          else f"⏱️ Timed out after {effective_timer:.0f}s.")
                fail = create_embed("🕵️ Mission Failed",
                                    f"{reason} Lost {spy_losses} spies.",
                                    guilded.Color.red())
                fail.add_field(name="Correct", value=f"`{question}` → **{correct}**", inline=False)
                await ctx.send(embed=fail)
                return
            self._start_cooldown(user_id, 'stealthbattle', cooldown_seconds)
            tech = self._get_military_tech(user_id); target_tech = self._get_military_tech(target_id)
            att_pow = civ['military']['spies'] * tech.get("ground_tech", 1)
            def_pow = target_civ['military']['spies'] * target_tech.get("ground_tech", 1)
            success = max(0.35, min(0.95, 0.7 + (att_pow - def_pow) / 100))
            if civ.get('ideology') == 'destruction': success *= 1.2
            if target_civ.get('ideology') == 'fascism': success *= 0.9
            if random.random() < success:
                op = random.choice(['sabotage', 'theft', 'intel'])
                text = ""
                if op == 'sabotage':
                    dmg = {"stone": -random.randint(50, 200), "wood": -random.randint(30, 150)}
                    self.civ_manager.update_resources(target_id, dmg)
                    text = "Sabotaged enemy infrastructure."
                elif op == 'theft':
                    stolen = min(int(target_civ['resources']['gold'] * random.uniform(0.05, 0.15)),
                                 target_civ['resources']['gold'])
                    self.civ_manager.update_resources(target_id, {"gold": -stolen})
                    self.civ_manager.update_resources(user_id, {"gold": stolen})
                    text = f"Stole {format_number(stolen)} gold."
                else:
                    gain = 1 if random.random() < 0.3 else 0
                    if gain:
                        self._update_military_tech(user_id, {"ground_tech": gain})
                    text = f"Gathered intelligence. {'+1 ground tech' if gain else ''}"
                self.civ_manager.apply_faction_effects(user_id, "stealthbattle")
                embed = create_embed("🕵️ Success!", text, guilded.Color.purple())
                embed.add_field(name="✅ Answer", value=f"`{correct}`", inline=False)
                await ctx.send(embed=embed)
            else:
                losses = random.randint(1, 4)
                self.civ_manager.update_military(user_id, {"spies": -losses})
                embed = create_embed("🕵️ Detected on exit", f"Lost {losses} spies.", guilded.Color.red())
                embed.add_field(name="✅ Answer", value=f"`{correct}`", inline=False)
                await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"stealthbattle error: {e}", exc_info=True)

    # =================================================================
    # SIEGE
    # =================================================================
    @commands.command(name='siege')
    async def siege_city(self, ctx, target: guilded.Member = None):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("siege", 10) * 60
            if not self._check_cooldown(user_id, 'siege', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'siege')
                await ctx.send(f"⏳ Wait {remaining // 60}m {remaining % 60}s.")
                return
            if not target:
                await ctx.send("🏰 Usage: `.siege <user>`")
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                await ctx.send("❌ Need a civilization.")
                return
            if civ['military']['soldiers'] < 50:
                await ctx.send("❌ Need 50 soldiers.")
                return
            target_id = str(target.id)
            target_civ = self.civ_manager.get_civilization(target_id)
            if not target_civ:
                await ctx.send("❌ Target has no civilization.")
                return
            if not self._check_war(user_id, target_id):
                await ctx.send("❌ Declare war first.")
                return
            tech = self._get_military_tech(user_id)
            siege_power = civ['military']['soldiers'] + tech.get("ground_tech", 1) * 10
            def_res = target_civ['military']['soldiers'] + target_civ['territory']['land_size'] / 100
            eff = siege_power / (siege_power + def_res)
            if target_civ['military']['soldiers'] / max(1, civ['military']['soldiers']) < 0.5:
                eff *= 0.7
                await ctx.send("🛡️ Underdog defense!")
            drain = {
                "gold": min(int(target_civ['resources']['gold'] * eff * 0.1), target_civ['resources']['gold']),
                "food": min(int(target_civ['resources']['food'] * eff * 0.2), target_civ['resources']['food']),
                "wood": min(int(target_civ['resources']['wood'] * eff * 0.15), target_civ['resources']['wood']),
                "stone": min(int(target_civ['resources']['stone'] * eff * 0.15), target_civ['resources']['stone']),
            }
            maint = {"gold": civ['military']['soldiers'] * 2, "food": civ['military']['soldiers'] * 3}
            if not self.civ_manager.can_afford(user_id, maint):
                await ctx.send("❌ Can't afford maintenance.")
                return
            self._start_cooldown(user_id, 'siege', cooldown_seconds)
            self.civ_manager.spend_resources(user_id, maint)
            self.civ_manager.update_resources(target_id, {r: -a for r, a in drain.items()})
            self.civ_manager.update_population(target_id, {"happiness": -15})
            self.civ_manager.update_population(user_id, {"happiness": -5})
            self.civ_manager.apply_faction_effects(user_id, "siege")
            embed = create_embed("🏰 Siege",
                                 f"**{civ['name']}** lays siege to **{target_civ['name']}**!",
                                 guilded.Color.orange())
            drain_text = "\n".join(f"🪙 {format_number(a)} {r}" for r, a in drain.items() if a > 0)
            embed.add_field(name="Drain", value=drain_text or "None", inline=True)
            embed.add_field(name="Maintenance",
                            value=f"🪙 {format_number(maint['gold'])}\n🌾 {format_number(maint['food'])}",
                            inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"siege error: {e}", exc_info=True)

    # =================================================================
    # FIND
    # =================================================================
    @commands.command(name='find')
    async def find_soldiers(self, ctx):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("find", 1) * 60
            if not self._check_cooldown(user_id, 'find', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'find')
                await ctx.send(f"⏳ Wait {remaining}s.")
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                await ctx.send("❌ Need a civilization.")
                return
            self._start_cooldown(user_id, 'find', cooldown_seconds)
            base_chance = 0.5
            min_s, max_s = 5, 20
            if civ.get('ideology') == 'pacifist':
                base_chance *= 1.9; max_s = 15
            elif civ.get('ideology') == 'destruction':
                base_chance *= 0.75; max_s = 30; min_s = 10
            final_chance = min(0.9, base_chance * (1 + civ['population']['happiness'] / 100))
            if random.random() < final_chance:
                found = random.randint(min_s, max_s)
                self.civ_manager.update_military(user_id, {"soldiers": found})
                self.civ_manager.apply_faction_effects(user_id, "find_soldiers")
                embed = create_embed("🔍 Soldiers Found!", f"{found} joined your army.", guilded.Color.green())
            else:
                embed = create_embed("🔍 Search Unsuccessful", "No willing soldiers found.", guilded.Color.blue())
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"find error: {e}", exc_info=True)

    # =================================================================
    # PEACE (legacy)
    # =================================================================
    @commands.command(name='peace')
    async def make_peace(self, ctx, target: guilded.Member = None):
        try:
            if not target:
                await ctx.send("🕊️ Usage: `.peace <user>`")
                return
            user_id = str(ctx.author.id)
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            target_civ = self.civ_manager.get_civilization(str(target.id))
            if not civ or not target_civ:
                await ctx.send("❌ Both need a civilization.")
                return
            target_id = str(target.id)
            if not self._check_war(user_id, target_id):
                await ctx.send("❌ Not at war.")
                return
            for offer in self.db.get_peace_offers():
                if offer.get("offerer_id") == user_id and offer.get("receiver_id") == target_id:
                    await ctx.send("❌ Already have a pending offer.")
                    return
            self.db.create_peace_offer(user_id, target_id)
            self.civ_manager.apply_faction_effects(user_id, "peace_offer")
            embed = create_embed("🕊️ Peace Offer Sent",
                                 f"**{civ['name']}** → **{target_civ['name']}**",
                                 guilded.Color.green())
            await ctx.send(embed=embed)
            try:
                await ctx.send(f"{target.mention} 🕊️ Use `.accept_peace @{ctx.author.display_name}`.")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"peace error: {e}", exc_info=True)

    @commands.command(name='accept_peace')
    async def accept_peace(self, ctx, target: guilded.Member = None):
        try:
            if not target:
                await ctx.send("🕊️ Usage: `.accept_peace <user>`")
                return
            user_id = str(ctx.author.id)
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            offerer_id = str(target.id)
            civ = self.civ_manager.get_civilization(user_id)
            offerer_civ = self.civ_manager.get_civilization(offerer_id)
            if not civ or not offerer_civ:
                await ctx.send("❌ Both need a civilization.")
                return
            if not self._check_war(user_id, offerer_id):
                await ctx.send("❌ Not at war.")
                return
            offer_id = next((o.get("id") for o in self.db.get_peace_offers()
                             if o.get("offerer_id") == offerer_id and o.get("receiver_id") == user_id), None)
            if not offer_id:
                await ctx.send("❌ No pending offer.")
                return
            self.db.end_war(user_id, offerer_id, "peace")
            self.db.update_peace_offer(offer_id, "accepted")
            self.civ_manager.update_population(user_id, {"happiness": 15})
            self.civ_manager.update_population(offerer_id, {"happiness": 15})
            self.civ_manager.apply_faction_effects(user_id, "accept_peace")
            self.civ_manager.apply_faction_effects(offerer_id, "accept_peace")
            embed = create_embed("🕊️ Peace Achieved",
                                 f"**{civ['name']}** accepted peace from **{offerer_civ['name']}**.",
                                 guilded.Color.green())
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"accept_peace error: {e}", exc_info=True)

    # =================================================================
    # CARDS
    # =================================================================
    @commands.command(name='cards')
    async def manage_cards(self, ctx, action: str = None, *, card_name: str = None):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        if action is None or action.lower() == 'view':
            purchased = civ.get('purchased_cards', [])
            if not purchased:
                await ctx.send("📭 No cards. `.buycard` to get one.")
                return
            embed = create_embed("🎴 Your Cards", "", guilded.Color.blue())
            for i, card in enumerate(purchased, 1):
                embed.add_field(name=f"{i}. {card['name']}",
                                value=f"{card['description']}\n`.cards use \"{card['name']}\"`",
                                inline=False)
            await ctx.send(embed=embed)
        elif action.lower() == 'use':
            if not card_name:
                await ctx.send("❌ Specify card name.")
                return
            purchased = civ.get('purchased_cards', [])
            card = next((c for c in purchased if c['name'].lower() == card_name.lower()), None)
            if not card:
                await ctx.send(f"❌ No card named '{card_name}'.")
                return
            effect = card['effect']
            if card['type'] == 'bonus':
                bonuses = civ.get('bonuses', {})
                for k, v in effect.items():
                    bonuses[k] = bonuses.get(k, 0) + v
                self.db.update_civilization(user_id, {"bonuses": bonuses})
            else:
                for r in ("gold", "food", "stone", "wood"):
                    if r in effect:
                        self.civ_manager.update_resources(user_id, {r: effect[r]})
                for m in ("soldiers", "spies", "tech_level"):
                    if m in effect:
                        self.civ_manager.update_military(user_id, {m: effect[m]})
                for p in ("citizens", "happiness"):
                    if p in effect:
                        self.civ_manager.update_population(user_id, {p: effect[p]})
            purchased.remove(card)
            self.db.update_civilization(user_id, {"purchased_cards": purchased})
            await ctx.send(f"✅ Used **{card['name']}**.")

    # =================================================================
    # BORDERS
    # =================================================================
    @commands.command(name='addborder')
    async def add_border(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        cost = config.MILITARY["border_cost"]
        if not self.civ_manager.can_afford(user_id, cost):
            await ctx.send(f"❌ Need 🪙 {format_number(cost['gold'])} / 🪨 {format_number(cost['stone'])} / 🪵 {format_number(cost['wood'])}.")
            return
        info = self._get_border_info(user_id)
        if info.get("has_border"):
            await ctx.send("❌ Already have a border.")
            return
        self.civ_manager.spend_resources(user_id, cost)
        self._update_border(user_id, {"has_border": True, "border_strength": 100, "border_soldiers": 0})
        await ctx.send(embed=create_embed("🛡️ Border Built", "Strength 100.", guilded.Color.green()))

    @commands.command(name='removeborder')
    async def remove_border(self, ctx):
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        info = self._get_border_info(user_id)
        if not info.get("has_border"):
            await ctx.send("❌ No border.")
            return
        returned = info.get("border_soldiers", 0)
        if returned:
            self.civ_manager.update_military(user_id, {"soldiers": returned})
        self._update_border(user_id, {"has_border": False, "border_strength": 0, "border_soldiers": 0})
        await ctx.send(embed=create_embed("🛡️ Border Removed",
                                          f"Returned {format_number(returned)} soldiers.",
                                          guilded.Color.blue()))

    @commands.command(name='rectract', aliases=['retract'])
    async def rectract_soldiers(self, ctx, percentage: int = None):
        if percentage is None or not 1 <= percentage <= 100:
            await ctx.send("❌ Usage: `.rectract <1-100>`")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        info = self._get_border_info(user_id)
        if not info.get("has_border"):
            await ctx.send("❌ No border.")
            return
        avail = civ['military']['soldiers']
        assign = min((avail * percentage) // 100, avail)
        if assign <= 0:
            await ctx.send("❌ 0 soldiers to assign.")
            return
        self._update_border(user_id, {
            "border_soldiers": info["border_soldiers"] + assign,
            "border_strength": info["border_strength"] + assign * 2,
        })
        self.civ_manager.update_military(user_id, {"soldiers": -assign})
        await ctx.send(f"🛡️ Assigned {format_number(assign)} soldiers.")

    @commands.command(name='retrieve')
    async def retrieve_soldiers(self, ctx, percentage: int = None):
        if percentage is None or not 1 <= percentage <= 100:
            await ctx.send("❌ Usage: `.retrieve <1-100>`")
            return
        user_id = str(ctx.author.id)
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        info = self._get_border_info(user_id)
        if not info.get("has_border") or info["border_soldiers"] == 0:
            await ctx.send("❌ No border or no soldiers on it.")
            return
        pull = min((info["border_soldiers"] * percentage) // 100, info["border_soldiers"])
        strength_loss = (info["border_strength"] * pull) // max(1, info["border_soldiers"])
        self._update_border(user_id, {
            "border_soldiers": info["border_soldiers"] - pull,
            "border_strength": max(1, info["border_strength"] - strength_loss),
        })
        self.civ_manager.update_military(user_id, {"soldiers": pull})
        await ctx.send(f"🛡️ Retrieved {format_number(pull)} soldiers.")

    @commands.command(name='borderinfo')
    async def border_info(self, ctx):
        user_id = str(ctx.author.id)
        info = self._get_border_info(user_id)
        if not info.get("has_border"):
            await ctx.send("🛡️ No border built.")
            return
        await ctx.send(embed=create_embed(
            "🛡️ Border",
            f"Strength: **{format_number(info['border_strength'])}**\n"
            f"Soldiers: **{format_number(info['border_soldiers'])}**",
            guilded.Color.green()))

    # =================================================================
    # BUILD SHIP / PLANE
    # =================================================================
    @commands.command(name='buildship')
    async def build_ship(self, ctx, ship_type: str = None, amount: int = 1):
        user_id = str(ctx.author.id)
        if not ship_type:
            embed = create_embed("🚢 Build Ships", "", guilded.Color.blue())
            for k, d in SHIP_TYPES.items():
                embed.add_field(name=f"{d['name']} (`{k}`)",
                                value=f"🪙{d['cost_gold']} 🪵{d['cost_wood']} 🪨{d['cost_stone']}\n{d['description']}",
                                inline=True)
            await ctx.send(embed=embed)
            return
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        ship_type = ship_type.lower()
        if ship_type not in SHIP_TYPES:
            await ctx.send(f"❌ Options: {', '.join(SHIP_TYPES.keys())}")
            return
        d = SHIP_TYPES[ship_type]
        cost = {"gold": d["cost_gold"] * amount, "wood": d["cost_wood"] * amount, "stone": d["cost_stone"] * amount}
        if not self.civ_manager.can_afford(user_id, cost):
            await ctx.send("❌ Not enough resources.")
            return
        self.civ_manager.spend_resources(user_id, cost)
        self._update_navy(user_id, {ship_type: amount})
        self.civ_manager.apply_faction_effects(user_id, "buildship")
        await ctx.send(f"🚢 Built {amount} {d['name']}(s).")

    @commands.command(name='buildplane')
    async def build_plane(self, ctx, plane_type: str = None, amount: int = 1):
        user_id = str(ctx.author.id)
        if not plane_type:
            embed = create_embed("✈️ Build Planes", "", guilded.Color.blue())
            for k, d in PLANE_TYPES.items():
                embed.add_field(name=f"{d['name']} (`{k}`)",
                                value=f"🪙{d['cost_gold']} 🪵{d['cost_wood']} 🪨{d['cost_stone']}\n{d['description']}",
                                inline=True)
            await ctx.send(embed=embed)
            return
        if not await self.check_civil_war_and_proceed(ctx, user_id):
            return
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        plane_type = plane_type.lower()
        if plane_type not in PLANE_TYPES:
            await ctx.send(f"❌ Options: {', '.join(PLANE_TYPES.keys())}")
            return
        if plane_type in ("attacker", "bomber"):
            if not self._has_completed_industrial(user_id):
                await ctx.send("❌ Need Industrial Revolution complete.")
                return
            if self._get_military_tech(user_id).get("air_tech", 1) < 3:
                await ctx.send("❌ Need Air Tech 3.")
                return
        d = PLANE_TYPES[plane_type]
        cost = {"gold": d["cost_gold"] * amount, "wood": d["cost_wood"] * amount, "stone": d["cost_stone"] * amount}
        if not self.civ_manager.can_afford(user_id, cost):
            await ctx.send("❌ Not enough resources.")
            return
        self.civ_manager.spend_resources(user_id, cost)
        self._update_airforce(user_id, {plane_type: amount})
        self.civ_manager.apply_faction_effects(user_id, "buildplane")
        await ctx.send(f"✈️ Built {amount} {d['name']}(s).")

    # =================================================================
    # NAVY / AIRFORCE DISPLAY
    # =================================================================
    @commands.command(name='navy')
    async def show_navy(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        navy = self._get_navy(user_id)
        tech = self._get_military_tech(user_id).get("naval_tech", 1)
        embed = create_embed("🚢 Navy", f"Naval Tech: {tech}", guilded.Color.blue())
        total = 0; strength = 0
        for k, c in navy.items():
            if c > 0:
                s = SHIP_TYPES[k]["strength"] * c * tech
                total += c; strength += s
                embed.add_field(name=SHIP_TYPES[k]["name"],
                                value=f"{c} × strength {format_number(s)}", inline=True)
        if total == 0:
            embed.description += "\n\nNo ships yet."
        else:
            embed.add_field(name="Totals", value=f"{total} ships / {format_number(strength)} strength", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='airforce')
    async def show_airforce(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        air = self._get_airforce(user_id)
        tech = self._get_military_tech(user_id).get("air_tech", 1)
        embed = create_embed("✈️ Airforce", f"Air Tech: {tech}", guilded.Color.blue())
        total = 0; strength = 0
        for k, c in air.items():
            if c > 0:
                s = PLANE_TYPES[k]["strength"] * c * tech
                total += c; strength += s
                embed.add_field(name=PLANE_TYPES[k]["name"],
                                value=f"{c} × strength {format_number(s)}", inline=True)
        if total == 0:
            embed.description += "\n\nNo planes yet."
        else:
            embed.add_field(name="Totals", value=f"{total} planes / {format_number(strength)} strength", inline=False)
        await ctx.send(embed=embed)

    # =================================================================
    # NAVAL / AIR ATTACK / BLOCKADE
    # =================================================================
    @commands.command(name='navalattack')
    async def naval_attack(self, ctx, target: guilded.Member = None):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("navalattack", 3) * 60
            if not self._check_cooldown(user_id, 'navalattack', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'navalattack')
                await ctx.send(f"⏳ Wait {remaining}s.")
                return
            if not target:
                await ctx.send("🚢 Usage: `.navalattack <user>`")
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            target_civ = self.civ_manager.get_civilization(str(target.id))
            if not civ or not target_civ:
                await ctx.send("❌ Both need a civilization.")
                return
            target_id = str(target.id)
            if not self._check_war(user_id, target_id):
                await ctx.send("❌ Declare war first.")
                return
            my_navy = self._get_navy(user_id)
            total = sum(my_navy.values())
            if total < 1:
                await ctx.send("❌ No ships.")
                return
            self._start_cooldown(user_id, 'navalattack', cooldown_seconds)
            att = self._get_naval_strength(user_id) * random.uniform(0.8, 1.2)
            dfn = self._get_naval_strength(target_id) * random.uniform(0.8, 1.2)
            if self.civ_manager.consume_lucky_strike(user_id):
                att *= 2.0
            if att > dfn:
                margin = att / max(1, dfn)
                def_loss = min(int(total * 0.3 * margin), total)
                att_loss = min(int(total * 0.1), total)
                gold = min(int(target_civ['resources']['gold'] * 0.1 * margin), target_civ['resources']['gold'])
                food = min(int(target_civ['resources']['food'] * 0.05 * margin), target_civ['resources']['food'])
                self.civ_manager.update_resources(user_id, {"gold": gold, "food": food})
                self.civ_manager.update_resources(target_id, {"gold": -gold, "food": -food})
                self._reduce_navy(user_id, att_loss)
                self._reduce_navy(target_id, def_loss)
                self.civ_manager.apply_faction_effects(user_id, "naval_attack")
                await ctx.send(embed=create_embed("🚢 Naval Victory",
                                                  f"Spoils: 🪙 {format_number(gold)} / 🌾 {format_number(food)}",
                                                  guilded.Color.green()))
            else:
                att_loss = min(int(total * 0.4 * (dfn / max(1, att))), total)
                self._reduce_navy(user_id, att_loss)
                self.civ_manager.apply_faction_effects(user_id, "naval_attack")
                await ctx.send(embed=create_embed("🚢 Naval Defeat",
                                                  f"Lost {att_loss} ships.",
                                                  guilded.Color.red()))
        except Exception as e:
            logger.error(f"navalattack error: {e}", exc_info=True)

    def _reduce_navy(self, user_id: str, losses: int):
        if losses <= 0: return
        navy = self._get_navy(user_id)
        for ship in ["frigate", "destroyer", "battleship", "aircraft_carrier", "submarine"]:
            if losses <= 0: break
            c = navy.get(ship, 0)
            if c > 0:
                rm = min(c, losses)
                navy[ship] = c - rm
                losses -= rm
        self._update_navy(user_id, navy)

    def _reduce_airforce(self, user_id: str, losses: int):
        if losses <= 0: return
        air = self._get_airforce(user_id)
        for plane in ["fighter", "attacker", "bomber"]:
            if losses <= 0: break
            c = air.get(plane, 0)
            if c > 0:
                rm = min(c, losses)
                air[plane] = c - rm
                losses -= rm
        self._update_airforce(user_id, air)

    @commands.command(name='airattack')
    async def air_attack(self, ctx, target: guilded.Member = None):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("airattack", 3) * 60
            if not self._check_cooldown(user_id, 'airattack', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'airattack')
                await ctx.send(f"⏳ Wait {remaining}s.")
                return
            if not target:
                await ctx.send("✈️ Usage: `.airattack <user>`")
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            target_civ = self.civ_manager.get_civilization(str(target.id))
            if not civ or not target_civ:
                await ctx.send("❌ Both need a civilization.")
                return
            target_id = str(target.id)
            if not self._check_war(user_id, target_id):
                await ctx.send("❌ Declare war first.")
                return
            total = sum(self._get_airforce(user_id).values())
            if total < 1:
                await ctx.send("❌ No planes.")
                return
            self._start_cooldown(user_id, 'airattack', cooldown_seconds)
            att = self._get_air_strength(user_id) * random.uniform(0.8, 1.2)
            dfn = (self._get_air_strength(target_id) + target_civ['military']['soldiers'] * 0.1) * random.uniform(0.8, 1.2)
            if self.civ_manager.consume_lucky_strike(user_id):
                att *= 2.0
            if att > dfn:
                margin = att / max(1, dfn)
                soldier_loss = min(int(target_civ['military']['soldiers'] * 0.1 * margin), target_civ['military']['soldiers'])
                gold = min(int(target_civ['resources']['gold'] * 0.05 * margin), target_civ['resources']['gold'])
                wood = min(int(target_civ['resources']['wood'] * 0.1 * margin), target_civ['resources']['wood'])
                stone = min(int(target_civ['resources']['stone'] * 0.1 * margin), target_civ['resources']['stone'])
                att_loss = min(int(total * 0.15), total)
                def_loss = min(int(total * 0.1), total)
                self._reduce_airforce(user_id, att_loss)
                self._reduce_airforce(target_id, def_loss)
                self.civ_manager.update_military(target_id, {"soldiers": -soldier_loss})
                self.civ_manager.update_resources(user_id, {"gold": gold, "wood": wood, "stone": stone})
                self.civ_manager.update_resources(target_id, {"gold": -gold, "wood": -wood, "stone": -stone})
                self.civ_manager.apply_faction_effects(user_id, "air_attack")
                await ctx.send(embed=create_embed("✈️ Air Victory",
                                                  f"Killed {format_number(soldier_loss)}. "
                                                  f"Spoils: 🪙 {format_number(gold)}",
                                                  guilded.Color.green()))
            else:
                att_loss = min(int(total * 0.3), total)
                self._reduce_airforce(user_id, att_loss)
                self.civ_manager.apply_faction_effects(user_id, "air_attack")
                await ctx.send(embed=create_embed("✈️ Air Defeat", f"Lost {att_loss} planes.", guilded.Color.red()))
        except Exception as e:
            logger.error(f"airattack error: {e}", exc_info=True)

    @commands.command(name='navalblockade')
    async def naval_blockade(self, ctx, target: guilded.Member = None):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("navalblockade", 20) * 60
            if not self._check_cooldown(user_id, 'navalblockade', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'navalblockade')
                await ctx.send(f"⏳ Wait {remaining}s.")
                return
            if not target:
                await ctx.send("🚢 Usage: `.navalblockade <user>`")
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            target_civ = self.civ_manager.get_civilization(str(target.id))
            if not civ or not target_civ:
                await ctx.send("❌ Both need a civilization.")
                return
            target_id = str(target.id)
            if not self._check_war(user_id, target_id):
                await ctx.send("❌ Declare war first.")
                return
            if target_id in self.blockades:
                await ctx.send("❌ Already blockaded.")
                return
            total = sum(self._get_navy(user_id).values())
            if total < 5:
                await ctx.send("❌ Need 5 ships.")
                return
            self._start_cooldown(user_id, 'navalblockade', cooldown_seconds)
            self.blockades[target_id] = {"attacker": user_id,
                                         "expires": datetime.utcnow() + timedelta(minutes=120)}
            losses = max(1, int(total * 0.2))
            self._reduce_navy(user_id, losses)
            self.civ_manager.apply_faction_effects(user_id, "naval_blockade")
            await ctx.send(embed=create_embed("🚢 Blockade Imposed",
                                              f"Target: **{target_civ['name']}**\nDuration: 120 min",
                                              guilded.Color.blue()))
        except Exception as e:
            logger.error(f"navalblockade error: {e}", exc_info=True)

    # =================================================================
    # BUY SPIES
    # =================================================================
    @commands.command(name='buyspys', aliases=['buyspies'])
    async def buy_spies(self, ctx, amount: int = None):
        if amount is None or amount < 1:
            await ctx.send(f"🕵️ Usage: `.buyspys <amount>` — {SPY_BUY_COST} gold each.")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ Need a civilization.")
            return
        cost = amount * SPY_BUY_COST
        if not self.civ_manager.can_afford(user_id, {"gold": cost}):
            await ctx.send(f"❌ Need {format_number(cost)} gold.")
            return
        self.civ_manager.spend_resources(user_id, {"gold": cost})
        self.civ_manager.update_military(user_id, {"spies": amount})
        self.civ_manager.apply_faction_effects(user_id, "train_spies")
        await ctx.send(f"🕵️ Recruited {format_number(amount)} spies "
                       f"(total: {format_number(civ['military']['spies'] + amount)}).")

    # =================================================================
    # QUICK ATTACK (legacy — tactical panel is preferred)
    # =================================================================
    @commands.command(name='attack')
    async def attack_civilization(self, ctx, target: guilded.Member = None, level: int = 5):
        try:
            user_id = str(ctx.author.id)
            cooldown_seconds = config.COOLDOWNS.get("attack", 3) * 60
            if not self._check_cooldown(user_id, 'attack', cooldown_seconds):
                remaining = self._get_cooldown_remaining(user_id, 'attack')
                await ctx.send(f"⏳ Wait {remaining // 60}m {remaining % 60}s. "
                               f"*Tip: `.tactics @user` for the tactical panel.*")
                return
            if not target:
                await ctx.send("⚔️ **Direct Attack** — `.attack <user> <level 1-10>`\n"
                               "*For tactical control use `.tactics <user>`.*")
                return
            if not 1 <= level <= 10:
                await ctx.send("❌ Level must be 1–10.")
                return
            if not await self.check_civil_war_and_proceed(ctx, user_id):
                return
            civ = self.civ_manager.get_civilization(user_id)
            target_civ = self.civ_manager.get_civilization(str(target.id))
            if not civ or not target_civ:
                await ctx.send("❌ Both need a civilization.")
                return
            target_id = str(target.id)
            if target_id == user_id:
                await ctx.send("❌ Can't attack yourself.")
                return
            if civ['military']['soldiers'] < 10:
                await ctx.send("❌ Need 10 soldiers.")
                return
            if not self._check_war(user_id, target_id):
                await ctx.send("❌ Declare war first.")
                return
            shares_border = self._do_attackers_border_defender(user_id, target_id)
            att = self._calculate_military_strength(civ) * (0.5 + (level - 1) * (1.5 / 9))
            dfn = self._calculate_military_strength(target_civ)
            att_roll = random.uniform(0.8, 1.2)
            def_roll = random.uniform(0.8, 1.2)
            if not shares_border:
                def_roll *= 1.5
                await ctx.send("🛡️ Defensive advantage (+50%).")
            if civ.get('ideology') == 'fascism': att_roll *= 1.1
            if target_civ.get('ideology') == 'fascism': def_roll *= 1.1
            if civ.get('ideology') == 'destruction': att_roll *= 1.15
            if self.civ_manager.consume_lucky_strike(user_id):
                att_roll *= 2.0
            fa = att * att_roll
            fd = dfn * def_roll
            soldier_cost = int(10 * (1 + (level - 1) * 0.1))
            gold_cost = int(200 * (1 + (level - 1) * 0.15))
            if civ['military']['soldiers'] < soldier_cost or civ['resources']['gold'] < gold_cost:
                await ctx.send("❌ Not enough soldiers or gold.")
                return
            self._start_cooldown(user_id, 'attack', cooldown_seconds)
            self.civ_manager.update_military(user_id, {"soldiers": -soldier_cost})
            self.civ_manager.update_resources(user_id, {"gold": -gold_cost})
            if fa > fd:
                margin = fa / max(1, fd)
                await self._process_attack_victory(ctx, user_id, target_id, civ, target_civ, margin, level)
                self.civ_manager.apply_faction_effects(user_id, "attack")
                self.civ_manager.apply_faction_effects(user_id, "battle_victory")
                # Province capture for quick attack too
                captured = await self._capture_provinces(
                    ctx, user_id, target_id, margin, "consolidate", civ, target_civ
                )
                if captured:
                    self.db.log_event(user_id, "quick_attack_capture", "Quick Attack Capture",
                                      f"Seized {', '.join(captured)} from {target_civ['name']}.")
            else:
                margin = fd / max(1, fa)
                await self._process_attack_defeat(ctx, user_id, target_id, civ, target_civ, margin, level)
                self.civ_manager.apply_faction_effects(user_id, "attack")
                self.civ_manager.apply_faction_effects(user_id, "battle_defeat")
        except Exception as e:
            logger.error(f"attack error: {e}", exc_info=True)

    # =================================================================
    # BATTLE SCENARIOS
    # =================================================================
    BATTLE_SCENARIOS = {
        "on_win": {
            "title": "🏆 Victory! What next, commander?",
            "description": "Your forces have broken through the enemy line.",
            "choices": {
                "pursue": {"label": "Pursue", "emoji": "🏃",
                           "desc": "Chase the fleeing enemy. Higher casualties, more spoils.",
                           "effects": {"extra_spoils_mult": 1.30, "extra_own_losses_mult": 1.20}},
                "consolidate": {"label": "Consolidate", "emoji": "🛡️",
                                "desc": "Hold the line. Fewer own losses, less loot.",
                                "effects": {"extra_spoils_mult": 0.70, "extra_own_losses_mult": 0.60, "morale_bonus": 5}},
                "loot": {"label": "Loot", "emoji": "💰",
                         "desc": "Take everything of value. Extra gold, less territory.",
                         "effects": {"extra_gold_mult": 1.50, "territory_mult": 0.30}},
                "encircle": {"label": "Encircle", "emoji": "🔗",
                             "desc": "Push deeper to surround. Chance at an extra province.",
                             "effects": {"extra_province_chance": 0.25, "extra_own_losses_mult": 1.35}},
            },
        },
        "on_loss": {
            "title": "💀 Defeat. What are your orders?",
            "description": "Your attack has collapsed. The enemy is pushing back.",
            "choices": {
                "retreat": {"label": "Retreat", "emoji": "🏳️",
                            "desc": "Fall back. Fewer losses, morale suffers.",
                            "effects": {"extra_own_losses_mult": 0.50, "morale_bonus": -5, "happiness_change": -3}},
                "hold": {"label": "Hold", "emoji": "🛡️",
                         "desc": "Stand and fight. Take the losses, no retreat.",
                         "effects": {"extra_own_losses_mult": 1.30, "morale_bonus": 3}},
                "counter": {"label": "Counter-attack", "emoji": "⚔️",
                            "desc": "Throw reserves in for one more push. High risk.",
                            "effects": {"counter_attack": True, "extra_own_losses_mult": 1.50}},
                "rally": {"label": "Rally", "emoji": "📣",
                          "desc": "Accept the loss but inspire the people.",
                          "effects": {"extra_own_losses_mult": 1.10, "happiness_change": 8}},
            },
        },
    }

    class _CustomStrategyModal(guilded.ui.Modal, title="Write Your Own Strategy"):
        def __init__(self, parent_view):
            super().__init__()
            self.parent_view = parent_view
            self.strategy_input = guilded.ui.TextInput(
                label="Your strategy",
                style=guilded.TextStyle.paragraph,
                placeholder="e.g. Feign retreat, then swing around the flank.",
                min_length=5, max_length=300, required=True,
            )
            self.add_item(self.strategy_input)

        async def on_submit(self, interaction: guilded.Interaction):
            if interaction.user.id != self.parent_view.user_id:
                await interaction.response.send_message("Not your battle.", ephemeral=True)
                return
            self.parent_view.custom_text = str(self.strategy_input.value)
            self.parent_view.choice = "custom"
            for item in self.parent_view.children:
                item.disabled = True
            await interaction.response.send_message("✍️ Strategy submitted.", ephemeral=True)
            self.parent_view.stop()

    class BattleScenarioView(guilded.ui.View):
        def __init__(self, user_id, choices, timeout=60.0):
            super().__init__(timeout=timeout)
            self.user_id = user_id
            self.choice = None
            self.custom_text = None
            for key, data in choices.items():
                button = guilded.ui.Button(
                    label=data["label"], emoji=data.get("emoji"),
                    style=guilded.ButtonStyle.primary,
                )
                button.callback = self._make_callback(key)
                self.add_item(button)
            custom_btn = guilded.ui.Button(
                label="Write your own", emoji="✍️",
                style=guilded.ButtonStyle.secondary,
            )
            custom_btn.callback = self._custom_callback
            self.add_item(custom_btn)

        def _make_callback(self, key):
            async def callback(interaction):
                if interaction.user.id != self.user_id:
                    await interaction.response.send_message("Not your battle.", ephemeral=True); return
                if self.choice is not None:
                    await interaction.response.send_message("Already chosen.", ephemeral=True); return
                self.choice = key
                for item in self.children:
                    item.disabled = True
                try:
                    await interaction.response.edit_message(view=self)
                except Exception:
                    pass
                self.stop()
            return callback

        async def _custom_callback(self, interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your battle.", ephemeral=True); return
            if self.choice is not None:
                await interaction.response.send_message("Already chosen.", ephemeral=True); return
            await interaction.response.send_modal(MilitaryCommands._CustomStrategyModal(self))

    async def _run_scenario(self, ctx, user_id, scenario_key, context_text):
        scenario = self.BATTLE_SCENARIOS.get(scenario_key)
        if not scenario:
            return None
        embed = create_embed(
            scenario["title"],
            f"{context_text}\n\n{scenario['description']}\n\n"
            f"*Pick a pre-made strategy or write your own.*",
            guilded.Color.gold(),
        )
        for key, choice in scenario["choices"].items():
            embed.add_field(
                name=f"{choice['emoji']} {choice['label']}",
                value=choice["desc"], inline=False,
            )
        view = self.BattleScenarioView(int(user_id), scenario["choices"], timeout=60.0)
        await ctx.send(embed=embed, view=view)
        await view.wait()
        if view.choice is None:
            first_key = list(scenario["choices"].keys())[0]
            return dict(scenario["choices"][first_key]["effects"])
        if view.choice == "custom":
            custom_text = (view.custom_text or "").strip()
            if not custom_text:
                first_key = list(scenario["choices"].keys())[0]
                return dict(scenario["choices"][first_key]["effects"])
            rating = await self._ai_rate_tactic(custom_text, context_text)
            if not rating:
                first_key = list(scenario["choices"].keys())[0]
                return dict(scenario["choices"][first_key]["effects"])
            score = float(rating.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            await ctx.send(embed=create_embed(
                "🎖️ Strategy Reviewed",
                f"**Verdict:** {rating.get('verdict','—')}\n"
                f"**Score:** {score*100:.0f}/100\n"
                f"*{rating.get('reasoning','')}*",
                guilded.Color.purple(),
            ))
            return {
                "extra_spoils_mult": 1.0 + (score - 0.5) * 0.4,
                "extra_own_losses_mult": 1.0 - (score - 0.5) * 0.3,
            }
        choice_data = scenario["choices"].get(view.choice)
        return dict(choice_data["effects"]) if choice_data else None

    # =================================================================
    # TACTICAL MATH
    # =================================================================
    def _sum_division_power(self, division_docs, doctrine):
        attack = 0.0
        defense = 0.0
        roles_present = []
        total_size = 0

        for d in division_docs:
            role_key = d.get("type", "")
            role = config.DIVISION_ROLES.get(role_key)
            if not role:
                continue
            size = int(d.get("size", 0))
            roles_present.append(role_key)
            total_size += size
            attack += size * role["attack_mult"]
            defense += size * role["defense_mult"]

        synergy_attack_mult = 1.0
        synergy_defense_mult = 1.0
        applied_synergies = []
        for pair, bonus in config.COMBINED_ARMS.items():
            r1, r2 = pair
            if r1 in roles_present and r2 in roles_present:
                if "attack" in bonus:
                    synergy_attack_mult *= (1 + bonus["attack"])
                if "defense" in bonus:
                    synergy_defense_mult *= (1 + bonus["defense"])
                applied_synergies.append(bonus["name"])

        return {
            "attack_base": attack,
            "defense_base": defense,
            "attack": attack,
            "defense": defense,
            "roles": roles_present,
            "total_size": total_size,
            "synergies": applied_synergies,
            "synergy_attack_mult": synergy_attack_mult,
            "synergy_defense_mult": synergy_defense_mult,
        }

    def _direction_multiplier(self, direction):
        if not direction:
            return 1.0
        if direction in {"NE", "SE", "SW", "NW"}:
            return 1.20
        if direction in {"N", "E", "S", "W"}:
            return 1.05
        return 1.0

    def _technique_counter_multiplier(self, attacker_technique, defender_technique):
        if not attacker_technique or not defender_technique:
            return 1.0
        a_def = config.TECHNIQUES.get(attacker_technique, {})
        d_def = config.TECHNIQUES.get(defender_technique, {})
        if a_def.get("counter") == defender_technique:
            return 1.25
        if d_def.get("counter") == attacker_technique:
            return 0.80
        return 1.0

    def _apply_instructions(self, stats, instruction_keys):
        applied = []
        for key in instruction_keys:
            ins = config.OPERATIONAL_INSTRUCTIONS.get(key)
            if not ins: continue
            effects = ins.get("effect", {})
            if "attack" in effects:
                stats["attack"] *= (1 + effects["attack"])
            if "defense" in effects:
                stats["defense"] *= (1 + effects["defense"])
            if "casualty" in effects:
                stats["casualty_mult"] = stats.get("casualty_mult", 1.0) * (1 + effects["casualty"])
            applied.append(ins["name"])
        return stats, applied

    def _apply_phases(self, stats, opening, main, exploitation):
        applied = []
        phases = config.BATTLE_PHASES
        for key, opts in (("opening", opening), ("main", main), ("exploitation", exploitation)):
            if not key or not opts:
                continue
            opt = phases.get(key, {}).get("options", {}).get(opts)
            if not opt: continue
            eff = opt.get("effect", {})
            for k, v in eff.items():
                if k in ("attack", "own_attack"):
                    stats["attack"] *= (1 + v)
                elif k in ("defense", "own_defense"):
                    stats["defense"] *= (1 + v)
                elif k == "casualty":
                    stats["casualty_mult"] = stats.get("casualty_mult", 1.0) * (1 + v)
                elif k == "extra_loot":
                    stats["loot_mult"] = stats.get("loot_mult", 1.0) * (1 + v)
            applied.append(opt["name"])
        return stats, applied

    def _apply_general(self, stats, general):
        if not general:
            return stats, []
        applied = []
        pos = config.GENERAL_POSITIVE_TRAITS.get(general.get("positive_trait"), {})
        neg = config.GENERAL_NEGATIVE_TRAITS.get(general.get("negative_trait"), {})
        if pos.get("effect") == "attack_mult_bonus":
            stats["attack"] *= pos["value"]
        elif pos.get("effect") == "defense_mult_bonus":
            stats["defense"] *= pos["value"]
        if pos.get("name"):
            applied.append(f"✅ {pos['name']}")
        if neg.get("effect") == "casualty_mult":
            stats["casualty_mult"] = stats.get("casualty_mult", 1.0) * neg["value"]
        elif neg.get("effect") == "attack_mult_penalty":
            stats["attack"] *= neg["value"]
        if neg.get("name"):
            applied.append(f"⚠️ {neg['name']}")
        return stats, applied

    # =================================================================
    # TACTICAL RESOLUTION — this is where tactics matter most
    # =================================================================
    @commands.command(name='attackresolve')
    async def resolve_pending_attack(self, ctx, attack_id: str = None):
        user_id = str(ctx.author.id)
        if not attack_id:
            pending = self.db.get_pending_attacks_for_user(user_id)
            if not pending:
                await ctx.send("📭 No pending attack orders. Use `.tactics @user`.")
                return
            await ctx.send(f"Pending orders: {', '.join('`' + p['id'] + '`' for p in pending)}")
            return
        order = self.db.get_pending_attack(attack_id)
        if not order:
            await ctx.send("❌ Order not found or expired.")
            return
        if str(order.get("attacker_id")) != user_id:
            await ctx.send("❌ Not your order.")
            return
        if order.get("status") != "pending":
            await ctx.send(f"❌ Order status: `{order.get('status')}`.")
            return
        await self._resolve_tactical_order(ctx, order)

    async def _resolve_tactical_order(self, ctx, order):
        attacker_id = str(order["attacker_id"])
        defender_id = str(order["defender_id"])
        attacker_civ = self.civ_manager.get_civilization(attacker_id)
        defender_civ = self.civ_manager.get_civilization(defender_id)
        if not attacker_civ or not defender_civ:
            await ctx.send("❌ One of the civilizations no longer exists.")
            self.db.delete_pending_attack(order["id"])
            return

        division_docs = []
        for div_id in order.get("division_ids", []):
            d = self.db.get_division(div_id)
            if d and str(d.get("owner_id")) == attacker_id:
                division_docs.append(d)
        if not division_docs:
            await ctx.send("❌ No valid divisions in this order.")
            self.db.delete_pending_attack(order["id"])
            return

        # Technique cost
        technique = order.get("technique")
        tech_def = config.TECHNIQUES.get(technique, {})
        tech_cost = tech_def.get("cost", {})
        if tech_cost and not self.civ_manager.can_afford(attacker_id, tech_cost):
            await ctx.send(f"❌ Cannot afford technique cost: {tech_cost}.")
            return
        if tech_cost:
            self.civ_manager.spend_resources(attacker_id, tech_cost)

        attacker_doctrine = attacker_civ.get("doctrine")
        defender_doctrine = defender_civ.get("doctrine")
        mentality = order.get("mentality", "balanced")
        ment = config.MENTALITIES.get(mentality, config.MENTALITIES["balanced"])

        # ===== ATTACKER STACK =====
        att_stats = self._sum_division_power(division_docs, attacker_doctrine)
        att_stats["attack_raw"] = att_stats["attack"]

        doc_att = config.DOCTRINES.get(attacker_doctrine, {}).get("attack_mult", 1.0)
        doc_def = config.DOCTRINES.get(attacker_doctrine, {}).get("defense_mult", 1.0)
        doc_cas = config.DOCTRINES.get(attacker_doctrine, {}).get("casualty_mult", 1.0)
        att_stats["attack"] *= doc_att
        att_stats["defense"] *= doc_def
        att_stats["attack"] *= tech_def.get("attack_mult", 1.0)
        att_stats["attack"] *= ment.get("attack_mult", 1.0)
        att_stats["casualty_mult"] = doc_cas * ment.get("casualty_mult", 1.0)
        att_stats["loot_mult"] = 1.0

        general = None
        if order.get("general_id"):
            general = self.db.get_general(order["general_id"])
        att_stats, general_notes = self._apply_general(att_stats, general)

        att_stats, instr_notes = self._apply_instructions(att_stats, order.get("instructions", []))
        att_stats, phase_notes = self._apply_phases(
            att_stats,
            order.get("phase_opening"),
            order.get("phase_main"),
            order.get("phase_exploitation"),
        )

        att_stats["attack"] *= att_stats["synergy_attack_mult"]
        att_stats["defense"] *= att_stats["synergy_defense_mult"]

        dir_mult = self._direction_multiplier(order.get("direction"))
        att_stats["attack"] *= dir_mult

        # Technique counter against defender's "signature" technique
        defender_sig_tech = None
        for tk, t in config.TECHNIQUES.items():
            if defender_doctrine and defender_doctrine in t.get("doctrines", []):
                defender_sig_tech = tk
                break
        counter_mult = self._technique_counter_multiplier(technique, defender_sig_tech)
        att_stats["attack"] *= counter_mult

        # ===== AI PLAN BONUS =====
        ai_score = order.get("ai_plan_score")
        ai_mult = 1.0
        if ai_score is not None:
            try:
                ai_score = float(ai_score)
                ai_mult = 1.0 + (ai_score - 0.5) * 0.5  # +/− 25%
                att_stats["attack"] *= ai_mult
            except Exception:
                ai_mult = 1.0

        # ===== DEFENDER STACK =====
        def_division_docs = self.db.get_user_divisions(defender_id)
        def_stats = self._sum_division_power(def_division_docs, defender_doctrine)
        doc_def_def = config.DOCTRINES.get(defender_doctrine, {}).get("defense_mult", 1.0)
        def_stats["defense"] *= doc_def_def
        def_stats["defense"] *= def_stats["synergy_defense_mult"]

        home_defense_bonus = 1.15
        def_stats["defense"] *= home_defense_bonus

        border = self._get_border_info(defender_id)
        if border.get("has_border"):
            def_stats["defense"] *= 1.25

        if not def_division_docs:
            def_stats["defense"] = (defender_civ['military']['soldiers'] * 10
                                    * doc_def_def
                                    * home_defense_bonus)

        # ===== COMBAT ROLL =====
        att_power_base = att_stats["attack"]
        def_power_base = def_stats["defense"]

        att_power = att_power_base * random.uniform(0.90, 1.10)
        def_power = def_power_base * random.uniform(0.90, 1.10)

        if self.civ_manager.consume_lucky_strike(attacker_id):
            att_power *= 2.0
            await ctx.send("🍀 **Lucky Strike!** Attack power doubled.")

        victory = att_power > def_power
        ratio = (att_power / max(1, def_power)) if victory else (def_power / max(1, att_power))
        ratio_capped = min(ratio, 8.0)

        # ===== CASUALTIES =====
        base_att_casualty = 0.04 + (0.10 * (1 / max(1, ratio_capped)))
        base_def_casualty = 0.06 + (0.14 * (1 / max(1, ratio_capped)))
        att_loss_pct = base_att_casualty * att_stats["casualty_mult"]
        def_loss_pct = base_def_casualty

        att_total_size = sum(d.get("size", 0) for d in division_docs)
        def_total_size = sum(d.get("size", 0) for d in def_division_docs) if def_division_docs else defender_civ['military']['soldiers']

        att_losses = max(1, int(att_total_size * att_loss_pct))
        def_losses = max(1, int(def_total_size * def_loss_pct))

        for d in division_docs:
            portion = d["size"] / max(1, att_total_size)
            loss = int(att_losses * portion)
            new_size = max(0, d["size"] - loss)
            if new_size <= 0:
                self.db.delete_division(d["id"])
            else:
                self.db.update_division(d["id"], {"size": new_size,
                                                   "morale": max(0, d.get("morale", 100) - 10)})

        if def_division_docs:
            for d in def_division_docs:
                portion = d["size"] / max(1, def_total_size)
                loss = int(def_losses * portion)
                new_size = max(0, d["size"] - loss)
                if new_size <= 0:
                    self.db.delete_division(d["id"])
                else:
                    self.db.update_division(d["id"], {"size": new_size})
        else:
            self.civ_manager.update_military(defender_id, {"soldiers": -def_losses})

        # ===== RESULT EMBED =====
        result_color = guilded.Color.green() if victory else guilded.Color.red()
        result_embed = create_embed(
            "⚔️ Engagement Resolved" if victory else "💀 Engagement Lost",
            f"**{attacker_civ['name']}** vs **{defender_civ['name']}**\n"
            f"Direction: {config.ATTACK_DIRECTIONS.get(order.get('direction','N'), {}).get('emoji','')} "
            f"{config.ATTACK_DIRECTIONS.get(order.get('direction','N'), {}).get('name','')}\n"
            f"Technique: {tech_def.get('emoji','')} {tech_def.get('name','—')}",
            result_color,
        )
        result_embed.add_field(
            name="Attacker",
            value=(f"Base: **{int(att_stats['attack_raw']):,}**\n"
                   f"Multiplier: **×{(att_power_base / max(1, att_stats['attack_raw'])):.2f}**\n"
                   f"Final: **{int(att_power):,}**\n"
                   f"Losses: **{att_losses:,}**"),
            inline=True,
        )
        result_embed.add_field(
            name="Defender",
            value=(f"Base: **{int(def_stats['defense_base']):,}**\n"
                   f"Multiplier: **×{(def_power_base / max(1, def_stats['defense_base'])):.2f}**\n"
                   f"Final: **{int(def_power):,}**\n"
                   f"Losses: **{def_losses:,}**"),
            inline=True,
        )
        if general_notes:
            result_embed.add_field(name="Commander", value=" · ".join(general_notes), inline=False)
        if instr_notes:
            result_embed.add_field(name="Instructions", value=" · ".join(instr_notes[:5]), inline=False)
        if phase_notes:
            result_embed.add_field(name="Phases", value=" · ".join(phase_notes[:5]), inline=False)
        if att_stats.get("synergies"):
            result_embed.add_field(name="Combined Arms",
                                   value=" · ".join(att_stats["synergies"][:5]), inline=False)
        if ai_score is not None:
            result_embed.add_field(
                name="AI Plan",
                value=f"Score {ai_score*100:.0f}/100  ·  attack ×{ai_mult:.2f}",
                inline=False,
            )
        result_embed.set_footer(
            text=f"Tactical: ×{counter_mult:.2f} | Direction: ×{dir_mult:.2f} | AI: ×{ai_mult:.2f}"
        )
        await ctx.send(embed=result_embed)

        # ===== SPOILS + PROVINCE CAPTURE =====
        if victory:
            scenario_eff = await self._run_scenario(
                ctx, attacker_id, "on_win",
                f"**{attacker_civ['name']}** defeated **{defender_civ['name']}**."
            ) or {}
            loot_mult = att_stats.get("loot_mult", 1.0) * scenario_eff.get("extra_spoils_mult", 1.0)
            territory_mult = scenario_eff.get("territory_mult", 1.0)
            extra_gold = scenario_eff.get("extra_gold_mult", 1.0)
            loot_ratio_boost = min(2.0, 0.6 + ratio_capped * 0.2)

            spoils = {
                "gold": min(int(defender_civ['resources']['gold'] * 0.10 * loot_mult * extra_gold * loot_ratio_boost), defender_civ['resources']['gold']),
                "food": min(int(defender_civ['resources']['food'] * 0.08 * loot_mult * loot_ratio_boost), defender_civ['resources']['food']),
                "stone": min(int(defender_civ['resources']['stone'] * 0.08 * loot_mult * loot_ratio_boost), defender_civ['resources']['stone']),
                "wood": min(int(defender_civ['resources']['wood'] * 0.08 * loot_mult * loot_ratio_boost), defender_civ['resources']['wood']),
            }
            territory = int(defender_civ['territory']['land_size'] * 0.03 * territory_mult * min(2.0, ratio_capped))

            self.civ_manager.update_resources(attacker_id, spoils)
            self.civ_manager.update_resources(defender_id, {r: -a for r, a in spoils.items()})
            self.civ_manager.update_territory(attacker_id, {"land_size": territory})
            self.civ_manager.update_territory(defender_id, {"land_size": -territory})
            self.civ_manager.apply_faction_effects(attacker_id, "battle_victory")
            self.civ_manager.apply_faction_effects(defender_id, "battle_defeat")

            spoils_text = "\n".join(f"{k}: {format_number(v)}" for k, v in spoils.items() if v > 0)
            await ctx.send(embed=create_embed(
                "🏆 Victory!",
                f"Spoils:\n{spoils_text or 'None'}\n\n"
                f"Land gained: {format_number(territory)} km²",
                guilded.Color.gold(),
            ))

            # Province capture — no cap, no last-province protection
            await self._capture_provinces(
                ctx, attacker_id, defender_id, ratio_capped,
                order.get("phase_exploitation"), attacker_civ, defender_civ,
            )
        else:
            scenario_eff = await self._run_scenario(
                ctx, attacker_id, "on_loss",
                f"**{attacker_civ['name']}** was defeated by **{defender_civ['name']}**."
            ) or {}
            morale_penalty = -10 + scenario_eff.get("happiness_change", 0)
            self.civ_manager.update_population(attacker_id, {"happiness": morale_penalty})
            self.civ_manager.apply_faction_effects(attacker_id, "battle_defeat")
            self.civ_manager.apply_faction_effects(defender_id, "battle_victory")

        # AI narrative
        try:
            narrative = await self._ai_rate_text(
                "You are a wire-service reporter. Write 2-3 sentences, no headers.",
                f"Battle: {attacker_civ['name']} vs {defender_civ['name']}. "
                f"Result: {'attacker victory' if victory else 'attacker defeat'}. "
                f"Intensity: {min(10, max(1, int(att_total_size / 1000)))}/10.",
                max_tokens=120, temperature=0.8,
            )
            if narrative:
                await ctx.send(f"📰 {narrative.strip()}")
        except Exception:
            pass

        self.db.update_pending_attack(order["id"], {
            "status": "resolved",
            "resolved_at": datetime.utcnow().isoformat(),
        })
        self.db.log_event(attacker_id, "tactical_attack", "Tactical Attack",
                          f"vs {defender_civ['name']} | {'victory' if victory else 'defeat'}")
        self.db.log_event(defender_id, "tactical_defense", "Tactical Defense",
                          f"vs {attacker_civ['name']} | {'victory' if not victory else 'defeat'}")

    # =================================================================
    # LEGACY VICTORY/DEFEAT PROCESSORS
    # =================================================================
    async def _process_attack_victory(self, ctx, attacker_id, defender_id, attacker_civ,
                                      defender_civ, margin, level):
        try:
            dmg = 0.5 + (level - 1) * (1.5 / 9)
            att_loss = min(random.randint(2, 8), attacker_civ['military']['soldiers'])
            def_loss = min(int(att_loss * margin * dmg), defender_civ['military']['soldiers'])

            scenario_eff = await self._run_scenario(
                ctx, str(attacker_id), "on_win",
                f"**{attacker_civ['name']}** defeated **{defender_civ['name']}**."
            ) or {}

            loot_mult = float(scenario_eff.get("extra_spoils_mult", 1.0))
            own_loss_mult = float(scenario_eff.get("extra_own_losses_mult", 1.0))
            gold_mult = float(scenario_eff.get("extra_gold_mult", 1.0))
            territory_mult = float(scenario_eff.get("territory_mult", 1.0))
            morale_bonus = int(scenario_eff.get("morale_bonus", 0))
            att_loss = max(1, int(att_loss * own_loss_mult))

            spoils = {
                "gold": min(int(defender_civ['resources']['gold'] * 0.15 * dmg * loot_mult * gold_mult), defender_civ['resources']['gold']),
                "food": min(int(defender_civ['resources']['food'] * 0.10 * dmg * loot_mult), defender_civ['resources']['food']),
                "stone": min(int(defender_civ['resources']['stone'] * 0.10 * dmg * loot_mult), defender_civ['resources']['stone']),
                "wood": min(int(defender_civ['resources']['wood'] * 0.10 * dmg * loot_mult), defender_civ['resources']['wood']),
            }
            territory = min(int(defender_civ['territory']['land_size'] * 0.05 * dmg * territory_mult),
                            defender_civ['territory']['land_size'])

            self.civ_manager.update_military(attacker_id, {"soldiers": -att_loss})
            self.civ_manager.update_military(defender_id, {"soldiers": -def_loss})
            self.civ_manager.update_resources(attacker_id, spoils)
            self.civ_manager.update_resources(defender_id, {r: -a for r, a in spoils.items()})
            self.civ_manager.update_territory(attacker_id, {"land_size": territory})
            self.civ_manager.update_territory(defender_id, {"land_size": -territory})
            if morale_bonus:
                self.civ_manager.update_population(attacker_id, {"happiness": morale_bonus})

            spoils_text = "\n".join(f"{k}: {format_number(v)}" for k, v in spoils.items() if v > 0)
            embed = create_embed("⚔️ Victory",
                                 f"**{attacker_civ['name']}** → **{defender_civ['name']}**",
                                 guilded.Color.green())
            embed.add_field(name="Losses", value=f"You: {att_loss} | Them: {def_loss}", inline=True)
            embed.add_field(name="Spoils", value=spoils_text or "None", inline=True)
            embed.add_field(name="Territory", value=f"+{format_number(territory)} km²", inline=True)
            await ctx.send(embed=embed)
            self.db.log_event(attacker_id, "victory", "Victory", f"Beat {defender_civ['name']}")
        except Exception as e:
            logger.error(f"victory wrapper error: {e}", exc_info=True)

    async def _process_attack_defeat(self, ctx, attacker_id, defender_id, attacker_civ,
                                     defender_civ, margin, level):
        try:
            dmg = 0.5 + (level - 1) * (1.5 / 9)
            att_loss = min(int(random.randint(5, 15) * margin * dmg), attacker_civ['military']['soldiers'])
            def_loss = min(random.randint(2, 5), defender_civ['military']['soldiers'])

            scenario_eff = await self._run_scenario(
                ctx, str(attacker_id), "on_loss",
                f"**{attacker_civ['name']}** was defeated by **{defender_civ['name']}**."
            ) or {}
            own_loss_mult = float(scenario_eff.get("extra_own_losses_mult", 1.0))
            happiness_delta = int(scenario_eff.get("happiness_change", 0))
            att_loss = max(1, int(att_loss * own_loss_mult))

            self.civ_manager.update_military(attacker_id, {"soldiers": -att_loss})
            self.civ_manager.update_military(defender_id, {"soldiers": -def_loss})
            self.civ_manager.update_population(attacker_id, {"happiness": -10 + happiness_delta})

            embed = create_embed("⚔️ Defeat",
                                 f"**{attacker_civ['name']}** lost to **{defender_civ['name']}**",
                                 guilded.Color.red())
            embed.add_field(name="Losses", value=f"You: {att_loss} | Them: {def_loss}", inline=True)
            await ctx.send(embed=embed)
            self.db.log_event(attacker_id, "defeat", "Defeat", f"Lost to {defender_civ['name']}")
        except Exception as e:
            logger.error(f"defeat wrapper error: {e}", exc_info=True)


async def setup(bot):
    await bot.add_cog(MilitaryCommands(bot))
