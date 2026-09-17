import random
import asyncio
import discord
from discord.ext import commands
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from bot import config

logger = logging.getLogger(__name__)

MAX_ANNEX_TERRITORIES = 5
ANNEX_FRACTION_CAP = 0.25


class DiplomacyCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager

    # ============================================================
    # INTERNAL HELPERS
    # ============================================================
    def _are_allied(self, user_a: str, user_b: str) -> bool:
        try:
            docs = self.db.client.collection("alliances").where("members", "array_contains", user_a).stream()
            for doc in docs:
                if user_b in doc.to_dict().get("members", []):
                    return True
            return False
        except Exception as e:
            logger.error(f"_are_allied error: {e}")
            return False

    def _is_sanctioned(self, user_id: str) -> bool:
        """True if this civ currently has any active received sanction."""
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

    def _check_cooldown(self, ctx, command_name: str):
        minutes = config.COOLDOWNS.get(command_name, 0)
        if minutes <= 0:
            return True, None
        user_id = str(ctx.author.id)
        last_used = self.db.get_command_cooldown(user_id, command_name)
        if last_used:
            cooldown_end = last_used + timedelta(minutes=minutes)
            if datetime.utcnow() < cooldown_end:
                remaining = cooldown_end - datetime.utcnow()
                mins = int(remaining.total_seconds() // 60)
                secs = int(remaining.total_seconds() % 60)
                return False, f"⏳ Please wait {mins}m {secs}s before using this command again!"
        self.db.set_command_cooldown(user_id, command_name, datetime.utcnow())
        return True, None

    def _check_war(self, a_id: str, b_id: str) -> bool:
        for war in self.db.get_wars(status="ongoing"):
            a = war.get("attacker_id")
            d = war.get("defender_id")
            if (a == a_id and d == b_id) or (a == b_id and d == a_id):
                return True
        return False

    # ============================================================
    # ALLIANCES
    # ============================================================
    @commands.command(name='ally')
    async def propose_alliance(self, ctx, target: discord.Member = None, *, alliance_name: str = None):
        if not target or not alliance_name:
            await ctx.send("🤝 **Alliance Proposal**\nUsage: `.ally <user> <alliance_name>`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        target_id = str(target.id)
        if target_id == user_id:
            await ctx.send("❌ You cannot ally with yourself!")
            return
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target user doesn't have a civilization!")
            return
        if self._check_war(user_id, target_id):
            await ctx.send("❌ You cannot ally with someone you're at war with!")
            return
        if self._are_allied(user_id, target_id):
            await ctx.send("❌ You're already in an alliance together!")
            return
        alliance_id = str(random.randint(100000, 999999))
        self.db.save_alliance_proposal(alliance_id, {
            "proposer_id": user_id,
            "target_id": target_id,
            "alliance_name": alliance_name,
            "expires": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            "created_at": datetime.utcnow().isoformat(),
        })
        embed = discord.Embed(title="🤝 Alliance Proposal Received!",
                              description=f"From **{civ['name']}** (led by {ctx.author.name})",
                              color=discord.Color.blue())
        embed.add_field(name="Proposed Alliance",
                        value=f"Alliance Name: **{alliance_name}**", inline=False)
        embed.add_field(name="How to Respond",
                        value=f"`.acceptally {alliance_id}` or `.rejectally {alliance_id}`\nExpires in 30 minutes.",
                        inline=False)
        await ctx.send(f"<@{target_id}>", embed=embed)
        await ctx.send(f"🤝 **Alliance Proposed!** Sent to **{target_civ['name']}**.")

    @commands.command(name='acceptally')
    async def accept_alliance(self, ctx, alliance_id: str = None):
        if not alliance_id:
            await ctx.send("Usage: `.acceptally <id>`")
            return
        user_id = str(ctx.author.id)
        proposal = self.db.get_alliance_proposal(alliance_id)
        if not proposal:
            await ctx.send("❌ Invalid or expired alliance ID!")
            return
        if user_id != proposal["target_id"]:
            await ctx.send("❌ This proposal isn't for you!")
            return
        success = self.db.create_alliance(proposal["alliance_name"], proposal["proposer_id"], description="")
        if not success:
            await ctx.send("❌ Failed to create alliance.")
            return
        alliance = self.db.get_alliance_by_name(proposal["alliance_name"])
        if alliance:
            self.db.add_alliance_member(alliance["id"], user_id)
        embed = discord.Embed(title="🤝 Alliance Formed!",
                              description=f"**{proposal['alliance_name']}** has been established!",
                              color=discord.Color.green())
        await ctx.send(embed=embed)
        await ctx.send(f"<@{proposal['proposer_id']}> 🤝 **Alliance Accepted!**")
        # Faction deltas both sides
        self.civ_manager.apply_faction_effects(user_id, "ally")
        self.civ_manager.apply_faction_effects(proposal["proposer_id"], "ally")
        self.db.delete_alliance_proposal(alliance_id)

    @commands.command(name='rejectally')
    async def reject_alliance(self, ctx, alliance_id: str = None):
        if not alliance_id:
            await ctx.send("Usage: `.rejectally <id>`")
            return
        user_id = str(ctx.author.id)
        proposal = self.db.get_alliance_proposal(alliance_id)
        if not proposal:
            await ctx.send("❌ Invalid or expired!")
            return
        if user_id != proposal["target_id"]:
            await ctx.send("❌ Not for you!")
            return
        await ctx.send(f"<@{proposal['proposer_id']}> 🤝 **Alliance Rejected!**")
        await ctx.send("🤝 **Rejected.**")
        self.db.delete_alliance_proposal(alliance_id)

    @commands.command(name='break')
    async def break_alliance(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        alliance_doc = None
        for doc in self.db.client.collection("alliances").where("members", "array_contains", user_id).stream():
            alliance_doc = doc
            break
        if not alliance_doc:
            await ctx.send("❌ You are not in an alliance!")
            return
        alliance_data = alliance_doc.to_dict()
        members = alliance_data.get("members", [])
        if len(members) <= 2:
            alliance_doc.reference.delete()
        else:
            members.remove(user_id)
            alliance_doc.reference.update({"members": members})
        self.civ_manager.update_population(user_id, {"happiness": -10})
        self.civ_manager.apply_faction_effects(user_id, "break_alliance")
        embed = discord.Embed(title="💔 Alliance Broken",
                              description=f"Left the **{alliance_data['name']}** alliance.",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        for member_id in members:
            if member_id != user_id:
                await ctx.send(f"<@{member_id}> 💔 {civ['name']} left the **{alliance_data['name']}** alliance.")

    # ============================================================
    # SEND / TRADE
    # ============================================================
    @commands.command(name='send')
    async def send_resources(self, ctx, target: discord.Member = None,
                             resource_type: str = None, amount: int = None):
        if not target or not resource_type or amount is None:
            await ctx.send("📦 **Resource Transfer**\nUsage: `.send <user> <gold|food|wood|stone> <amount>`")
            return
        resource_type = resource_type.lower()
        if resource_type not in ('gold', 'food', 'wood', 'stone'):
            await ctx.send("❌ Invalid resource type! Choose from: gold, food, wood, stone.")
            return
        if amount < 1:
            await ctx.send("❌ Amount must be positive!")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        target_id = str(target.id)
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target has no civilization!")
            return
        if not self.civ_manager.can_afford(user_id, {resource_type: amount}):
            await ctx.send(f"❌ You don't have {amount} {resource_type}!")
            return
        is_allied = self._are_allied(user_id, target_id)
        efficiency = 0.95 if is_allied else 0.9
        received = int(amount * efficiency)
        self.civ_manager.spend_resources(user_id, {resource_type: amount})
        self.civ_manager.update_resources(target_id, {resource_type: received})
        icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        embed = discord.Embed(title="📦 Resources Sent",
                              description=f"Sent to **{target_civ['name']}**!",
                              color=discord.Color.blue())
        embed.add_field(name="Transfer",
                        value=f"{icons[resource_type]} Sent: {amount}\n{icons[resource_type]} Received: {received}\n📊 Efficiency: {int(efficiency * 100)}%",
                        inline=False)
        if is_allied:
            embed.add_field(name="Alliance Bonus", value="Higher efficiency!", inline=False)
        await ctx.send(embed=embed)
        await ctx.send(f"<@{target_id}> 📦 **Received** {received} {resource_type} from {civ['name']}!")
        self.civ_manager.apply_faction_effects(user_id, "send_resources")

    @commands.command(name='trade')
    async def propose_trade(self, ctx, target: discord.Member = None,
                            offer_resource: str = None, offer_amount: int = None,
                            request_resource: str = None, request_amount: int = None):
        if not all([target, offer_resource, offer_amount, request_resource, request_amount]):
            await ctx.send("💰 **Trade**\nUsage: `.trade <user> <offer_resource> <offer_amount> <request_resource> <request_amount>`")
            return
        offer_resource = offer_resource.lower()
        request_resource = request_resource.lower()
        valid = ['gold', 'food', 'wood', 'stone']
        if offer_resource not in valid or request_resource not in valid:
            await ctx.send(f"❌ Invalid resource! Choose from: {', '.join(valid)}")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        target_id = str(target.id)
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target has no civilization!")
            return

        # --- Sanctions block ---
        if self._is_sanctioned(user_id):
            await ctx.send("🚫 **You are under sanctions.** You cannot propose trades.")
            return
        if self._is_sanctioned(target_id):
            await ctx.send(f"🚫 **{target_civ['name']}** is under sanctions. Trade proposals to them are blocked.")
            return

        if not self.civ_manager.can_afford(user_id, {offer_resource: offer_amount}):
            await ctx.send(f"❌ You don't have {offer_amount} {offer_resource}!")
            return
        trade_id = str(random.randint(100000, 999999))
        self.db.save_trade_proposal(trade_id, {
            "proposer_id": user_id, "target_id": target_id,
            "offer_resource": offer_resource, "offer_amount": offer_amount,
            "request_resource": request_resource, "request_amount": request_amount,
            "expires": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            "created_at": datetime.utcnow().isoformat(),
        })
        icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        embed = discord.Embed(title="💰 Trade Proposal",
                              description=f"From **{civ['name']}**",
                              color=discord.Color.blue())
        embed.add_field(name="Terms",
                        value=(f"They offer: {icons[offer_resource]} {offer_amount} {offer_resource.capitalize()}\n"
                               f"They request: {icons[request_resource]} {request_amount} {request_resource.capitalize()}"),
                        inline=False)
        embed.add_field(name="Respond",
                        value=f"`.accepttrade {trade_id}` or `.rejecttrade {trade_id}`\nExpires in 30 min.",
                        inline=False)
        await ctx.send(f"<@{target_id}>", embed=embed)
        await ctx.send("💰 **Trade Proposed!**")

    @commands.command(name='accepttrade')
    async def accept_trade(self, ctx, trade_id: str = None):
        if not trade_id:
            await ctx.send("Usage: `.accepttrade <id>`")
            return
        user_id = str(ctx.author.id)
        trade = self.db.get_trade_proposal(trade_id)
        if not trade:
            await ctx.send("❌ Invalid or expired trade ID!")
            return
        if user_id != trade["target_id"]:
            await ctx.send("❌ Not for you!")
            return

        # --- Sanctions block ---
        if self._is_sanctioned(user_id) or self._is_sanctioned(trade["proposer_id"]):
            await ctx.send("🚫 **Sanctions in effect.** This trade cannot be completed while either party is sanctioned.")
            self.db.delete_trade_proposal(trade_id)
            return

        if not self.civ_manager.can_afford(trade["proposer_id"], {trade["offer_resource"]: trade["offer_amount"]}):
            await ctx.send("❌ Proposer no longer has the offered resources!")
            self.db.delete_trade_proposal(trade_id)
            return
        if not self.civ_manager.can_afford(user_id, {trade["request_resource"]: trade["request_amount"]}):
            await ctx.send("❌ You no longer have the requested resources!")
            self.db.delete_trade_proposal(trade_id)
            return
        self.civ_manager.spend_resources(trade["proposer_id"], {trade["offer_resource"]: trade["offer_amount"]})
        self.civ_manager.update_resources(trade["proposer_id"], {trade["request_resource"]: trade["request_amount"]})
        self.civ_manager.spend_resources(user_id, {trade["request_resource"]: trade["request_amount"]})
        self.civ_manager.update_resources(user_id, {trade["offer_resource"]: trade["offer_amount"]})
        await ctx.send(f"<@{trade['proposer_id']}> 💰 **Trade Accepted!**")
        await ctx.send("💰 **Trade Accepted!**")
        # Faction deltas both sides
        self.civ_manager.apply_faction_effects(user_id, "trade_accepted")
        self.civ_manager.apply_faction_effects(trade["proposer_id"], "trade_accepted")
        self.db.delete_trade_proposal(trade_id)

    @commands.command(name='rejecttrade')
    async def reject_trade(self, ctx, trade_id: str = None):
        if not trade_id:
            await ctx.send("Usage: `.rejecttrade <id>`")
            return
        user_id = str(ctx.author.id)
        trade = self.db.get_trade_proposal(trade_id)
        if not trade:
            await ctx.send("❌ Invalid trade!")
            return
        if user_id != trade["target_id"]:
            await ctx.send("❌ Not for you!")
            return
        await ctx.send(f"<@{trade['proposer_id']}> 💰 **Trade Rejected!**")
        await ctx.send("💰 **Rejected.**")
        self.db.delete_trade_proposal(trade_id)

    # ============================================================
    # MAIL
    # ============================================================
    @commands.command(name='mail')
    async def send_diplomatic_message(self, ctx, target: discord.Member = None, *, message: str = None):
        if not target or not message:
            await ctx.send("📜 **Mail**\nUsage: `.mail <user> <message>`")
            return
        if len(message) > 500:
            await ctx.send("❌ Message too long! Max 500 chars.")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        target_id = str(target.id)
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target has no civilization!")
            return
        self.db.send_message(user_id, target_id, message)
        await ctx.send(f"<@{target_id}> 📜 Mail from {civ['name']}! Check `.inbox`.")
        await ctx.send("📜 **Sent.**")

    @commands.command(name='inbox')
    async def check_inbox(self, ctx):
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        embed = discord.Embed(title="📬 Inbox",
                              description=f"Pending proposals for **{civ['name']}**",
                              color=discord.Color.blue())

        # Alliance proposals
        alliance_proposals = []
        for proposal in self.db.get_alliance_proposals_for_user(user_id):
            proposer_civ = self.civ_manager.get_civilization(proposal["proposer_id"])
            if proposer_civ:
                exp_raw = proposal.get("expires")
                exp_dt = datetime.fromisoformat(exp_raw) if isinstance(exp_raw, str) else exp_raw
                exp_ts = int(exp_dt.timestamp()) if exp_dt else 0
                alliance_proposals.append(
                    f"**ID**: {proposal['id']} — from **{proposer_civ['name']}**\n"
                    f"Alliance: **{proposal['alliance_name']}**\n"
                    f"`.acceptally {proposal['id']}` / `.rejectally {proposal['id']}` | Expires <t:{exp_ts}:R>"
                )

        # Trade proposals
        trade_proposals = []
        icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        for trade in self.db.get_trade_proposals_for_user(user_id):
            proposer_civ = self.civ_manager.get_civilization(trade["proposer_id"])
            if proposer_civ:
                exp_raw = trade.get("expires")
                exp_dt = datetime.fromisoformat(exp_raw) if isinstance(exp_raw, str) else exp_raw
                exp_ts = int(exp_dt.timestamp()) if exp_dt else 0
                trade_proposals.append(
                    f"**ID**: {trade['id']} — from **{proposer_civ['name']}**\n"
                    f"Offers: {icons[trade['offer_resource']]} {trade['offer_amount']}\n"
                    f"Requests: {icons[trade['request_resource']]} {trade['request_amount']}\n"
                    f"`.accepttrade {trade['id']}` / `.rejecttrade {trade['id']}` | Expires <t:{exp_ts}:R>"
                )

        # Peace offers
        peace_offers_list = []
        for offer in self.db.get_peace_offers(user_id):
            if offer.get("receiver_id") != user_id:
                continue
            terms = offer.get("terms", {}) or {}
            offer_type = offer.get("type", "peace")
            exp_iso = offer.get("expires_at")
            exp_ts = 0
            if exp_iso:
                try:
                    exp_dt = datetime.fromisoformat(exp_iso)
                    exp_ts = int(exp_dt.timestamp())
                except Exception:
                    pass
            terms_summary = self._format_terms(terms, offer_type)
            peace_offers_list.append(
                f"**ID**: {offer['id']} — from **{offer.get('offerer_name','?')}** ({offer_type})\n"
                f"{terms_summary}\n"
                f"`.acceptpeace {offer['id']}` / `.rejectpeace {offer['id']}` | Expires <t:{exp_ts}:R>"
            )

        # Messages
        messages_list = []
        try:
            for m in self.db.get_messages(user_id):
                sender_civ = self.civ_manager.get_civilization(m['sender_id'])
                if sender_civ:
                    timestamp = m['created_at']
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    messages_list.append(
                        f"**From**: {sender_civ['name']}\n{m['message']}\n<t:{int(timestamp.timestamp())}:R>"
                    )
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")

        embed.add_field(name="🤝 Alliance Proposals",
                        value="\n\n".join(alliance_proposals) if alliance_proposals else "None.",
                        inline=False)
        embed.add_field(name="💰 Trade Proposals",
                        value="\n\n".join(trade_proposals) if trade_proposals else "None.",
                        inline=False)
        embed.add_field(name="🕊️ Peace Offers",
                        value="\n\n".join(peace_offers_list) if peace_offers_list else "None.",
                        inline=False)
        embed.add_field(name="📜 Messages",
                        value="\n\n".join(messages_list) if messages_list else "None.",
                        inline=False)

        await ctx.send(embed=embed)

    # ============================================================
    # SIMPLE PEACE (renamed from .peace to avoid clash with military)
    # ============================================================
    @commands.command(name='simplepeace', aliases=['sp'])
    async def simple_peace(self, ctx, target: discord.Member = None):
        if not target:
            await ctx.send("🕊️ **Simple Peace**\nUsage: `.simplepeace <user>` (alias `.sp`)\nFor a customizable deal, use `.peacedraft`.")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        target_id = str(target.id)
        if target_id == user_id:
            await ctx.send("❌ You're at peace with yourself!")
            return
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target has no civilization!")
            return
        if not self._check_war(user_id, target_id):
            await ctx.send("❌ You're not at war with them!")
            return
        existing = self.db.get_peace_offers(user_id)
        for offer in existing:
            if offer.get("offerer_id") == user_id and offer.get("receiver_id") == target_id:
                await ctx.send("❌ You already have a pending offer!")
                return
        offer_id = self.db.create_peace_offer(
            user_id, target_id, offer_type="peace",
            terms={"gold": 0, "food": 0, "wood": 0, "stone": 0,
                   "annex_territories": [], "ceasefire_hours": 0}
        )
        if not offer_id:
            await ctx.send("❌ Failed to create peace offer.")
            return
        embed = discord.Embed(title="🕊️ Peace Offer Sent",
                              description=f"**{civ['name']}** offered **permanent peace** to **{target_civ['name']}**.",
                              color=discord.Color.green())
        embed.add_field(name="No terms — just peace.",
                        value=f"Offer ID: `{offer_id}`\n`{target.mention}` respond with `.acceptpeace {offer_id}` or `.rejectpeace {offer_id}`",
                        inline=False)
        await ctx.send(embed=embed)
        try:
            await ctx.send(f"{target.mention} 🕊️ Peace offer received! Use `.acceptpeace {offer_id}`.")
        except Exception:
            pass
        self.civ_manager.apply_faction_effects(user_id, "peace_offer")

    # ============================================================
    # DRAFTED PEACE
    # ============================================================
    @commands.command(name='peacedraft')
    async def peace_draft(self, ctx, target: discord.Member = None):
        if not target:
            await ctx.send("🕊️ **Draft Peace**\nUsage: `.peacedraft <user>`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        target_id = str(target.id)
        if target_id == user_id:
            await ctx.send("❌ You cannot negotiate with yourself!")
            return
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target has no civilization!")
            return
        if not self._check_war(user_id, target_id):
            await ctx.send("❌ You're not at war with them!")
            return

        embed = discord.Embed(
            title="🕊️ Draft a Peace Deal",
            description=(
                f"Negotiating with **{target_civ['name']}**.\n"
                "You'll be asked for each term one at a time.\n"
                "**Type `skip` for any field** to leave it at 0.\n"
                "Whole draft expires in **5 minutes**."
            ),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        async def ask(question: str, max_val: Optional[int] = None) -> Optional[int]:
            await ctx.send(question)
            try:
                msg = await self.bot.wait_for('message', timeout=90, check=check)
                content = msg.content.strip().lower()
                if content == "skip" or content == "0":
                    return 0
                val = int(content)
                if val < 0:
                    return 0
                if max_val is not None and val > max_val:
                    val = max_val
                return val
            except asyncio.TimeoutError:
                return None
            except (ValueError, AttributeError):
                return None

        gold_demand = await ask(f"💰 **How much gold?** Target has {target_civ['resources']['gold']:,}.", target_civ['resources']['gold'])
        if gold_demand is None:
            await ctx.send("❌ Draft timed out.")
            return
        food_demand = await ask(f"🌾 **How much food?** Target has {target_civ['resources']['food']:,}.", target_civ['resources']['food'])
        if food_demand is None:
            await ctx.send("❌ Draft timed out.")
            return
        wood_demand = await ask(f"🪵 **How much wood?** Target has {target_civ['resources']['wood']:,}.", target_civ['resources']['wood'])
        if wood_demand is None:
            await ctx.send("❌ Draft timed out.")
            return
        stone_demand = await ask(f"🪨 **How much stone?** Target has {target_civ['resources']['stone']:,}.", target_civ['resources']['stone'])
        if stone_demand is None:
            await ctx.send("❌ Draft timed out.")
            return
        hours = await ask(
            "⏳ **Ceasefire duration in hours?**\n"
            "`0` = permanent peace (ends the war)\n"
            "Any positive = temporary ceasefire (war continues after)\n"
            "Max 720 hours (30 days).",
            max_val=720
        )
        if hours is None:
            await ctx.send("❌ Draft timed out.")
            return

        target_territories = self.db.get_player_territories(target_id)
        annex_list: List[str] = []
        if target_territories:
            max_annex = min(MAX_ANNEX_TERRITORIES, max(1, int(len(target_territories) * ANNEX_FRACTION_CAP)))
            preview = ", ".join(target_territories[:20])
            if len(target_territories) > 20:
                preview += f"... (+{len(target_territories) - 20} more)"
            await ctx.send(
                f"🏴 **Which territories to annex?**\n"
                f"You can annex up to **{max_annex}**.\n"
                f"Target owns: {preview}\n\n"
                f"Type comma-separated names, or `skip` for none."
            )
            try:
                msg = await self.bot.wait_for('message', timeout=90, check=check)
                content = msg.content.strip()
                if content.lower() != "skip":
                    requested = [t.strip() for t in content.split(",") if t.strip()]
                    matched = []
                    for req in requested:
                        for t in target_territories:
                            if t.lower() == req.lower():
                                matched.append(t)
                                break
                    annex_list = matched[:max_annex]
                    if len(matched) > max_annex:
                        await ctx.send(f"⚠️ Only first **{max_annex}** will be included.")
            except asyncio.TimeoutError:
                await ctx.send("❌ Draft timed out.")
                return

        terms = {
            "gold": gold_demand,
            "food": food_demand,
            "wood": wood_demand,
            "stone": stone_demand,
            "annex_territories": annex_list,
            "ceasefire_hours": hours,
        }
        summary = self._format_terms(terms, "peace")

        embed = discord.Embed(title="📜 Peace Deal Summary",
                              description=f"From **{civ['name']}** → **{target_civ['name']}**",
                              color=discord.Color.gold())
        embed.add_field(name="Terms", value=summary, inline=False)
        embed.set_footer(text="Type 'confirm' within 60s to send, or 'cancel' to abort.")
        await ctx.send(embed=embed)

        try:
            msg = await self.bot.wait_for('message', timeout=60, check=check)
            if msg.content.strip().lower() != "confirm":
                await ctx.send("🛑 Draft cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("❌ Draft timed out.")
            return

        offer_id = self.db.create_peace_offer(user_id, target_id, offer_type="peace", terms=terms)
        if not offer_id:
            await ctx.send("❌ Failed to create peace offer.")
            return
        embed = discord.Embed(title="🕊️ Peace Offer Sent!",
                              description=f"**{civ['name']}** sent terms to **{target_civ['name']}**.",
                              color=discord.Color.green())
        embed.add_field(name="Terms", value=summary, inline=False)
        embed.add_field(name="Respond",
                        value=f"`{target.mention}` — `.acceptpeace {offer_id}` or `.rejectpeace {offer_id}`",
                        inline=False)
        await ctx.send(embed=embed)
        self.civ_manager.apply_faction_effects(user_id, "peace_offer")

    # ============================================================
    # ACCEPT / REJECT PEACE
    # ============================================================
    @commands.command(name='acceptpeace')
    async def accept_peace(self, ctx, offer_id: str = None):
        if not offer_id:
            await ctx.send("Usage: `.acceptpeace <id>`")
            return
        user_id = str(ctx.author.id)
        offer = self.db.get_peace_offer_by_id(offer_id)
        if not offer:
            await ctx.send("❌ Invalid or expired peace offer.")
            return
        if offer.get("receiver_id") != user_id:
            await ctx.send("❌ Not for you!")
            return

        offerer_id = offer.get("offerer_id")
        offerer_civ = self.civ_manager.get_civilization(offerer_id)
        receiver_civ = self.civ_manager.get_civilization(user_id)
        if not offerer_civ or not receiver_civ:
            await ctx.send("❌ One of the civilizations no longer exists.")
            self.db.delete_peace_offer(offer_id)
            return

        terms = offer.get("terms", {}) or {}
        offer_type = offer.get("type", "peace")

        costs = {
            "gold": terms.get("gold", 0),
            "food": terms.get("food", 0),
            "wood": terms.get("wood", 0),
            "stone": terms.get("stone", 0),
        }
        if not self.civ_manager.can_afford(user_id, costs):
            await ctx.send("❌ You can no longer afford those terms!")
            self.db.delete_peace_offer(offer_id)
            return

        receiver_territories = set(self.db.get_player_territories(user_id))
        annex_list = terms.get("annex_territories", [])
        missing = [t for t in annex_list if t not in receiver_territories]
        if missing:
            await ctx.send(f"❌ You no longer own: {', '.join(missing)}.")
            self.db.delete_peace_offer(offer_id)
            return

        paid = {}
        for res, amt in costs.items():
            if amt > 0:
                self.civ_manager.spend_resources(user_id, {res: amt})
                self.civ_manager.update_resources(offerer_id, {res: amt})
                paid[res] = amt

        transferred = []
        territory_cog = self.bot.get_cog("TerritoryCog")
        for t in annex_list:
            success = self.db.conquer_territory(offerer_id, user_id, t)
            if success:
                area = territory_cog.province_areas.get(t, 1000) if territory_cog else 1000
                self.civ_manager.update_territory(offerer_id, {"land_size": area})
                self.civ_manager.update_territory(user_id, {"land_size": -area})
                transferred.append(t)

        ceasefire_hours = terms.get("ceasefire_hours", 0)
        if ceasefire_hours and ceasefire_hours > 0:
            self.db.create_ceasefire(offerer_id, user_id, ceasefire_hours)
            war_ended = False
        else:
            self.db.end_war(offerer_id, user_id, "peace")
            war_ended = True

        self.civ_manager.update_population(user_id, {"happiness": 15})
        self.civ_manager.update_population(offerer_id, {"happiness": 15})
        self.db.delete_peace_offer(offer_id)

        # Faction deltas both sides
        self.civ_manager.apply_faction_effects(user_id, "accept_peace")
        self.civ_manager.apply_faction_effects(offerer_id, "accept_peace")

        icons = {"gold": "🪙", "food": "🌾", "wood": "🪵", "stone": "🪨"}
        embed = discord.Embed(
            title="🕊️ Peace Deal Accepted!" if war_ended else "⏳ Ceasefire Accepted!",
            description=f"**{receiver_civ['name']}** accepted terms from **{offerer_civ['name']}**.",
            color=discord.Color.green()
        )
        if paid:
            embed.add_field(name="Resources Transferred",
                            value="\n".join([f"{icons[r]} {v:,} {r.capitalize()}" for r, v in paid.items()]),
                            inline=False)
        if transferred:
            embed.add_field(name="Territories Annexed",
                            value=", ".join(transferred),
                            inline=False)
        if ceasefire_hours and ceasefire_hours > 0:
            embed.add_field(name="Ceasefire Duration",
                            value=f"{ceasefire_hours} hours",
                            inline=False)
        else:
            embed.add_field(name="War Status", value="⚔️ **War Ended** — permanent peace.", inline=False)
        embed.add_field(name="Morale Boost", value="Both nations gain +15 happiness.", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='rejectpeace')
    async def reject_peace(self, ctx, offer_id: str = None):
        if not offer_id:
            await ctx.send("Usage: `.rejectpeace <id>`")
            return
        user_id = str(ctx.author.id)
        offer = self.db.get_peace_offer_by_id(offer_id)
        if not offer:
            await ctx.send("❌ Invalid or expired.")
            return
        if offer.get("receiver_id") != user_id:
            await ctx.send("❌ Not for you!")
            return
        offerer_id = offer.get("offerer_id")
        self.db.delete_peace_offer(offer_id)
        await ctx.send(f"<@{offerer_id}> 🕊️ **Peace offer rejected!**")
        await ctx.send("🕊️ **Rejected.**")

    @commands.command(name='peaceinfo')
    async def peace_info(self, ctx, offer_id: str = None):
        if not offer_id:
            await ctx.send("Usage: `.peaceinfo <id>`")
            return
        offer = self.db.get_peace_offer_by_id(offer_id)
        if not offer:
            await ctx.send("❌ Invalid or expired.")
            return
        terms = offer.get("terms", {}) or {}
        offer_type = offer.get("type", "peace")
        summary = self._format_terms(terms, offer_type)
        embed = discord.Embed(title=f"📜 Peace Offer {offer_id}",
                              description=f"From <@{offer.get('offerer_id')}> → <@{offer.get('receiver_id')}>",
                              color=discord.Color.blue())
        embed.add_field(name="Type", value=offer_type.capitalize(), inline=True)
        embed.add_field(name="Terms", value=summary, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='myoffers')
    async def my_offers(self, ctx):
        user_id = str(ctx.author.id)
        offers = self.db.get_peace_offers(user_id)
        if not offers:
            await ctx.send("📭 You have no pending peace offers.")
            return
        embed = discord.Embed(title="📭 Your Peace Offers", color=discord.Color.blue())
        for offer in offers:
            direction = "📤 SENT" if offer.get("offerer_id") == user_id else "📥 RECEIVED"
            terms = offer.get("terms", {}) or {}
            summary = self._format_terms(terms, offer.get("type", "peace"))
            embed.add_field(name=f"{direction} — ID `{offer['id']}`", value=summary, inline=False)
        await ctx.send(embed=embed)

    # ============================================================
    # CEASEFIRE
    # ============================================================
    @commands.command(name='ceasefire')
    async def ceasefire(self, ctx, target: discord.Member = None, hours: int = None):
        if not target or hours is None:
            await ctx.send("⏳ **Ceasefire**\nUsage: `.ceasefire <user> <hours>`\nMax 720 hours (30 days).")
            return
        if hours < 1 or hours > 720:
            await ctx.send("❌ Hours must be between 1 and 720.")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        target_id = str(target.id)
        if target_id == user_id:
            await ctx.send("❌ You cannot ceasefire with yourself!")
            return
        target_civ = self.civ_manager.get_civilization(target_id)
        if not target_civ:
            await ctx.send("❌ Target has no civilization!")
            return
        if not self._check_war(user_id, target_id):
            await ctx.send("❌ You're not at war with them!")
            return
        active = self.db.get_active_ceasefire(user_id, target_id)
        if active:
            await ctx.send("❌ There's already an active ceasefire!")
            return
        offer_id = self.db.create_peace_offer(
            user_id, target_id, offer_type="ceasefire",
            terms={"ceasefire_hours": hours}
        )
        if not offer_id:
            await ctx.send("❌ Failed to create ceasefire proposal.")
            return
        embed = discord.Embed(
            title="⏳ Ceasefire Proposed",
            description=f"**{civ['name']}** → **{target_civ['name']}** for **{hours} hours**.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Terms",
                        value=f"War continues, but no military actions for {hours}h.",
                        inline=False)
        embed.add_field(name="Respond",
                        value=f"`{target.mention}` — `.acceptpeace {offer_id}` or `.rejectpeace {offer_id}`",
                        inline=False)
        await ctx.send(embed=embed)
        self.civ_manager.apply_faction_effects(user_id, "ceasefire")

    @commands.command(name='ceasefires')
    async def list_ceasefires(self, ctx):
        user_id = str(ctx.author.id)
        ceasefires = self.db.get_all_ceasefires_for_user(user_id)
        if not ceasefires:
            await ctx.send("📭 No active ceasefires.")
            return
        embed = discord.Embed(title="⏳ Active Ceasefires", color=discord.Color.blue())
        for cf in ceasefires:
            other_id = cf.get("civ_b") if cf.get("civ_a") == user_id else cf.get("civ_a")
            other_civ = self.civ_manager.get_civilization(other_id)
            other_name = other_civ['name'] if other_civ else other_id[:6]
            exp_iso = cf.get("expires_at", "")
            exp_ts = 0
            try:
                exp_dt = datetime.fromisoformat(exp_iso)
                exp_ts = int(exp_dt.timestamp())
            except Exception:
                pass
            embed.add_field(name=f"vs **{other_name}**", value=f"Expires <t:{exp_ts}:R>", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='breakceasefire')
    async def break_ceasefire(self, ctx, target: discord.Member = None):
        if not target:
            await ctx.send("Usage: `.breakceasefire <user>`")
            return
        user_id = str(ctx.author.id)
        target_id = str(target.id)
        cf = self.db.get_active_ceasefire(user_id, target_id)
        if not cf:
            await ctx.send("❌ No active ceasefire between you.")
            return
        try:
            self.db.client.collection("ceasefires").document(cf["id"]).delete()
        except Exception as e:
            logger.error(f"Failed to delete ceasefire: {e}")
        self.civ_manager.update_population(user_id, {"happiness": -15})
        self.civ_manager.apply_faction_effects(user_id, "break_alliance")  # shares penalty
        embed = discord.Embed(title="💔 Ceasefire Broken",
                              description=f"**{ctx.author.display_name}** broke the ceasefire with **{target.display_name}**.",
                              color=discord.Color.red())
        embed.add_field(name="Consequence", value="-15 happiness", inline=False)
        await ctx.send(embed=embed)

    # ============================================================
    # UTIL
    # ============================================================
    def _format_terms(self, terms: dict, offer_type: str) -> str:
        lines = []
        if offer_type == "ceasefire":
            hours = terms.get("ceasefire_hours", 0)
            lines.append(f"⏳ Ceasefire for **{hours}** hours")
            return "\n".join(lines)

        gold = terms.get("gold", 0)
        food = terms.get("food", 0)
        wood = terms.get("wood", 0)
        stone = terms.get("stone", 0)
        annex = terms.get("annex_territories", [])
        hours = terms.get("ceasefire_hours", 0)

        if gold:
            lines.append(f"🪙 **{gold:,}** gold")
        if food:
            lines.append(f"🌾 **{food:,}** food")
        if wood:
            lines.append(f"🪵 **{wood:,}** wood")
        if stone:
            lines.append(f"🪨 **{stone:,}** stone")
        if annex:
            lines.append(f"🏴 Annex: **{', '.join(annex)}**")
        if hours and hours > 0:
            lines.append(f"⏳ Ceasefire: **{hours}** hours (war continues)")
        else:
            lines.append("🕊️ **Permanent peace** (war ends)")

        if not lines:
            lines.append("*No terms — pure peace.*")
        return "\n".join(lines)

    # ============================================================
    # COALITION
    # ============================================================
    @commands.command(name='coalition')
    async def form_coalition(self, ctx, *, target_alliance: str = None):
        if not target_alliance:
            await ctx.send("⚔️ **Coalition**\nUsage: `.coalition <target_alliance_name>`")
            return
        user_id = str(ctx.author.id)
        civ = self.civ_manager.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You need a civilization first!")
            return
        user_alliance_doc = None
        for doc in self.db.client.collection("alliances").where("members", "array_contains", user_id).stream():
            user_alliance_doc = doc
            break
        if not user_alliance_doc:
            await ctx.send("❌ You must be in an alliance!")
            return
        user_alliance_data = user_alliance_doc.to_dict()
        target_alliance_data = self.db.get_alliance_by_name(target_alliance)
        if not target_alliance_data:
            await ctx.send(f"❌ Alliance '{target_alliance}' not found!")
            return
        if user_alliance_data['name'] == target_alliance:
            await ctx.send("❌ Cannot target your own alliance!")
            return
        user_members = user_alliance_data.get("members", [])
        target_members = target_alliance_data.get("members", [])
        success_chance = min(0.8, len(user_members) / max(1, len(target_members)))
        if random.random() < success_chance:
            embed = discord.Embed(title="⚔️ Coalition Formed!",
                                  description=f"**{user_alliance_data['name']}** formed a coalition against **{target_alliance}**!",
                                  color=discord.Color.red())
            for m in user_members + target_members:
                if m != user_id:
                    if m in user_members:
                        await ctx.send(f"<@{m}> ⚔️ Coalition formed against {target_alliance}!")
                    else:
                        await ctx.send(f"<@{m}> ⚔️ Coalition formed against your alliance!")
            await ctx.send(embed=embed)
            self.civ_manager.apply_faction_effects(user_id, "coalition")
        else:
            embed = discord.Embed(title="⚔️ Coalition Failed",
                                  description=f"Failed coalition against **{target_alliance}**.",
                                  color=discord.Color.red())
            embed.add_field(name="Consequence", value="-10 happiness", inline=False)
            self.civ_manager.update_population(user_id, {"happiness": -10})
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(DiplomacyCommands(bot))
