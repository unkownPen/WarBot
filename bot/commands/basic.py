import random
import discord
import os
import aiohttp
import asyncio
import logging
import json
from typing import List, Optional, Literal, Tuple, Dict
from datetime import datetime, timedelta
from collections import defaultdict, deque
from discord.ext import commands
from discord import app_commands
from bot.utils import (
    format_number, get_ascii_art, create_embed,
    get_all_faction_warnings, get_faction_status_emoji,
)
from bot import config

# Import subregion data from territory.py
from bot.commands.territory import (
    PROVINCES, SUBREGION_TO_CONTINENT, SUBREGION_DATA,
    ALL_SUBREGIONS, FORBIDDEN_START_PROVINCES,
)

logger = logging.getLogger(__name__)

MAX_CONVERSATION_HISTORY = 100
CONVERSATION_TIMEOUT = 1800


# =================================================================
# WARHELP — hardcoded hints + auto-discovery
# =================================================================

# Canonical categories. Order here = order shown in .warhelp.
CATEGORY_META: Dict[str, Tuple[str, str]] = {
    "basic":         ("🏛️ Basic Commands",        "Essential civilization management"),
    "ideology":      ("🏛️ Ideologies",            "Government types and their bonuses"),
    "factions":      ("⚖️ Factions",              "Internal power blocs and civil war risk"),
    "economy":       ("💰 Economy",               "Gathering, taxes, corporations, megaprojects"),
    "bank":          ("🏦 Banking & Sanctions",   "Deposits, loans, sanctions"),
    "military":      ("⚔️ Military",              "War, borders, navy, airforce"),
    "diplomacy":     ("🤝 Diplomacy",             "Alliances, trade, messages, peace"),
    "hyperitems":    ("💎 HyperItems",            "Powerful one-time items"),
    "store":         ("🏪 Store",                 "Upgrades and Black Market"),
    "territory":     ("🗺️ Territory & Countryballs", "Expansion, maps, collection"),
    "industrial":    ("🏭 Industrial Revolution", "Micromanagement challenge"),
    "other":         ("📌 Other",                 "Miscellaneous"),
}

# Hardcoded (command -> (category, description)). If a command exists in
# the bot but is NOT here, we fall back to keyword-based auto-categorization
# so new commands show up without editing this file.
HARDCODED_HELP: Dict[str, Tuple[str, str]] = {
    # --- Basic ---
    "start":      ("basic", "Start a new civilization with a cinematic intro"),
    "status":     ("basic", "View your civilization status, factions, and sanctions"),
    "reset":      ("basic", "Reset your civilization (irreversible!)"),
    "regions":    ("basic", "View or select your civilization's region"),
    "sv":         ("basic", "Start a saved chat with the AI (no timeout)"),
    "svc":        ("basic", "Close and delete your saved chat"),
    "victory":    ("basic", "Check your progress toward victory conditions"),
    "warhelp":    ("basic", "Show this help menu"),
    "updates":    ("basic", "Show the roadmap and update log"),
    "map":        ("basic", "Show the world map"),

    # --- Ideology ---
    "ideology":   ("ideology", "Choose your civilization's government ideology"),

    # --- Factions ---
    "factions":   ("factions", "View your three internal factions and warnings"),

    # --- Economy ---
    "gather":       ("economy", "Gather random resources from your territory"),
    "work":         ("economy", "Employ citizens to work and gain immediate gold"),
    "farm":         ("economy", "Farm food for your civilization"),
    "mine":         ("economy", "Mine stone and wood from your territory"),
    "harvest":      ("economy", "Large harvest of food"),
    "drill":        ("economy", "Extract rare minerals – requires Tech 2"),
    "labor":        ("economy", "Forced labor for wood/stone – requires Tech 3"),
    "raidcaravan":  ("economy", "Raid NPC merchant caravans"),
    "tax":          ("economy", "Collect taxes (capped at 150K)"),
    "lottery":      ("economy", "Gamble gold for a chance at the jackpot"),
    "invest":       ("economy", "Invest gold for delayed profit"),
    "advertise":    ("economy", "Run promotional campaigns to attract citizens"),
    "census":       ("economy", "Display current gold and population status"),
    "recruit":      ("economy", "Convert citizens into soldiers"),
    "buysoldiers":  ("economy", "Buy soldiers with gold (20 gold each)"),
    "buytech":      ("economy", "Purchase a tech level (2000 gold, max 10)"),
    "cheerup":      ("economy", "Boost happiness toward 100 for 2000 gold"),
    "cheer":        ("economy", "Spread cheer (+happiness, costs 50 gold)"),
    "festival":     ("economy", "Hold a grand festival to boost happiness"),
    "burn":         ("economy", "Burn excess resources down to 1000 each"),
    "immigration":  ("economy", "Open borders to gain citizens (risk of riots)"),
    "buycard":      ("economy", "Purchase a random card for 500 gold"),
    "corporation":  ("economy", "Manage corporations (build/upgrade/list)"),
    "megaproject":  ("economy", "Build world-changing megaprojects"),
    "policy":       ("economy", "Enable/upgrade/disable policies"),
    "policieshelp": ("economy", "Show all available policies"),
    "sell":         ("economy", "Sell hyper items to wandering merchants"),
    "drive":        ("economy", "Unemploy citizens, freeing them from work"),
    "globaltrade":  ("economy", "Trade resources on the global market (blocked while sanctioned)"),
    "fish":         ("economy", "Fish for food or occasionally find treasure"),
    "revolution":   ("economy", "Tech 10 reset for permanent +100% production"),

    # --- Bank & Sanctions ---
    "bank":          ("bank", "Central bank — deposit, withdraw, loan, repay"),
    "sanction":      ("bank", "Impose economic sanctions on a target (10K gold)"),
    "liftsanction":  ("bank", "Lift your own sanction on a target"),
    "sanctions":     ("bank", "List sanctions you've imposed / received"),

    # --- Military ---
    "train":         ("military", "Train military units (2min cooldown)"),
    "find":          ("military", "Search for wandering soldiers (1min cooldown)"),
    "declare":       ("military", "Declare war on another civilization"),
    "attack":        ("military", "Launch a direct attack (3min cooldown)"),
    "siege":         ("military", "Lay siege to an enemy (10min cooldown)"),
    "stealthbattle": ("military", "Conduct a spy-based stealth attack (4min)"),
    "peace":         ("military", "Offer peace to an enemy civilization"),
    "accept_peace":  ("military", "Accept a peace offer from another civilization"),
    "addborder":     ("military", "Build a defensive border (5min cooldown)"),
    "removeborder":  ("military", "Remove your border and retrieve soldiers (2min)"),
    "rectract":      ("military", "Assign soldiers to the border (1min cooldown)"),
    "retrieve":      ("military", "Retrieve soldiers from the border (1min cooldown)"),
    "borderinfo":    ("military", "Check your border status (1min cooldown)"),
    "buildship":     ("military", "Build navy ships"),
    "buildplane":    ("military", "Build airforce planes"),
    "tech":          ("military", "Upgrade military tech (500 gold per level)"),
    "trainboost":    ("military", "Increase soldier training level (max 3)"),
    "navy":          ("military", "View your navy fleet"),
    "airforce":      ("military", "View your airforce fleet"),
    "cards":         ("military", "View or use your purchased cards"),
    "navalattack":   ("military", "Attack with your navy"),
    "airattack":     ("military", "Attack with your airforce"),
    "navalblockade": ("military", "Blockade an enemy (reduces their income 30%)"),

    # --- Diplomacy ---
    "ally":         ("diplomacy", "Propose an alliance with another civilization"),
    "acceptally":   ("diplomacy", "Accept a pending alliance proposal"),
    "rejectally":   ("diplomacy", "Reject a pending alliance proposal"),
    "break":        ("diplomacy", "Break your current alliance"),
    "send":         ("diplomacy", "Send resources to an ally"),
    "trade":        ("diplomacy", "Propose a resource trade (blocked while sanctioned)"),
    "accepttrade":  ("diplomacy", "Accept a pending trade proposal"),
    "rejecttrade":  ("diplomacy", "Reject a pending trade proposal"),
    "mail":         ("diplomacy", "Send a diplomatic message to another civilization"),
    "inbox":        ("diplomacy", "Check your pending proposals and messages"),
    "coalition":    ("diplomacy", "Form a coalition against another alliance"),
    "simplepeace":  ("diplomacy", "Simple peace offer to an enemy"),
    "peacedraft":   ("diplomacy", "Draft a custom peace deal"),
    "acceptpeace":  ("diplomacy", "Accept a peace offer"),
    "rejectpeace":  ("diplomacy", "Reject a peace offer"),
    "peaceinfo":    ("diplomacy", "View details of a peace offer"),
    "myoffers":     ("diplomacy", "View your pending peace offers"),
    "ceasefire":    ("diplomacy", "Propose a temporary ceasefire"),
    "ceasefires":   ("diplomacy", "View active ceasefires"),
    "breakceasefire": ("diplomacy", "Break an active ceasefire"),

    # --- HyperItems ---
    "laststand":   ("hyperitems", "Use Last Stand when under 500 gold"),
    "sacrifice":   ("hyperitems", "Destroy your civ and another (mutual destruction)"),
    "mirror":      ("hyperitems", "Reflects the next attack back at the attacker"),
    "nuke":        ("hyperitems", "Launch a devastating nuclear attack"),
    "obliterate":  ("hyperitems", "Completely obliterate a civilization (HyperLaser)"),
    "shield":      ("hyperitems", "Display Anti-Nuke Shield status"),
    "luckystrike": ("hyperitems", "Use Lucky Charm for guaranteed critical success"),
    "propaganda":  ("hyperitems", "Use Propaganda Kit to steal enemy soldiers"),
    "hiremercs":   ("hyperitems", "Use Mercenary Contract to hire soldiers"),
    "boosttech":   ("hyperitems", "Use Ancient Scroll to advance technology"),
    "mintgold":    ("hyperitems", "Use Gold Mint to generate gold"),
    "superharvest":("hyperitems", "Use Harvest Engine for massive food"),
    "superspy":    ("hyperitems", "Use Spy Network for elite espionage"),
    "megainvent":  ("hyperitems", "Use Tech Core for multiple tech levels"),
    "backstab":    ("hyperitems", "Use Dagger — zeroes target happiness, steals gold"),
    "bomb":        ("hyperitems", "Use Missiles for mid-tier military strike"),
    "clone":       ("hyperitems", "Use Bio-Replicator to clone your military"),
    "fakeflag":    ("hyperitems", "Use Decoy Banner to blame another civ for your attack"),
    "glitch_protocol": ("hyperitems", "Use Corrupted — randomizes the next incoming attack"),

    # --- Store ---
    "store":       ("store", "View the civilization store and purchase upgrades"),
    "blackmarket": ("store", "Purchase random HyperItems"),
    "inventory":   ("store", "View your HyperItems and store upgrades"),
    "market":      ("store", "Display information about the Black Market"),

    # --- Territory ---
    "territories":  ("territory", "List your owned provinces"),
    "states":       ("territory", "Show global state ownership"),
    "expand":       ("territory", "Claim a province (overseas requires navy)"),
    "rapidexpansion": ("territory", "Claim a province using only soldiers (2× cost)"),
    "reclaim":      ("territory", "Fight rebel-held territories during civil war (+30% boost)"),
    "civilwar":     ("territory", "View your civil war status"),
    "openpacks":    ("territory", "Unlock countryballs for completed subregions"),
    "evolve":       ("territory", "Manually check evolution for countryballs"),
    "packs":        ("territory", "View your countryball collection and progress"),
    "activate":     ("territory", "Activate a countryball as a manager"),
    "deactivate":   ("territory", "Deactivate a countryball manager"),
    "synergies":    ("territory", "Show active synergy bonuses"),

    # --- Industrial ---
    "industrial_start":   ("industrial", "Begin the Industrial Revolution"),
    "industrial_status":  ("industrial", "View all 25+ industrial stats"),
    "industrial_build":   ("industrial", "Build a factory"),
    "industrial_tech":    ("industrial", "Research technology"),
    "industrial_workers": ("industrial", "Train workers"),
    "industrial_cleanup": ("industrial", "Reduce pollution"),
    "industrial_railway": ("industrial", "Build railways"),
    "industrial_transport":("industrial", "Improve transport"),
    "industrial_army":    ("industrial", "Raise military protection"),
    "industrial_policy":  ("industrial", "Enact a new policy"),
    "industrial_import":  ("industrial", "Import raw materials"),
    "industrial_export":  ("industrial", "Export goods"),
    "industrial_steam":   ("industrial", "Research steam power"),
    "industrial_mine":    ("industrial", "Build a mine"),
    "industrial_hospital":("industrial", "Build a hospital"),
    "industrial_school":  ("industrial", "Build a school"),
    "industrial_law":     ("industrial", "Enforce law and order"),
    "industrial_trade":   ("industrial", "Diplomatic trade"),
    "industrial_aid":     ("industrial", "Request foreign aid"),
    "industrial_suppress":("industrial", "Suppress revolts"),
    "industrial_bribe":   ("industrial", "Bribe workers"),
    "industrial_automate":("industrial", "Automate factories"),
    "industrial_upgrade": ("industrial", "Upgrade factories"),
    "industrial_relief":  ("industrial", "Disaster relief"),
    "industrial_expand":  ("industrial", "Expand cities"),
    "industrial_banking": ("industrial", "Invest in banking (max 5 uses)"),
    "industrial_nationalize":("industrial", "Nationalize industry"),
    "indushelp":          ("industrial", "Show all Industrial Revolution commands"),

    # --- Other ---
    "help":     ("other", "Shows the help message"),
    "exportdb": ("other", "Export the current database (owner only)"),
}

