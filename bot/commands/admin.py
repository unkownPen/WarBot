import discord
import io
import os
import logging
import asyncio
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone

try:
    from firebase_admin import firestore
except ImportError:
    firestore = None

logger = logging.getLogger(__name__)


# =================================================================
# OWNER GATE — only this user can run .reinstall
# =================================================================
HOLLOW_USER_IDS = {
    1221063035842727998,
}
HOLLOW_USERNAMES = {"hollow_x2"}


# =================================================================
# FULL WIPE COLLECTIONS
# =================================================================
# Everything that represents season-specific player state.
# Add new collections to this list as you build new features.
WIPE_COLLECTIONS = [
    "civilizations",
    "territories",
    "territory_history",
    "wars",
    "peace_offers",
    "alliances",
    "alliance_proposals",
    "trade_proposals",
    "messages",
    "divisions",
    "generals",
    "pending_attacks",
    "corporations",
    "dailies",
    "navy",
    "airforce",
    "military_tech",
    "training",
    "borders",
    "industrial_revolutions",
    # Uncomment to also nuke the event log:
    # "events",
]

# Collections that are reset (not fully deleted) after the wipe.
RESET_DOCS = [
    ("config", "market_state"),   # force a fresh market restock
]

# Collections we deliberately KEEP across seasons.
KEEP_COLLECTIONS = [
    "config",   # testing_mode, testing_backup
]


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # =================================================================
    # PERMISSION CHECK
    # =================================================================
    def _is_hollow(self, user) -> bool:
        try:
            if user.id in HOLLOW_USER_IDS:
                return True
            name = getattr(user, "name", "") or ""
            if name.lower() in HOLLOW_USERNAMES:
                return True
            disp = getattr(user, "display_name", "") or ""
            if disp.lower() in HOLLOW_USERNAMES:
                return True
        except Exception:
            pass
        return False

    # =================================================================
    # SYNC COMMANDS (existing)
    # =================================================================
    @commands.hybrid_command(name="sync", with_app_command=True)
    @commands.is_owner()
    @app_commands.describe(
        scope="Where to sync commands: global, current_guild, or copy_global_to_guild",
        guild_id="Optional guild id (used for current_guild/copy_global_to_guild)"
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="global", value="global"),
        app_commands.Choice(name="current_guild", value="current_guild"),
        app_commands.Choice(name="copy_global_to_guild", value="copy_global_to_guild"),
    ])
    async def sync_commands(self, ctx, scope: str = "global", guild_id: int = None):
        """Owner-only command to sync slash commands."""
        scope = (scope or "global").lower().strip()

        async def _send(message: str, **kwargs):
            if isinstance(ctx, discord.Interaction):
                try:
                    if not ctx.response.is_done():
                        await ctx.response.send_message(message, **kwargs)
                    else:
                        await ctx.followup.send(message, **kwargs)
                except Exception:
                    try:
                        await ctx.followup.send(message, **kwargs)
                    except Exception:
                        pass
            else:
                await ctx.send(message, **kwargs)

        if scope not in {"global", "current_guild", "copy_global_to_guild"}:
            await _send("❌ Invalid scope. Use one of: `global`, `current_guild`, `copy_global_to_guild`.")
            return

        target_guild = None
        if scope != "global":
            if guild_id is not None:
                target_guild = discord.Object(id=guild_id)
            elif getattr(ctx, "guild", None) is not None:
                target_guild = ctx.guild
            else:
                await _send("❌ No guild context found. Provide a `guild_id`.")
                return

        try:
            if scope == "global":
                synced = await self.bot.tree.sync()
                await _send(f"✅ Synced {len(synced)} global slash commands.")
                return

            if scope == "copy_global_to_guild":
                self.bot.tree.copy_global_to(target_guild)

            synced = await self.bot.tree.sync(guild=target_guild)
            await _send(f"✅ Synced {len(synced)} slash commands to guild `{target_guild.id}` (scope: `{scope}`).")
        except Exception as e:
            await _send(f"❌ Sync failed: {e}")

    # =================================================================
    # EXPORT DB (existing)
    # =================================================================
    @commands.hybrid_command(name="exportdb")
    async def export_database(self, ctx):
        """Export the current database file (.db) with instructions."""
        try:
            db_path = self.bot.db.db_path
            if not os.path.exists(db_path):
                await ctx.send("❌ Database file not found.")
                return

            with open(db_path, 'rb') as f:
                file_data = f.read()

            file_size_mb = len(file_data) / (1024 * 1024)
            if file_size_mb > 8:
                await ctx.send(f"⚠️ Database file is **{file_size_mb:.1f} MB** – larger than Discord's 8MB limit.")
                return

            file = discord.File(io.BytesIO(file_data), filename="warbot.db")
            embed = discord.Embed(
                title="📦 Database Export",
                description="Here is the current database file.",
                color=discord.Color.green()
            )
            embed.add_field(name="File Size", value=f"{file_size_mb:.2f} MB", inline=True)
            embed.add_field(name="Created", value=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
            await ctx.send(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error exporting database: {e}")
            await ctx.send(f"❌ Error exporting database: {e}")

    # =================================================================
    # ALLIANCE CHECK (existing)
    # =================================================================
    @commands.command(name='alliancecheck')
    @commands.is_owner()
    async def alliance_check(self, ctx, user1: discord.Member = None, user2: discord.Member = None):
        if not user1 or not user2:
            await ctx.send("Usage: `.alliancecheck @user1 @user2`")
            return
        try:
            matches = self.bot.db.find_alliances_containing_both(str(user1.id), str(user2.id))
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")
            return
        if not matches:
            await ctx.send(f"❌ No shared alliance between {user1.mention} and {user2.mention}.")
            return
        lines = [f"• **{m['name']}** (`{m['id']}`) — {len(m.get('members', []))} members" for m in matches]
        await ctx.send("✅ Shared alliances:\n" + "\n".join(lines))

    # =================================================================
    # REINSTALL — FULL SEASON RESET
    # =================================================================
    @commands.hybrid_command(name="reinstall", with_app_command=True)
    async def reinstall(self, ctx):
        """FULL SEASON RESET — wipes every civilization and every Firestore doc.

        Restricted to hollow_x2. Irreversible. Run .exportdb first if you want a backup.
        """
        user = ctx.user if isinstance(ctx, discord.Interaction) else ctx.author

        # --- Permission gate ---
        if not self._is_hollow(user):
            msg = "❌ This command is restricted."
            if isinstance(ctx, discord.Interaction):
                try:
                    await ctx.response.send_message(msg, ephemeral=True)
                except Exception:
                    await ctx.followup.send(msg, ephemeral=True)
            else:
                await ctx.send(msg)
            return

        # --- Count what's about to be wiped ---
        counts = {}
        total = 0
        for col in WIPE_COLLECTIONS:
            try:
                n = sum(1 for _ in self.bot.db.client.collection(col).stream())
                counts[col] = n
                total += n
            except Exception as e:
                logger.error(f"Count failed for {col}: {e}")
                counts[col] = "?"

        # --- Preview embed ---
        preview = discord.Embed(
            title="💥 FULL SEASON RESET — PREVIEW",
            description=(
                "**⚠️ THIS WILL WIPE EVERY CIVILIZATION AND RESET THE ENTIRE WORLD ⚠️**\n\n"
                f"**Total documents to delete:** `{total}`\n"
                f"**Collections affected:** `{len(WIPE_COLLECTIONS)}`\n\n"
                "**Every player's progress will be erased:**\n"
                "• All civilizations and resources\n"
                "• All territories and land claims\n"
                "• All wars, peace offers, alliances\n"
                "• All corporations, divisions, generals\n"
                "• All messages, proposals, and history\n"
                "• The market will restock fresh\n\n"
                "**This cannot be undone.**"
            ),
            color=0xff0000,
        )

        # Split counts into 2 fields to stay under embed limits
        count_lines_a = []
        count_lines_b = []
        for i, (col, n) in enumerate(counts.items()):
            line = f"`{col}`: **{n}**"
            (count_lines_a if i < len(counts) // 2 else count_lines_b).append(line)

        preview.add_field(name="Documents by Collection (1/2)",
                          value="\n".join(count_lines_a) or "—", inline=True)
        if count_lines_b:
            preview.add_field(name="Documents by Collection (2/2)",
                              value="\n".join(count_lines_b), inline=True)

        preview.add_field(
            name="🛑 To proceed",
            value="Type `NEW SEASON` (exactly, with a space) in this channel within 60 seconds.",
            inline=False,
        )
        preview.set_footer(text="Run .exportdb first if you want a backup before wiping")
        await ctx.send(embed=preview)

        # --- Confirmation ---
        channel_id = ctx.channel.id if not isinstance(ctx, discord.Interaction) else ctx.channel_id

        def check(m: discord.Message):
            return (
                m.author.id == user.id
                and m.channel.id == channel_id
                and m.content.strip() == "NEW SEASON"
            )

        try:
            await self.bot.wait_for("message", timeout=60.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send("🛑 Season reset cancelled (timeout). The world is safe.")
            return

        # --- Execute wipe ---
        status = await ctx.send("🌍 **Wiping the world...** this may take a minute.")

        try:
            report = await self._wipe_all_collections()

            # Reset market state so next .market call creates a fresh one
            for col, doc_id in RESET_DOCS:
                try:
                    self.bot.db.client.collection(col).document(doc_id).delete()
                except Exception as e:
                    logger.debug(f"Reset doc failed {col}/{doc_id}: {e}")

            # Clear all in-memory caches
            self._clear_all_caches()

            # --- Success embed ---
            embed = discord.Embed(
                title="✅ NEW SEASON — WORLD RESET COMPLETE",
                description=(
                    f"**{report['total']}** documents deleted across "
                    f"**{len(report['wiped'])}** collections.\n\n"
                    "The world is empty. Everyone can `.start <name>` to begin again."
                ),
                color=0x00ff00,
            )

            # Per-collection report
            lines = [f"`{col}`: **{n}**" for col, n in report["wiped"].items()]
            # Split into chunks of 15 to stay under field limit
            for i in range(0, len(lines), 15):
                chunk = lines[i:i + 15]
                embed.add_field(
                    name=f"Wiped ({i + 1}-{i + len(chunk)})",
                    value="\n".join(chunk),
                    inline=True,
                )

            if report["failures"]:
                embed.add_field(
                    name="⚠️ Failures",
                    value="\n".join(report["failures"][:5]),
                    inline=False,
                )

            embed.set_footer(text="Use .sync if new slash commands were added this season")
            await status.edit(content=None, embed=embed)
            logger.warning(f"SEASON RESET by {user.id} ({user.name}) — {report['total']} docs wiped")

        except Exception as e:
            logger.exception("Season reset failed")
            await status.edit(content=f"❌ Season reset failed: `{e}`")

    # -----------------------------------------------------------------
    # INTERNAL — wipe all collections with subcollection handling
    # -----------------------------------------------------------------
    async def _wipe_all_collections(self) -> dict:
        """Delete everything in WIPE_COLLECTIONS. Returns a report dict."""
        db = self.bot.db
        wiped = {}
        failures = []
        total = 0

        for col in WIPE_COLLECTIONS:
            count = 0
            try:
                coll = db.client.collection(col)

                # We need to handle two cases:
                # 1. Normal docs (delete directly)
                # 2. Docs with subcollections (delete subs first, then parent)
                #
                # Firestore best practice: iterate docs, walk subcollections,
                # batch the deletes.
                batch = db.client.batch()
                batch_size = 0

                for doc in coll.stream():
                    # Walk every subcollection under this doc
                    try:
                        for sub in doc.reference.collections():
                            for sub_doc in sub.stream():
                                batch.delete(sub_doc.reference)
                                batch_size += 1
                                if batch_size >= 400:
                                    batch.commit()
                                    batch = db.client.batch()
                                    batch_size = 0
                    except Exception as e:
                        logger.debug(f"Subcollection walk failed on {col}/{doc.id}: {e}")

                    batch.delete(doc.reference)
                    batch_size += 1
                    count += 1

                    if batch_size >= 400:
                        batch.commit()
                        batch = db.client.batch()
                        batch_size = 0

                if batch_size > 0:
                    batch.commit()

                wiped[col] = count
                total += count
                logger.info(f"Wiped {count} docs from {col}")

            except Exception as e:
                logger.error(f"Wipe failed for {col}: {e}")
                failures.append(f"{col}: {e}")
                wiped[col] = f"ERROR"

        return {"wiped": wiped, "failures": failures, "total": total}

    def _clear_all_caches(self):
        """Clear in-memory caches across all cogs after a full wipe."""
        # Civilization cache
        try:
            self.bot.civ_manager._civ_cache.clear()
        except Exception:
            pass

        # Basic AI chat caches
        try:
            basic = self.bot.get_cog("BasicCommands")
            if basic:
                basic.saved_chats.clear()
                basic.conversations.clear()
                basic.last_interaction.clear()
        except Exception:
            pass

        # Military blockades & bankraid history
        try:
            mil = self.bot.get_cog("MilitaryCommands")
            if mil:
                mil.blockades.clear()
                mil.cooldowns.clear()
                if hasattr(mil, "_bankraid_history"):
                    mil._bankraid_history.clear()
        except Exception:
            pass

        # Industrial revolutions cache
        try:
            ind = self.bot.get_cog("IndustrialCog")
            if ind:
                ind._active_revolutions.clear()
        except Exception:
            pass

        # ExtraEconomy cooldowns
        try:
            econ = self.bot.get_cog("EconomyCog")
            if econ:
                econ.cooldowns.clear()
                econ.coding_tasks.clear()
                econ.product_last_pay.clear()
        except Exception:
            pass

        # Map cache
        try:
            map_cog = self.bot.get_cog("MapCog")
            if map_cog:
                map_cog.cache.clear()
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
