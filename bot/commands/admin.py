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
# REINSTALL — restricted to hollow_x2
# =================================================================
# Hardcoded owner ID. Only this user can run .reinstall.
HOLLOW_USER_IDS = {
    1221063035842727998,
}
# Optional name fallback (lowercase). Kept for convenience — the ID
# check runs first and is authoritative.
HOLLOW_USERNAMES = {"hollow_x2"}


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # =================================================================
    # PERMISSION CHECK
    # =================================================================
    def _is_hollow(self, user) -> bool:
        """True if the user is the reinstall owner (by ID or fallback name)."""
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
                self.bot.tree.copy_global_to(guild=target_guild)

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
                await ctx.send(f"⚠️ Database file is **{file_size_mb:.1f} MB** – larger than Discord's 8MB limit. Please use a different method to retrieve it.")
                return

            file = discord.File(io.BytesIO(file_data), filename="warbot.db")
            embed = discord.Embed(
                title="📦 Database Export",
                description=(
                    "Here is the current database file.\n\n"
                    "**To restore:**\n"
                    "1. Stop the bot.\n"
                    "2. Replace the existing `warbot.db` with this file.\n"
                    "3. Restart the bot.\n\n"
                    "**To inspect:**\n"
                    "Open with any SQLite browser (e.g., DB Browser for SQLite)."
                ),
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
        """Owner diagnostic: check if two users share an alliance."""
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
    # REINSTALL — personal full reset, restricted to hollow_x2
    # =================================================================
    @commands.hybrid_command(name="reinstall", with_app_command=True)
    async def reinstall(self, ctx):
        """Full personal reset. Restricted to hollow_x2. Irreversible."""
        user = ctx.user if isinstance(ctx, discord.Interaction) else ctx.author
        user_id = str(user.id)

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

        # --- Preview / confirmation ---
        civ = self.bot.db.get_civilization(user_id)
        if not civ:
            await ctx.send("❌ You don't have a civilization to reinstall.")
            return

        preview = discord.Embed(
            title="💥 FULL REINSTALL — CONFIRMATION",
            description=(
                f"**Reinstalling `{civ.get('name', 'Unknown')}`**\n\n"
                "This will **permanently delete**:\n"
                "• Your civilization and all resources\n"
                "• All your provinces and land\n"
                "• Your military, navy, airforce\n"
                "• All your corporations, divisions, generals\n"
                "• Your bank account, deposits, credit score\n"
                "• Your daily streak and workforce\n"
                "• Every other doc tied to your user\n\n"
                "**This cannot be undone.**"
            ),
            color=0xff0000,
        )
        preview.add_field(
            name="To confirm",
            value="Type `REINSTALL` (exactly, all caps) in this channel within 60 seconds.",
            inline=False,
        )
        preview.set_footer(text="Use .reset if you just want the standard reset")
        await ctx.send(embed=preview)

        channel_id = ctx.channel.id if not isinstance(ctx, discord.Interaction) else ctx.channel_id

        def check(m: discord.Message):
            return (
                m.author.id == user.id
                and m.channel.id == channel_id
                and m.content.strip() == "REINSTALL"
            )

        try:
            await self.bot.wait_for("message", timeout=60.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send("🛑 Reinstall cancelled (timeout). Your civilization is safe.")
            return

        # --- Execute wipe ---
        status = await ctx.send("🗑️ **Reinstalling...** this may take a few seconds.")

        try:
            deleted = await self._full_wipe_user(user_id)

            # Clear caches on other cogs
            try:
                basic = self.bot.get_cog("BasicCommands")
                if basic:
                    basic.saved_chats.discard(user_id)
                    basic.conversations.pop(user_id, None)
                    basic.last_interaction.pop(user_id, None)
            except Exception:
                pass
            try:
                self.bot.civ_manager._invalidate_civ(user_id)
            except Exception:
                pass

            embed = discord.Embed(
                title="✅ Reinstall Complete",
                description=(
                    f"**{civ.get('name', 'Unknown')}** has been completely wiped.\n\n"
                    f"**Documents deleted:** `{deleted}`\n\n"
                    "Create a new civilization with `.start <name>`."
                ),
                color=0x00ff00,
            )
            await status.edit(content=None, embed=embed)
            logger.info(f"User {user_id} ran .reinstall — {deleted} docs wiped")

        except Exception as e:
            logger.exception("Reinstall failed")
            await status.edit(content=f"❌ Reinstall failed: `{e}`")

    # -----------------------------------------------------------------
    # INTERNAL — wipe everything tied to a user
    # -----------------------------------------------------------------
    async def _full_wipe_user(self, user_id: str) -> int:
        """Delete everything tied to one user. Returns doc count."""
        db = self.bot.db
        deleted = 0

        # 1. Delete subcollections under civilizations/{user_id}
        civ_ref = db.client.collection("civilizations").document(user_id)
        try:
            for sub in civ_ref.collections():
                for doc in sub.stream():
                    doc.reference.delete()
                    deleted += 1
        except Exception as e:
            logger.debug(f"Subcollection wipe failed for {user_id}: {e}")

        # 2. Delete their territories
        try:
            for t_doc in db.client.collection("territories").stream():
                if t_doc.to_dict().get("owner_id") == user_id:
                    t_doc.reference.delete()
                    deleted += 1
        except Exception as e:
            logger.debug(f"Territory wipe failed: {e}")

        # 3. Delete solo docs where the doc id IS the user id
        solo_collections = [
            "navy", "airforce", "military_tech", "training",
            "borders", "dailies", "industrial_revolutions",
        ]
        for col in solo_collections:
            try:
                db.client.collection(col).document(user_id).delete()
                deleted += 1
            except Exception:
                pass

        # 4. Delete owned docs by field
        field_collections = [
            ("corporations", "owner_id"),
            ("divisions", "owner_id"),
            ("generals", "owner_id"),
            ("pending_attacks", "attacker_id"),
            ("pending_attacks", "defender_id"),
            ("messages", "sender_id"),
            ("messages", "recipient_id"),
            ("alliance_proposals", "proposer_id"),
            ("alliance_proposals", "target_id"),
            ("trade_proposals", "proposer_id"),
            ("trade_proposals", "target_id"),
            ("peace_offers", "offerer_id"),
            ("peace_offers", "receiver_id"),
            ("wars", "attacker_id"),
            ("wars", "defender_id"),
            ("territory_history", "user_id"),
        ]
        for col, field in field_collections:
            try:
                for doc in db.client.collection(col).where(field, "==", user_id).stream():
                    doc.reference.delete()
                    deleted += 1
            except Exception as e:
                logger.debug(f"Field wipe failed {col}.{field}: {e}")

        # 5. Remove from alliances (keep the alliance itself)
        if firestore is not None:
            try:
                for a_doc in db.client.collection("alliances") \
                                  .where("members", "array_contains", user_id).stream():
                    a_doc.reference.update({
                        "members": firestore.ArrayRemove([user_id]),
                        "join_requests": firestore.ArrayRemove([user_id]),
                    })
                    deleted += 1
            except Exception as e:
                logger.debug(f"Alliance clean failed: {e}")

        # 6. Delete the civ doc itself LAST
        try:
            civ_ref.delete()
            deleted += 1
        except Exception as e:
            logger.error(f"Civ doc delete failed for {user_id}: {e}")

        return deleted


async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