# Keyword heuristics for auto-categorization of brand-new commands
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "industrial": ["industrial", "indus"],
    "bank":       ["bank", "sanction", "loan", "deposit"],
    "economy":    ["gold", "trade", "tax", "gather", "farm", "mine", "work",
                   "harvest", "invest", "drill", "labor", "raid", "corporation",
                   "megaproject", "policy"],
    "military":   ["attack", "war", "soldier", "ship", "plane", "navy", "air",
                   "siege", "train", "border", "stealth", "spy", "recruit",
                   "buildship", "buildplane", "blockade"],
    "diplomacy":  ["ally", "peace", "cease", "mail", "inbox", "coalition",
                   "trade", "send", "message"],
    "hyperitems": ["hyper", "nuke", "obliterate", "sacrifice", "mirror",
                   "shield", "luck", "propaganda", "merc", "mint", "harvest",
                   "spy", "invent", "backstab", "bomb", "clone", "fake", "glitch"],
    "store":      ["store", "market", "inventory", "black"],
    "territory":  ["territory", "expand", "province", "reclaim", "packs",
                   "countryball", "state", "civilwar", "map"],
    "factions":   ["faction"],
    "ideology":   ["ideology"],
    "basic":      ["start", "status", "reset", "region", "victory", "warhelp",
                   "updates", "sv", "svc"],
}


class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager
        self.groq_key = os.getenv('GROQ_API_KEY')
        self.openrouter_key = os.getenv('OPENROUTER')
        self.openai_key = os.getenv('OPENAI_API_KEY')
        self.groq_model = "llama-3.1-8b-instant"
        self.openrouter_model = "meta-llama/llama-3.3-70b-instruct"
        self.model_switch_time = None
        self.rate_limited = False
        self.conversations = defaultdict(deque)
        self.last_interaction = {}
        self.saved_chats = set()

    # =================================================================
    # HELPERS
    # =================================================================
    def _get_all_owned_provinces(self) -> list:
        territories = self.db.get_all_territories()
        return [name for name, data in territories.items() if data.get("owner_id")]

    def _get_conversation_history(self, user_id):
        return [
            {"role": "user" if msg['is_user'] else "assistant", "content": msg['content']}
            for msg in self.conversations[user_id]
        ]

    def _update_conversation(self, user_id, is_user, content):
        now = datetime.now()
        self.last_interaction[user_id] = now
        self.conversations[user_id].append({
            "is_user": is_user, "content": content, "timestamp": now,
        })
        if len(self.conversations[user_id]) > MAX_CONVERSATION_HISTORY:
            self.conversations[user_id].clear()
            return False
        if user_id not in self.saved_chats:
            expired = [uid for uid, t in list(self.last_interaction.items())
                       if (now - t).total_seconds() > CONVERSATION_TIMEOUT]
            for uid in expired:
                self.conversations.pop(uid, None)
                self.last_interaction.pop(uid, None)
        return True

    def _categorize_command(self, cmd: commands.Command) -> Tuple[str, str]:
        """Return (category_key, description) for a live command object.

        Priority:
          1. Hardcoded HARDCODED_HELP entry
          2. Keyword heuristic over the command name + aliases
          3. Fallback → 'other' with a placeholder description
        """
        name = cmd.name.lower()
        if name in HARDCODED_HELP:
            return HARDCODED_HELP[name]

        # Try aliases too
        for alias in getattr(cmd, "aliases", []) or []:
            if alias.lower() in HARDCODED_HELP:
                return HARDCODED_HELP[alias.lower()]

        # Heuristic fallback — new command auto-discovery
        haystack = " ".join([name] + [a.lower() for a in (getattr(cmd, "aliases", []) or [])])
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in haystack for kw in keywords):
                return (cat, "(new command — help text pending)")

        return ("other", "(new command — help text pending)")

    def _build_category_map(self) -> Dict[str, List[Tuple[str, str, bool]]]:
        """Walk live commands and bucket them.

        Returns { category_key: [(command_name, description, is_new), ...] }
        """
        buckets: Dict[str, List[Tuple[str, str, bool]]] = defaultdict(list)
        seen = set()

        # Pull commands from the live bot
        for cmd in self.bot.commands:
            if cmd.hidden:
                continue
            # Skip commands that are sub-commands (they show via their parent)
            if isinstance(cmd, commands.Group):
                # The group itself shows; its subcommands don't need separate rows
                pass
            name = cmd.name.lower()
            if name in seen:
                continue
            seen.add(name)
            cat, desc = self._categorize_command(cmd)
            is_new = name not in HARDCODED_HELP and not any(
                a.lower() in HARDCODED_HELP for a in (getattr(cmd, "aliases", []) or [])
            )
            buckets[cat].append((name, desc, is_new))

        # Sort each bucket: hardcoded commands first (alphabetical), new ones after
        for cat in buckets:
            buckets[cat].sort(key=lambda row: (row[2], row[0]))

        return buckets

    # =================================================================
    # RESET
    # =================================================================
    @commands.command(name='reset')
    async def reset_civilization(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You don't have a civilization to reset!")
            return
        embed = discord.Embed(
            title="⚠️ CIVILIZATION RESET CONFIRMATION",
            description="**This action is PERMANENT and cannot be undone!**",
            color=0xff0000,
        )
        embed.add_field(
            name="You will lose:",
            value="• All resources and progress\n• Your military and population\n"
                  "• Your territory and items\n• Your region and ideology\n"
                  "• Your bank deposits and credit score",
            inline=False,
        )
        embed.add_field(
            name="Confirmation Required:",
            value="Type `CONFIRM RESET` exactly as shown to reset your civilization.",
            inline=False,
        )
        embed.set_footer(text="This action cannot be reversed!")
        await ctx.send(embed=embed)

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            if msg.content == "CONFIRM RESET":
                if self.civ_manager.reset_civilization(user_id):
                    self.saved_chats.discard(user_id)
                    self.conversations.pop(user_id, None)
                    self.last_interaction.pop(user_id, None)
                    ok = discord.Embed(
                        title="🗑️ Civilization Reset",
                        description="Your civilization has been completely reset.",
                        color=0x00ff00,
                    )
                    ok.add_field(
                        name="What's Next?",
                        value="Use `.start <name>` to create a new civilization and begin again!",
                        inline=False,
                    )
                    await ctx.send(embed=ok)
                else:
                    await ctx.send("❌ Failed to reset civilization. Please try again later.")
            else:
                await ctx.send("🛑 Reset cancelled. Your civilization is safe.")
        except asyncio.TimeoutError:
            await ctx.send("🕒 Reset confirmation timed out. Your civilization is safe.")

    # =================================================================
    # SAVED CHAT
    # =================================================================
    @commands.command(name='sv')
    async def start_saved_chat(self, ctx):
        user_id = str(ctx.author.id)
        if user_id in self.saved_chats:
            await ctx.send("💾 You already have a saved chat running! Use `.svc` to close it.")
            return
        self.saved_chats.add(user_id)
        if user_id not in self.conversations:
            self.conversations[user_id] = deque()
            self.last_interaction[user_id] = datetime.now()
        embed = discord.Embed(
            title="💾 Saved Chat Started",
            description="Your conversation will now be saved until you use `.svc` to close it.",
            color=0x00ff00,
        )
        embed.add_field(
            name="Features:",
            value="• No 30-minute timeout\n• Persistent across bot restarts\n"
                  "• Up to 100 messages\n• Use `.svc` to close and delete",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name='svc')
    async def close_saved_chat(self, ctx):
        user_id = str(ctx.author.id)
        if user_id not in self.saved_chats:
            await ctx.send("❌ You don't have a saved chat running! Use `.sv` to start one.")
            return
        self.conversations.pop(user_id, None)
        self.last_interaction.pop(user_id, None)
        self.saved_chats.discard(user_id)
        embed = discord.Embed(
            title="🗑️ Saved Chat Closed",
            description="Your saved chat has been closed and all conversation history deleted.",
            color=0x00ff00,
        )
        await ctx.send(embed=embed)

    # =================================================================
    # AI LISTENER
    # =================================================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        user_id = str(message.author.id)
        content = (message.content or "").strip()

        is_reply = False
        if getattr(message, "reference", None) and getattr(message.reference, "message_id", None):
            try:
                replied = await message.channel.fetch_message(message.reference.message_id)
                if replied and replied.author.id == self.bot.user.id:
                    is_reply = True
            except Exception as e:
                logger.error(f"Error fetching replied message: {e}")

        try:
            mentions = getattr(message, "mentions", []) or []
            bot_mentioned = any(getattr(u, "id", None) == self.bot.user.id for u in mentions)
        except Exception:
            bot_mentioned = False

        if not (bot_mentioned or is_reply):
            return

        if bot_mentioned:
            content = content.replace(f'<@{self.bot.user.id}>', '').strip()

        if is_reply and user_id in self.conversations and len(self.conversations[user_id]) >= MAX_CONVERSATION_HISTORY:
            try:
                await message.reply("Chat limit reached! Starting new conversation.", mention_author=False)
            except Exception:
                pass
            self.conversations.pop(user_id, None)
            self.last_interaction.pop(user_id, None)
            return

        if bot_mentioned and not is_reply and user_id not in self.saved_chats:
            self.conversations[user_id] = deque()
            self.last_interaction[user_id] = datetime.now()

        if not content:
            if bot_mentioned:
                try:
                    await message.reply(embed=create_embed(
                        "🤖 NationBot Assistant",
                        "Hello! I'm here to help you with NationBot. Ask me about:\n"
                        "- Starting your civilization (`.start`)\n"
                        "- Managing resources (`.status`)\n"
                        "- Factions & civil war\n"
                        "- Sanctions & banking\n"
                        "- Military commands (`.warhelp military`)\n"
                        "- Victory conditions (`.victory`)\n\n"
                        "Try: *'How do factions work?'* or *'How do I impose a sanction?'*",
                        discord.Color.blue(),
                    ), mention_author=False)
                    self._update_conversation(user_id, False, "Hello! How can I assist today?")
                except Exception:
                    logger.exception("Failed to send default mention reply")
            return

        civ = None
        try:
            civ = self.civ_manager.get_civilization(user_id)
        except Exception:
            logger.exception("Failed to fetch civ for AI context")

        civ_status = ""
        if civ:
            try:
                factions = civ.get('factions', {"military": 50, "merchant": 50, "people": 50})
                civ_status = (
                    f"Player's Civilization: {civ['name']} (Ideology: {civ.get('ideology', 'none')})\n"
                    f"Resources: 🪙{format_number(civ['resources'].get('gold',0))} "
                    f"🌾{format_number(civ['resources'].get('food',0))} "
                    f"🪨{format_number(civ['resources'].get('stone',0))} "
                    f"🪵{format_number(civ['resources'].get('wood',0))}\n"
                    f"Military: ⚔️{format_number(civ['military'].get('soldiers',0))} "
                    f"🕵️{format_number(civ['military'].get('spies',0))}\n"
                    f"Factions: ⚔️{factions.get('military',50)} 💰{factions.get('merchant',50)} 👥{factions.get('people',50)}\n"
                )
            except Exception:
                civ_status = ""

        system_prompt = f"""You are NationBot, an AI assistant for a nation simulation game.
Players build civilizations, manage resources, wage wars, and form alliances.
Your role is to help players understand game mechanics and strategies.

{civ_status}

**CORE BALANCE (from config.py):**
- Economy gains use config.ECONOMY, gated by tech-level curve (linear, ~0.8%/level).
- Passive income uses tech_gold_per_level = 2% (flat, no compounding).
- Territory modifier caps at 1.20x (diminishing returns, NOT a spike).
- Soldier cost: 20 gold each.
- Expansion: large provinces (≥1M km²) cost 1 soldier per 2000 km².
- Tax has a HARD CAP of 150,000 per collection.

**FACTIONS (internal politics):**
Every nation has three factions 0-100: ⚔️ Military, 💰 Merchant, 👥 People.
- Actions move them: war → Military up / Merchant down; trade → Merchant up / Military down;
  farming/festivals → People up; heavy tax/labor → People down.
- **≤10 → instant civil war** (that faction rebels, split territories).
- **≥80 → passive blessing** (bonus income or training speed).
- Tell players to watch `.factions` and avoid spamming one action type.

**SANCTIONS:**
- `.sanction @user [reason]` — costs 10,000 gold. Blocks target from `.globaltrade`,
  `.trade`, and ALL `.bank` commands. Also reduces their income ×0.60 and drains happiness.
- Lasts 24 hours. Max 3 active at once.
- `.liftsanction @user` and `.sanctions` to manage.

**BANKING:**
- `.bank` — view deposits, loans, credit score.
- `.bank deposit <amt>` — earn 0.1%/hr interest.
- `.bank loan <amt>` — borrow up to 30% of net worth. Loan rate 0.6%/hr.
- `.bank repay <amt>` — pay down the loan.
- **Default at 5 days unpaid** → deposits seized, account locked 30 days, credit −50.

**VICTORY CONDITIONS:** Domination, Economic, Industrial, Conquest, United Nations.
Track with `.victory`.

**STRATEGY TIPS:**
- Build navy before overseas expansion (25% off + required for non-neighbour).
- Airforce gives 50% off land expansions.
- Use `.buysoldiers` for quick armies.
- Tax is capped — focus on gathering, trade, and megaprojects.
- Watch factions — one bad tradeoff (e.g., endless war) crashes a faction to civil war.
- Sanction rivals to cripple their economy without firing a shot.

You are helpful, encouraging, and strategic. Keep responses concise.
Address the player as 'President'. Use Discord markdown.
"""

        try:
            messages = [{"role": "system", "content": system_prompt}]
            if user_id in self.conversations and self.conversations[user_id]:
                messages.extend(self._get_conversation_history(user_id))
            messages.append({"role": "user", "content": content})

            response = await self.generate_ai_response(messages)

            update_success = self._update_conversation(user_id, True, content)
            if not update_success:
                response += "\n\n💬 *Note: Chat history limit reached. Starting a new conversation.*"
                if user_id not in self.saved_chats:
                    self.conversations[user_id] = deque()
                    self.last_interaction[user_id] = datetime.now()

            self._update_conversation(user_id, False, response)

            try:
                await message.reply(response, mention_author=False)
            except Exception:
                try:
                    await message.channel.send(response)
                except Exception:
                    logger.exception("Failed to send AI response")
        except Exception as e:
            logger.error(f"AI response error: {e}", exc_info=True)
            try:
                await message.reply("I'm having trouble thinking right now. Please try again later!",
                                    mention_author=False)
            except Exception:
                pass

    async def generate_ai_response(self, messages):
        # --- GROQ ---
        if self.groq_key:
            headers = {"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"}
            payload = {"model": self.groq_model, "messages": messages, "max_tokens": 500, "temperature": 0.7}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers=headers, json=payload, timeout=60,
                    ) as response:
                        text = await response.text()
                        if response.status == 200:
                            data = await response.json()
                            return data['choices'][0]['message']['content']
                        raise Exception(f"Groq API error {response.status}: {text}")
            except Exception:
                logger.exception("Groq request failed")

        # --- OPENROUTER ---
        if self.openrouter_key:
            headers = {"Authorization": f"Bearer {self.openrouter_key}", "Content-Type": "application/json"}
            model = self.openrouter_model
            if self.rate_limited and self.model_switch_time and datetime.now() < self.model_switch_time:
                model = "moonshotai/kimi-k2:free"
            else:
                self.rate_limited = False
            payload = {"model": model, "messages": messages, "max_tokens": 500}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers, json=payload, timeout=60,
                    ) as response:
                        text = await response.text()
                        if response.status == 200:
                            data = await response.json()
                            return data['choices'][0]['message']['content']
                        elif response.status == 429:
                            self.rate_limited = True
                            self.model_switch_time = datetime.now() + timedelta(hours=24)
                            payload["model"] = "moonshotai/kimi-k2:free"
                            async with session.post(
                                "https://openrouter.ai/api/v1/chat/completions",
                                headers=headers, json=payload, timeout=60,
                            ) as fallback:
                                if fallback.status == 200:
                                    data = await fallback.json()
                                    return data['choices'][0]['message']['content']
                                errtxt = await fallback.text()
                                raise Exception(f"Fallback failed: {fallback.status} - {errtxt}")
                        else:
                            raise Exception(f"OpenRouter error {response.status}: {text}")
            except Exception:
                logger.exception("OpenRouter failed")

        # --- OPENAI ---
        if self.openai_key:
            headers = {"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
            payload = {"model": "gpt-3.5-turbo", "messages": messages, "max_tokens": 500, "temperature": 0.7}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers, json=payload, timeout=60,
                    ) as response:
                        text = await response.text()
                        if response.status == 200:
                            data = await response.json()
                            return data['choices'][0]['message']['content']
                        raise Exception(f"OpenAI error {response.status}: {text}")
            except Exception:
                logger.exception("OpenAI request failed")

        return "AI is unavailable right now. Please check the bot's API keys."

    # =================================================================
    # WARHELP — hybrid (prefix + slash), auto-discovering
    # =================================================================
    @commands.hybrid_command(name='warhelp', with_app_command=True)
    @app_commands.describe(category="Category to view (leave blank to list all)")
    async def warhelp(self, ctx, category: str = None):
        """Show command help. Auto-discovers new commands."""
        buckets = self._build_category_map()

        def _send(embed):
            return ctx.send(embed=embed)

        # No category → overview
        if category is None:
            embed = discord.Embed(
                title="🤖 NationBot — Command Categories",
                description=(
                    "Use `.warhelp <category>` (or `/warhelp category:<name>`) to see commands.\n"
                    "*New commands are auto-discovered and listed.*"
                ),
                color=discord.Color.blue(),
            )
            lines = []
            for cat_key, (cat_name, cat_desc) in CATEGORY_META.items():
                count = len(buckets.get(cat_key, []))
                if count == 0:
                    continue
                lines.append(f"**{cat_name}** — *{cat_desc}*  `({count})`")
            full = "\n".join(lines)
            if len(full) > 1024:
                chunks = [full[i:i+1024] for i in range(0, len(full), 1024)]
                for i, chunk in enumerate(chunks, 1):
                    embed.add_field(name=f"Categories (Part {i})", value=chunk, inline=False)
            else:
                embed.add_field(name="Categories", value=full, inline=False)
            embed.set_footer(text="Example: .warhelp military  |  /warhelp category:military")
            await _send(embed)
            return

        cat_key = category.lower().strip()
        # Accept either key or display name fragment
        if cat_key not in CATEGORY_META:
            for key, (name, _) in CATEGORY_META.items():
                if cat_key in key or cat_key in name.lower():
                    cat_key = key
                    break
            else:
                await ctx.send(f"❌ Unknown category `{category}`. Use `.warhelp` to see all.")
                return

        rows = buckets.get(cat_key, [])
        if not rows:
            await ctx.send(f"📭 No commands in **{CATEGORY_META[cat_key][0]}** yet.")
            return

        cat_name, cat_desc = CATEGORY_META[cat_key]

        # Split into chunks of 20 commands per embed
        CHUNK = 20
        chunks = [rows[i:i+CHUNK] for i in range(0, len(rows), CHUNK)]
        for idx, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=f"{cat_name}" + (f" (Part {idx}/{len(chunks)})" if len(chunks) > 1 else ""),
                description=f"*{cat_desc}*",
                color=discord.Color.green(),
            )
            lines = []
            for name, desc, is_new in chunk:
                prefix = "🆕 " if is_new else ""
                lines.append(f"{prefix}`{name}` — {desc}")
            value = "\n".join(lines)
            if len(value) > 1024:
                value = value[:1021] + "..."
            embed.add_field(name="Commands", value=value, inline=False)
            embed.set_footer(text="Use .warhelp <category>  |  /warhelp category:<name>")
            await _send(embed)

    # =================================================================
    # UPDATES
    # =================================================================
    @commands.command(name='updates')
    async def show_updates(self, ctx):
        embed = discord.Embed(title="📅 NationBot Roadmap & Updates", color=discord.Color.blue())
        roadmap = (
            "**Phase 1: Core** (✅)\n"
            "• Firestore migration, centralised config, economy balance\n\n"
            "**Phase 2: Expansion & War** (✅)\n"
            "• State-based expansion, navy/airforce, `.states`\n\n"
            "**Phase 3: Victory** (✅)\n"
            "• Domination / Economic / Industrial / Conquest / UN\n\n"
            "**Phase 4: Civil War** (✅)\n"
            "• Territory splits, AI news, +30% reclaim boost\n\n"
            "**Phase 5: Factions, Sanctions & Banking** (✅)\n"
            "• Three internal factions with civil-war triggers\n"
            "• Sanctions: block trade, banking, nerf income\n"
            "• Central bank: deposits, loans, default system"
        )
        embed.add_field(name="🗺️ Roadmap", value=roadmap, inline=False)

        updates = (
            "**v3.0.0**\n"
            "• Factions: Military / Merchant / People drive civil war\n"
            "• Sanctions: `.sanction`, `.liftsanction`, `.sanctions`\n"
            "• Bank: `.bank deposit / withdraw / loan / repay`\n"
            "• Lucky Strike fixed (used to set wrong flag)\n"
            "• Power curve flattened (linear, no compounding)\n"
            "• `.warhelp` auto-discovers new commands\n"
            "• `.factions` command added\n"
            "• `.status` shows factions and sanction badge"
        )
        embed.add_field(name="📝 Update Log", value=updates, inline=False)
        await ctx.send(embed=embed)

    # =================================================================
    # VICTORY
    # =================================================================
    @commands.command(name='victory')
    async def show_victory_progress(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`.")
            return
        progress = self.db.get_victory_progress(user_id)
        if not progress:
            await ctx.send("❌ Victory conditions not available. Try again later.")
            return

        embed = discord.Embed(
            title="🏆 Victory Progress",
            description=f"Progress for **{civ['name']}** — complete any one to win!",
            color=discord.Color.gold(),
        )

        d = progress["domination"]
        embed.add_field(
            name="⚔️ Domination",
            value=f"{self._create_bar(d['progress'], d['target'])} "
                  f"{d['owned']}/{d['threshold']} provinces ({d['progress']*100:.1f}%)",
            inline=False,
        )
        e = progress["economic"]
        embed.add_field(
            name="💰 Economic",
            value=(f"{self._create_bar(e['gold'], e['target_gold'])} Gold: "
                   f"{format_number(e['gold'])}/{format_number(e['target_gold'])}\n"
                   f"{self._create_bar(e['gdp'], e['target_gdp'])} GDP/citizen: "
                   f"{format_number(e['gdp'])}/{format_number(e['target_gdp'])}"),
            inline=False,
        )
        ind = progress["industrial"]
        embed.add_field(
            name="🏭 Industrial",
            value=(f"{self._create_bar(ind['megaprojects'], ind['target_megaprojects'])} "
                   f"Megaprojects: {ind['megaprojects']}/{ind['target_megaprojects']}\n"
                   f"{self._create_bar(ind['policies'], ind['target_policies'])} "
                   f"Policies: {ind['policies']}/{ind['target_policies']}"),
            inline=False,
        )
        c = progress["conquest"]
        status = "✅ Complete" if c["completed"] else f"❌ {c['owned']}/{c['total']} provinces"
        embed.add_field(name="🌍 Conquest", value=f"Own all provinces: {status}", inline=False)
        un = progress["united_nations"]
        un_status = "✅ In alliance" if un["in_alliance"] else "❌ No alliance"
        embed.add_field(
            name="🕊️ United Nations",
            value=f"{un_status}\nMembers: {un['members']}/{un['target']}",
            inline=False,
        )
        embed.set_footer(text="Complete any one condition to achieve victory!")
        await ctx.send(embed=embed)

    def _create_bar(self, current: float, target: float, length: int = 10) -> str:
        if target <= 0:
            return "▓" * length
        progress = min(1.0, current / target)
        filled = int(progress * length)
        return "▓" * filled + "░" * (length - filled)

    # =================================================================
    # REGIONS
    # =================================================================
    @commands.command(name='regions')
    @app_commands.describe(region_name="Subregion to select (e.g., 'western europe')")
    async def regions_command(self, ctx, *, region_name: str = None):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return

        if not region_name:
            embed = discord.Embed(
                title="🌍 Available Subregions",
                description=("Choose a subregion to start your civilization. Each provides unique bonuses. "
                             "Provinces are **unique** — once taken, no one else can claim it.\n\n"
                             "To select one, use `.regions <subregion_name>`."),
                color=0x00ff00,
            )
            grouped = {}
            for sub in ALL_SUBREGIONS:
                continent = SUBREGION_TO_CONTINENT.get(sub, "Unknown")
                grouped.setdefault(continent, []).append(sub)
            all_owned = self._get_all_owned_provinces()
            for continent, sublist in grouped.items():
                available_subregions = []
                for sub in sorted(sublist):
                    provinces = PROVINCES.get(sub, [])
                    available = [p for p in provinces if p not in all_owned and p not in FORBIDDEN_START_PROVINCES]
                    if available:
                        available_subregions.append(sub)
                if available_subregions:
                    embed.add_field(name=continent, value=", ".join(available_subregions), inline=False)
                else:
                    embed.add_field(name=continent, value="*All subregions fully claimed.*", inline=False)
            embed.set_footer(text=f"Your current region: {civ.get('region', 'None')}")
            await ctx.send(embed=embed)
            return

        input_name = region_name.strip().lower()
        matched = None
        for sub in ALL_SUBREGIONS:
            if sub.lower() == input_name:
                matched = sub
                break
        if not matched:
            for sub in ALL_SUBREGIONS:
                if input_name in sub.lower():
                    matched = sub
                    break
        if not matched:
            await ctx.send(f"❌ Unknown subregion: `{region_name}`.")
            return
        if civ.get('region'):
            await ctx.send(f"❌ You already selected **{civ['region']}**. Region cannot be changed.")
            return

        provinces_in_subregion = PROVINCES.get(matched, [])
        if not provinces_in_subregion:
            await ctx.send(f"❌ Subregion **{matched}** has no provinces.")
            return
        all_owned = self._get_all_owned_provinces()
        available_provinces = [
            p for p in provinces_in_subregion
            if p not in all_owned and p not in FORBIDDEN_START_PROVINCES
        ]
        if not available_provinces:
            await ctx.send(f"❌ All startable provinces in **{matched}** are claimed.")
            return

        chosen = random.choice(available_provinces)
        continent = SUBREGION_TO_CONTINENT.get(matched, "Unknown")
        continent_bonuses = {
            "Europe": {"gold": 300, "tech_level": 1},
            "Asia": {"food": 200, "population": 50},
            "Africa": {"stone": 150, "wood": 150},
            "North America": {"gold": 200, "food": 200},
            "South America": {"food": 300, "wood": 100},
            "Oceania": {"food": 250, "happiness": 15},
            "Antarctica": {"research": 25},
            "Unknown": {"gold": 100, "food": 100},
        }
        bonuses = continent_bonuses.get(continent, continent_bonuses["Unknown"])

        updated_resources = civ['resources'].copy()
        updated_population = civ['population'].copy()
        for resource, amount in bonuses.items():
            if resource in updated_resources:
                updated_resources[resource] += amount
            elif resource == "population":
                updated_population['citizens'] += amount
            elif resource == "happiness":
                updated_population['happiness'] = min(100, updated_population['happiness'] + amount)
            elif resource == "research":
                cb = civ.get('bonuses', {})
                cb['research_speed'] = cb.get('research_speed', 0) + amount
                self.db.update_civilization(user_id, {'bonuses': cb})

        update_data = {
            'region': matched,
            'resources': updated_resources,
            'population': updated_population,
        }

        if self.db.update_civilization(user_id, update_data):
            territory_cog = self.bot.get_cog("TerritoryCog")
            if territory_cog:
                success = territory_cog._add_province(user_id, chosen)
                if not success:
                    await ctx.send("❌ Failed to assign starting province. Contact admin.")
                    return
            else:
                await ctx.send("❌ Territory system not available. Contact admin.")
                return

            area = territory_cog.province_areas.get(chosen, 1000) if territory_cog else 1000
            bonus_text = ", ".join([f"+{amount} {resource}" for resource, amount in bonuses.items()])
            embed = discord.Embed(
                title=f"🌍 Region Selected: {matched}",
                description=f"Civilization established in **{matched}** ({continent}).",
                color=0x00ff00,
            )
            embed.add_field(name="Bonuses Applied", value=bonus_text, inline=False)
            embed.add_field(name="🏛️ Starting Province",
                            value=f"You have been granted **{chosen}** (area: {area:,} km²).",
                            inline=False)
            embed.add_field(name="🎉 Nation Complete!",
                            value="Use `.status` to view your stats and `.warhelp` to see commands.",
                            inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to update your region. Try again later.")

    # =================================================================
    # START
    # =================================================================
    @commands.command(name='start')
    @app_commands.describe(civ_name="Name of your civilization")
    async def start_civilization(self, ctx, *, civ_name: str = None):
        if not civ_name:
            await ctx.send("❌ Please provide a civilization name: `.start <civilization_name>`")
            return
        user_id = str(ctx.author.id)
        if self.civ_manager.get_civilization(user_id):
            await ctx.send("❌ You already have a civilization! Use `.status` to view it.")
            return
        intro_art = get_ascii_art("civilization_start")
        founding_events = [
            ("🏛️ **Golden Dawn**: Your people discovered ancient gold deposits!", {"gold": 200}),
            ("🌾 **Fertile Lands**: Blessed with rich soil!", {"food": 300}),
            ("🏗️ **Master Builders**: Citizens are natural architects!", {"stone": 150, "wood": 150}),
            ("👥 **Population Boom**: Word of your leadership spreads!", {"population": 50}),
            ("⚡ **Lightning Strike**: A divine sign brings fortune!", {"gold": 100, "happiness": 20}),
        ]
        event_text, bonus_resources = random.choice(founding_events)
        name_bonuses = {}
        special_message = ""
        if "ink" in civ_name.lower():
            name_bonuses["luck_bonus"] = 5
            special_message = "🖋️ *The pen will never forget your work.* (+5% luck)"
        elif "pen" in civ_name.lower():
            name_bonuses["diplomacy_bonus"] = 5
            special_message = "🖋️ *The pen is mightier than the sword.* (+5% diplomacy)"
        hyper_item = None
        if random.random() < 0.05:
            hyper_item = random.choice(["Lucky Charm", "Propaganda Kit", "Mercenary Contract"])

        self.civ_manager.create_civilization(user_id, civ_name, bonus_resources, name_bonuses, hyper_item)
        embed = discord.Embed(
            title=f"🏛️ The Founding of {civ_name}",
            description=f"{intro_art}\n\n{event_text}\n{special_message}",
            color=0x00ff00,
        )
        if hyper_item:
            embed.add_field(name="🎁 Rare Discovery!",
                            value=f"Your scouts found a **{hyper_item}**!",
                            inline=False)
        embed.add_field(
            name="📋 Next Steps",
            value=("Choose your government ideology with `.ideology <type>`\n"
                   "Select your region with `.regions`\n"
                   "View your status with `.status`\n"
                   "Track victory with `.victory`"),
            inline=False,
        )
        await ctx.send(embed=embed)

    # =================================================================
    # IDEOLOGY — updated descriptions with faction leanings
    # =================================================================
    @commands.command(name='ideology')
    @app_commands.describe(ideology_type="Government ideology")
    @app_commands.choices(ideology_type=[
        app_commands.Choice(name="fascism", value="fascism"),
        app_commands.Choice(name="democracy", value="democracy"),
        app_commands.Choice(name="communism", value="communism"),
        app_commands.Choice(name="theocracy", value="theocracy"),
        app_commands.Choice(name="anarchy", value="anarchy"),
        app_commands.Choice(name="destruction", value="destruction"),
        app_commands.Choice(name="pacifist", value="pacifist"),
        app_commands.Choice(name="socialism", value="socialism"),
        app_commands.Choice(name="terrorism", value="terrorism"),
        app_commands.Choice(name="capitalism", value="capitalism"),
        app_commands.Choice(name="federalism", value="federalism"),
        app_commands.Choice(name="monarchy", value="monarchy"),
    ])
    async def choose_ideology(
        self,
        ctx,
        ideology_type: Optional[Literal[
            "fascism", "democracy", "communism", "theocracy", "anarchy", "destruction",
            "pacifist", "socialism", "terrorism", "capitalism", "federalism", "monarchy",
        ]] = None,
    ):
        # ---- Info table ----
        IDEOLOGIES = {
            "fascism":     ("⚔️", "Militarist autocracy", "+25% soldier training, +10% combat, −15% diplomacy, −10% luck",
                            "Leans ⚔️ Military — Merchant drifts down from constant war"),
            "democracy":   ("🗳️", "Representative republic", "+20% happiness, +10% trade profit, −15% soldier training",
                            "Leans 💰 Merchant + 👥 People — balanced"),
            "communism":   ("🏭", "Worker state", "+10% citizen productivity, −10% tech speed",
                            "Leans 👥 People — Merchant resents central control"),
            "theocracy":   ("⛪", "Divine rule", "+15% propaganda, +5% happiness, −10% tech speed",
                            "Leans 👥 People — Military suspicious of clerics"),
            "anarchy":     ("💥", "No central government", "2× random events, 0 soldier upkeep, −20% spy success",
                            "Leans ⚔️ Military — civil war is always close"),
            "destruction": ("💀", "Total-war doctrine", "+35% combat, +40% soldier training, −25% resources, −50% diplomacy",
                            "Leans ⚔️ Military — Merchant and People flee"),
            "pacifist":    ("🕊️", "Peace at any cost", "+35% happiness, +25% pop growth, +20% trade, −60% training, −40% combat",
                            "Leans 👥 People + 💰 Merchant — Military furious"),
            "socialism":   ("🤝", "Welfare state", "+15% citizen productivity, +10% happiness, −10% trade",
                            "Leans 👥 People — Merchant mildly unhappy"),
            "terrorism":   ("🔥", "Shadow warfare", "+40% raids, +30% spy success, −50% diplomacy, +25% unrest",
                            "Leans ⚔️ Military — Merchant and People terrified"),
            "capitalism":  ("💹", "Free market", "+20% trade, +15% gold generation, −10% happiness",
                            "Leans 💰 Merchant — People resent inequality"),
            "federalism":  ("🏛️", "Decentralized union", "+10% stability, +10% diplomacy, +5% regional production",
                            "Leans 💰 Merchant + 👥 People — stable"),
            "monarchy":    ("👑", "Hereditary crown", "+10% loyalty, +10% soldier morale, −10% reform speed",
                            "Leans ⚔️ Military + 👥 People — Merchant neutral"),
        }

        if not ideology_type:
            embed = discord.Embed(
                title="🏛️ Government Ideologies",
                description="Choose carefully — this is **permanent**. Each shapes your economy, military, and factions.",
                color=0x0099ff,
            )
            for name, (emoji, tagline, effects, faction_lean) in IDEOLOGIES.items():
                embed.add_field(
                    name=f"{emoji} {name.capitalize()} — *{tagline}*",
                    value=f"{effects}\n**Faction lean:** {faction_lean}",
                    inline=False,
                )
            embed.add_field(name="Usage", value="`.ideology <type>`", inline=False)
            await ctx.send(embed=embed)
            return

        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need to start a civilization first! Use `.start <name>`")
            return
        if civ.get('ideology'):
            await ctx.send("❌ You have already chosen an ideology! It cannot be changed.")
            return
        ideology_type = ideology_type.lower()
        if ideology_type not in IDEOLOGIES:
            await ctx.send(f"❌ Invalid ideology! Choose from: {', '.join(IDEOLOGIES.keys())}")
            return

        self.civ_manager.set_ideology(user_id, ideology_type)
        emoji, tagline, effects, faction_lean = IDEOLOGIES[ideology_type]
        embed = discord.Embed(
            title=f"{emoji} Ideology Chosen: {ideology_type.capitalize()}",
            description=f"*{tagline}*\n\n**Effects:** {effects}\n**Faction lean:** {faction_lean}",
            color=0x00ff00,
        )
        embed.add_field(
            name="🎉 Almost Complete!",
            value="**Select your region with `.regions`** to finish setup and receive regional bonuses.",
            inline=False,
        )
        await ctx.send(embed=embed)

    # =================================================================
    # STATUS
    # =================================================================
    @commands.command(name='status')
    async def civilization_status(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You don't have a civilization yet! Use `.start <name>` to begin.")
            return

        embed = discord.Embed(
            title=f"🏛️ {civ['name']}",
            description=(f"**Leader**: {ctx.author.name}\n"
                         f"**Ideology**: {civ['ideology'].capitalize() if civ.get('ideology') else 'None'}\n"
                         f"**Region**: {civ.get('region', 'Not selected')}"),
            color=0x0099ff,
        )

        resources = civ['resources']
        embed.add_field(
            name="💰 Resources",
            value=(f"🪙 Gold: {format_number(resources['gold'])}\n"
                   f"🌾 Food: {format_number(resources['food'])}\n"
                   f"🪨 Stone: {format_number(resources['stone'])}\n"
                   f"🪵 Wood: {format_number(resources['wood'])}"),
            inline=True,
        )

        population = civ['population']
        military = civ['military']
        embed.add_field(
            name="👥 Population & Military",
            value=(f"👤 Citizens: {format_number(population['citizens'])}\n"
                   f"😊 Happiness: {population['happiness']}%\n"
                   f"🍽️ Hunger: {population['hunger']}%\n"
                   f"⚔️ Soldiers: {format_number(military['soldiers'])}\n"
                   f"🕵️ Spies: {format_number(military['spies'])}"),
            inline=True,
        )

        territory = civ['territory']
        hyper_items = civ.get('hyper_items', [])
        embed.add_field(
            name="🗺️ Territory & Items",
            value=(f"🏞️ Land Size: {format_number(territory['land_size'])} km²\n"
                   f"🎁 HyperItems: {len(hyper_items)}\n"
                   + ("\n".join(f"• {item}" for item in hyper_items[:5])
                      + ("..." if len(hyper_items) > 5 else ""))),
            inline=True,
        )

        # ---- Factions ----
        factions = civ.get('factions', {"military": 50, "merchant": 50, "people": 50})
        f_lines = []
        for fkey in ("military", "merchant", "people"):
            meta = config.FACTIONS.get(fkey, {})
            val = factions.get(fkey, 50)
            f_lines.append(f"{meta.get('emoji','❓')} {meta.get('name', fkey.title())}: "
                           f"**{val}**/100 {get_faction_status_emoji(val)}")
        embed.add_field(name="🏛️ Factions", value="\n".join(f_lines), inline=True)

        warns = get_all_faction_warnings(factions)
        if warns:
            embed.add_field(name="⚠️ Faction Unrest", value="\n".join(warns), inline=False)

        # ---- Sanctions ----
        try:
            now = datetime.utcnow()
            active_recv = [s for s in (civ.get('received_sanctions') or [])
                           if datetime.fromisoformat(s['expires_at']) > now]
            if active_recv:
                embed.add_field(
                    name="🚫 Sanctioned",
                    value=f"{len(active_recv)} active — income reduced, "
                          f"`.globaltrade` / `.trade` / `.bank` blocked.",
                    inline=False,
                )
        except Exception:
            pass

        # ---- Bank snapshot ----
        try:
            bank = civ.get('bank') or {}
            d = int(bank.get('deposits', 0))
            l = int(bank.get('loan', 0))
            credit = int(bank.get('credit_score', 100))
            if d > 0 or l > 0:
                embed.add_field(
                    name="🏦 Bank",
                    value=f"Deposits: {format_number(d)} | Loan: {format_number(l)} | Credit: {credit}/100",
                    inline=False,
                )
        except Exception:
            pass

        # ---- Civil war status ----
        cw = civ.get('civil_war') or {}
        if cw.get('active'):
            embed.add_field(
                name="⚠️ CIVIL WAR ACTIVE",
                value=(f"Rebel territories: {len(cw.get('rebel_territories', []))}\n"
                       f"Rebel strength: {cw.get('rebel_strength', 0)}\n"
                       f"Cause: {cw.get('cause', 'unknown')}\n"
                       f"Use `.reclaim <territory>` to fight back."),
                inline=False,
            )

        await ctx.send(embed=embed)

    # =================================================================
    # FACTIONS
    # =================================================================
    @commands.command(name='factions')
    async def factions_command(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first! Use `.start <name>`")
            return

        factions = civ.get('factions', {"military": 50, "merchant": 50, "people": 50})

        danger = config.FACTIONS['military']['danger_threshold']
        bless = config.FACTIONS['military']['blessing_threshold']

        embed = discord.Embed(
            title="🏛️ Factions",
            description=(
                f"Three power blocs live inside every nation.\n"
                f"**≤{danger}** → instant civil war (that faction rebels).\n"
                f"**≥{bless}** → passive blessing.\n"
                f"Actions move them — watch your behavior."
            ),
            color=discord.Color.purple(),
        )

        for fkey in ("military", "merchant", "people"):
            meta = config.FACTIONS.get(fkey, {})
            val = factions.get(fkey, 50)
            bar = "▓" * (val // 10) + "░" * (10 - val // 10)
            lines = [f"{bar} **{val}/100** {get_faction_status_emoji(val)}"]
            if meta.get("desc"):
                lines.append(f"*{meta['desc']}*")
            if meta.get("blessing_effect"):
                lines.append("Bless: " + ", ".join(f"`{k}` × {v}" for k, v in meta["blessing_effect"].items()))
            if meta.get("bane_effect"):
                lines.append("Bane: " + ", ".join(f"`{k}` × {v}" for k, v in meta["bane_effect"].items()))
            embed.add_field(
                name=f"{meta.get('emoji','❓')} {meta.get('name', fkey.title())}",
                value="\n".join(lines),
                inline=False,
            )

        warns = get_all_faction_warnings(factions)
        if warns:
            embed.add_field(name="⚠️ Warnings", value="\n".join(warns), inline=False)
        else:
            embed.set_footer(text="All factions stable.")
        await ctx.send(embed=embed)

    # =================================================================
    # SANCTIONS
    # =================================================================
    @commands.command(name='sanction')
    async def impose_sanction(self, ctx, target: discord.Member = None, *, reason: str = "No reason given"):
        if not target:
            await ctx.send(
                f"🚫 **Sanction**\nUsage: `.sanction <user> [reason]`\n"
                f"Cost: {config.SANCTIONS['impose_cost_gold']:,} gold. "
                f"Duration: {config.SANCTIONS['duration_hours']}h."
            )
            return
        user_id, target_id = str(ctx.author.id), str(target.id)
        if user_id == target_id:
            await ctx.send("❌ You cannot sanction yourself.")
            return

        civ = self.civ_manager.get_civilization(user_id)
        target_civ = self.civ_manager.get_civilization(target_id)
        if not civ or not target_civ:
            await ctx.send("❌ Both parties need a civilization.")
            return

        now = datetime.utcnow()
        imposed = [s for s in (civ.get('imposed_sanctions') or [])
                   if datetime.fromisoformat(s['expires_at']) > now]
        if len(imposed) >= config.SANCTIONS['max_active_per_imposer']:
            await ctx.send(f"❌ Max {config.SANCTIONS['max_active_per_imposer']} active sanctions.")
            return

        cost = config.SANCTIONS['impose_cost_gold']
        if not self.civ_manager.can_afford(user_id, {"gold": cost}):
            await ctx.send(f"❌ Need {cost:,} gold to impose a sanction.")
            return

        self.civ_manager.spend_resources(user_id, {"gold": cost})
        expires = (now + timedelta(hours=config.SANCTIONS['duration_hours'])).isoformat()

        imposed.append({"target_id": target_id, "expires_at": expires, "reason": reason})
        self.db.update_civilization(user_id, {"imposed_sanctions": imposed})

        received = target_civ.get('received_sanctions') or []
        received.append({"imposer_id": user_id, "expires_at": expires, "reason": reason})
        self.db.update_civilization(target_id, {"received_sanctions": received})
        self.civ_manager._invalidate_civ(user_id)
        self.civ_manager._invalidate_civ(target_id)
        self.civ_manager.apply_faction_effects(user_id, "impose_sanction")

        embed = discord.Embed(
            title="🚫 Sanctions Imposed",
            description=f"**{civ['name']}** has sanctioned **{target_civ['name']}**.",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Duration", value=f"{config.SANCTIONS['duration_hours']}h", inline=True)
        embed.add_field(name="Cost", value=f"🪙 {cost:,}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(
            name="Effects on Target",
            value=(f"• 🚫 `.globaltrade`, `.trade`, `.bank` blocked\n"
                   f"• 📉 Income × {config.SANCTIONS['resource_income_multiplier']}\n"
                   f"• 😡 −{config.SANCTIONS['happiness_penalty_per_tick']} happiness per tick"),
            inline=False,
        )
        await ctx.send(embed=embed)
        self.db.log_event(user_id, "sanction_imposed", "Sanction Imposed",
                          f"{civ['name']} sanctioned {target_civ['name']}: {reason}")

    @commands.command(name='liftsanction', aliases=['unsanction'])
    async def lift_sanction(self, ctx, target: discord.Member = None):
        if not target:
            await ctx.send("Usage: `.liftsanction <user>`")
            return
        user_id, target_id = str(ctx.author.id), str(target.id)

        civ = self.civ_manager.get_civilization(user_id)
        target_civ = self.civ_manager.get_civilization(target_id)
        if not civ or not target_civ:
            await ctx.send("❌ Both parties need a civilization.")
            return

        imposed = civ.get('imposed_sanctions') or []
        before = len(imposed)
        imposed = [s for s in imposed if s['target_id'] != target_id]
        if len(imposed) == before:
            await ctx.send("❌ You have not sanctioned that user.")
            return

        received = [s for s in (target_civ.get('received_sanctions') or [])
                    if s['imposer_id'] != user_id]

        self.db.update_civilization(user_id, {"imposed_sanctions": imposed})
        self.db.update_civilization(target_id, {"received_sanctions": received})
        self.civ_manager._invalidate_civ(user_id)
        self.civ_manager._invalidate_civ(target_id)
        self.civ_manager.apply_faction_effects(user_id, "lift_sanction")
        await ctx.send(f"✅ Sanctions lifted on **{target_civ['name']}**.")
        self.db.log_event(user_id, "sanction_lifted", "Sanction Lifted",
                          f"Lifted sanctions on {target_civ['name']}")

    @commands.command(name='sanctions')
    async def list_sanctions(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first.")
            return

        now = datetime.utcnow()
        imposed = [s for s in (civ.get('imposed_sanctions') or [])
                   if datetime.fromisoformat(s['expires_at']) > now]
        received = [s for s in (civ.get('received_sanctions') or [])
                    if datetime.fromisoformat(s['expires_at']) > now]

        embed = discord.Embed(title="🚫 Sanction Registry", color=discord.Color.dark_red())

        if imposed:
            lines = []
            for s in imposed:
                tc = self.civ_manager.get_civilization(s['target_id'])
                name = tc['name'] if tc else s['target_id'][:6]
                ts = int(datetime.fromisoformat(s['expires_at']).timestamp())
                lines.append(f"→ **{name}** — <t:{ts}:R> — *{s.get('reason','')}*")
            embed.add_field(name="You Imposed", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="You Imposed", value="None", inline=False)

        if received:
            lines = []
            for s in received:
                ic = self.civ_manager.get_civilization(s['imposer_id'])
                name = ic['name'] if ic else s['imposer_id'][:6]
                ts = int(datetime.fromisoformat(s['expires_at']).timestamp())
                lines.append(f"← **{name}** — <t:{ts}:R> — *{s.get('reason','')}*")
            embed.add_field(name="You Received", value="\n".join(lines), inline=False)
            embed.add_field(
                name="⚠️ Active Penalties",
                value=(f"• Income × {config.SANCTIONS['resource_income_multiplier']}\n"
                       f"• `.globaltrade`, `.trade`, `.bank` blocked\n"
                       f"• −{config.SANCTIONS['happiness_penalty_per_tick']} happiness/tick"),
                inline=False,
            )
        else:
            embed.add_field(name="You Received", value="None", inline=False)

        await ctx.send(embed=embed)

    # =================================================================
    # BANK
    # =================================================================
    def _is_sanctioned_local(self, user_id: str) -> bool:
        try:
            civ = self.civ_manager.get_civilization(user_id)
            if not civ:
                return False
            now = datetime.utcnow()
            for s in (civ.get('received_sanctions') or []):
                if datetime.fromisoformat(s['expires_at']) > now:
                    return True
            return False
        except Exception:
            return False

    def _bank_state(self, civ: dict) -> dict:
        b = civ.get('bank') or {}
        return {
            "deposits": int(b.get('deposits', 0)),
            "loan": int(b.get('loan', 0)),
            "loan_opened_at": b.get('loan_opened_at'),
            "credit_score": int(b.get('credit_score', 100)),
            "locked_until": b.get('locked_until'),
        }

    def _is_bank_locked(self, bank: dict) -> bool:
        lu = bank.get('locked_until')
        if not lu:
            return False
        try:
            return datetime.fromisoformat(lu) > datetime.utcnow()
        except Exception:
            return False

    @commands.group(name='bank', invoke_without_command=True)
    async def bank(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if self._is_sanctioned_local(user_id):
            await ctx.send("🚫 **You are under sanctions.** Banking is frozen.")
            return

        bank = self._bank_state(civ)
        if self._is_bank_locked(bank):
            exp = datetime.fromisoformat(bank['locked_until'])
            await ctx.send(
                f"🚫 Your account is locked until <t:{int(exp.timestamp())}:R> (default). "
                f"Credit: {bank['credit_score']}/100."
            )
            return

        dr = config.BANKING['deposit_rate'] * 100
        lr = config.BANKING['loan_rate'] * 100
        pocket = civ['resources']['gold']
        net = pocket + bank['deposits'] - bank['loan']

        embed = discord.Embed(
            title=f"🏦 {civ['name']} — Central Bank",
            description=(f"**Pocket gold:** 🪙 {format_number(pocket)}\n"
                         f"**Deposits:** 🪙 {format_number(bank['deposits'])} ({dr:.2f}%/hr)\n"
                         f"**Outstanding loan:** 🪙 {format_number(bank['loan'])} ({lr:.2f}%/hr)\n"
                         f"**Net worth:** 🪙 {format_number(net)}\n"
                         f"**Credit score:** {bank['credit_score']}/100"),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(
            name="Commands",
            value=("`.bank deposit <amount>` — earn hourly interest\n"
                   "`.bank withdraw <amount>` — pull funds out\n"
                   "`.bank loan <amount>` — borrow (limit = 30% of net)\n"
                   "`.bank repay <amount>` — pay down the loan"),
            inline=False,
        )
        if bank['loan'] > 0 and bank['loan_opened_at']:
            try:
                opened = datetime.fromisoformat(bank['loan_opened_at'])
                days = (datetime.utcnow() - opened).days
                if days >= 1:
                    embed.set_footer(
                        text=f"Loan opened {days}d ago. Default at "
                             f"{config.BANKING['default_days']}d."
                    )
            except Exception:
                pass
        await ctx.send(embed=embed)

    @bank.command(name='deposit')
    async def bank_deposit(self, ctx, amount: int = None):
        if amount is None or amount <= 0:
            await ctx.send("Usage: `.bank deposit <amount>`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if self._is_sanctioned_local(user_id):
            await ctx.send("🚫 **You are under sanctions.** Deposits are frozen.")
            return
        bank = self._bank_state(civ)
        if self._is_bank_locked(bank):
            await ctx.send("🚫 Your bank account is locked (default).")
            return
        if not self.civ_manager.can_afford(user_id, {"gold": amount}):
            await ctx.send(f"❌ You don't have {format_number(amount)} gold.")
            return

        self.civ_manager.spend_resources(user_id, {"gold": amount})
        bank['deposits'] += amount
        self.db.update_civilization(user_id, {"bank": bank})
        self.civ_manager._invalidate_civ(user_id)
        self.civ_manager.apply_faction_effects(user_id, "bank_deposit")
        await ctx.send(f"🏦 Deposited **{format_number(amount)}** gold. "
                       f"Balance: {format_number(bank['deposits'])}.")

    @bank.command(name='withdraw')
    async def bank_withdraw(self, ctx, amount: int = None):
        if amount is None or amount <= 0:
            await ctx.send("Usage: `.bank withdraw <amount>`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if self._is_sanctioned_local(user_id):
            await ctx.send("🚫 **You are under sanctions.** Withdrawals are frozen.")
            return
        bank = self._bank_state(civ)
        if self._is_bank_locked(bank):
            await ctx.send("🚫 Your bank account is locked (default).")
            return
        if bank['deposits'] < amount:
            await ctx.send(f"❌ You only have {format_number(bank['deposits'])} in the bank.")
            return
        bank['deposits'] -= amount
        self.db.update_civilization(user_id, {"bank": bank})
        self.civ_manager.update_resources(user_id, {"gold": amount})
        self.civ_manager._invalidate_civ(user_id)
        await ctx.send(f"🏦 Withdrew **{format_number(amount)}** gold. "
                       f"Balance: {format_number(bank['deposits'])}.")

    @bank.command(name='loan')
    async def bank_loan(self, ctx, amount: int = None):
        if amount is None or amount <= 0:
            await ctx.send("Usage: `.bank loan <amount>`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if self._is_sanctioned_local(user_id):
            await ctx.send("🚫 **You are under sanctions.** Loans are frozen.")
            return
        bank = self._bank_state(civ)
        if self._is_bank_locked(bank):
            await ctx.send("🚫 Your bank account is locked (default).")
            return
        if bank['loan'] > 0:
            await ctx.send(f"❌ You already have an outstanding loan of "
                           f"{format_number(bank['loan'])}. Repay it first.")
            return

        net = civ['resources']['gold'] + bank['deposits']
        limit = min(
            config.BANKING['max_loan_absolute'],
            int(net * config.BANKING['max_loan_fraction']),
        )
        limit = max(100, int(limit * (bank['credit_score'] / 100)))

        if amount > limit:
            await ctx.send(f"❌ Loan limit is {format_number(limit)} gold "
                           f"(based on net worth and credit score).")
            return

        bank['loan'] = amount
        bank['loan_opened_at'] = datetime.utcnow().isoformat()
        self.db.update_civilization(user_id, {"bank": bank})
        self.civ_manager.update_resources(user_id, {"gold": amount})
        self.civ_manager._invalidate_civ(user_id)
        self.civ_manager.apply_faction_effects(user_id, "bank_loan")
        await ctx.send(
            f"🏦 Borrowed **{format_number(amount)}** gold. "
            f"Interest: {config.BANKING['loan_rate']*100:.2f}%/hr. "
            f"Default at {config.BANKING['default_days']} days unpaid."
        )

    @bank.command(name='repay')
    async def bank_repay(self, ctx, amount: int = None):
        if amount is None or amount <= 0:
            await ctx.send("Usage: `.bank repay <amount>`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        if self._is_sanctioned_local(user_id):
            await ctx.send("🚫 **You are under sanctions.** Repayments are frozen.")
            return
        bank = self._bank_state(civ)
        if bank['loan'] <= 0:
            await ctx.send("❌ You don't have a loan.")
            return
        amount = min(amount, bank['loan'])
        if not self.civ_manager.can_afford(user_id, {"gold": amount}):
            await ctx.send(f"❌ You don't have {format_number(amount)} gold.")
            return
        self.civ_manager.spend_resources(user_id, {"gold": amount})
        bank['loan'] -= amount
        if bank['loan'] == 0:
            bank['loan_opened_at'] = None
            bank['credit_score'] = min(100, bank['credit_score'] + 5)
        self.db.update_civilization(user_id, {"bank": bank})
        self.civ_manager._invalidate_civ(user_id)
        await ctx.send(f"🏦 Repaid **{format_number(amount)}** gold. "
                       f"Remaining loan: {format_number(bank['loan'])}.")


async def setup(bot):
    await bot.add_cog(BasicCommands(bot))
