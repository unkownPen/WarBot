import discord
from discord.ext import commands
from discord import app_commands
from io import BytesIO
import json
import os
import hashlib
import logging
import asyncio
import time
from typing import Optional, Dict, List, Any

# Headless matplotlib backend
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import geopandas as gpd

from bot import config

logger = logging.getLogger(__name__)

# Try to import subregion / province metadata; tolerate if missing
try:
    from bot.commands.territory import (
        PROVINCES,
        PROVINCE_TO_SUBREGION,
        PROVINCE_AREAS,
        ALL_SUBREGIONS,
    )
except Exception:
    PROVINCES = {}
    PROVINCE_TO_SUBREGION = {}
    PROVINCE_AREAS = {}
    ALL_SUBREGIONS = []


# Symbol glyph per division role branch
ROLE_BRANCH_SYMBOLS = {
    "infantry":   "o",
    "armor":      "s",
    "artillery":  "P",
    "airborne":   "^",
    "mechanized": "D",
}

# Fallback colors used everywhere — plain 4-tuples of floats
FALLBACK_COLOR = (0.88, 0.88, 0.88, 1.0)
ATTACKER_COLOR = (0.15, 0.35, 0.85, 1.0)
DEFENDER_COLOR = (0.85, 0.15, 0.15, 1.0)
MARKER_BLUE = "#1e40af"
MARKER_RED = "#b91c1c"


def _normalize_color(c) -> tuple:
    """Force any color-like input into a 4-tuple of floats."""
    try:
        if c is None:
            return FALLBACK_COLOR
        # numpy array / list / tuple
        if hasattr(c, "__len__") and len(c) >= 3:
            r = float(c[0]); g = float(c[1]); b = float(c[2])
            a = float(c[3]) if len(c) >= 4 else 1.0
            return (r, g, b, a)
    except Exception:
        pass
    return FALLBACK_COLOR


class MapCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.civ_manager = bot.civ_manager

        # ---- Load geojson once ----
        self.geojson_path = "regions.geojson"
        self.gdf = None
        if not os.path.exists(self.geojson_path):
            logger.error("regions.geojson not found. Map will not work.")
        else:
            try:
                self.gdf = gpd.read_file(self.geojson_path)
                if self.gdf.crs is None:
                    self.gdf = self.gdf.set_crs("EPSG:4326", allow_override=True)
                elif str(self.gdf.crs) != "EPSG:4326":
                    self.gdf = self.gdf.to_crs("EPSG:4326")
                self.gdf["geometry"] = self.gdf["geometry"].buffer(0)
                # Normalize name column
                self.gdf["_name"] = self.gdf.apply(self._row_name, axis=1)
                # Precompute centroids (needed for labels + markers)
                self.gdf["_centroid"] = self.gdf["geometry"].centroid
                logger.info(f"Loaded regions.geojson with {len(self.gdf)} rows")
            except Exception as e:
                logger.error(f"Failed to load regions.geojson: {e}")
                self.gdf = None

        # ---- Image cache ----
        self.cache: Dict[str, Dict[str, Any]] = {}

    # =================================================================
    # HELPERS
    # =================================================================
    def _row_name(self, row) -> str:
        for k in ("NAME", "ADMIN", "NAME_LONG", "name"):
            if k in row and row[k] is not None:
                return str(row[k])
        return "Unknown"

    def _is_fresh(self, entry, ttl: float) -> bool:
        return entry and (time.time() - entry["ts"]) < ttl

    def _get_cached(self, key: str, ttl: float):
        entry = self.cache.get(key)
        if self._is_fresh(entry, ttl):
            buf = entry["buf"]
            buf.seek(0)
            return BytesIO(buf.getvalue())
        return None

    def _store_cache(self, key: str, buf: BytesIO):
        buf.seek(0)
        self.cache[key] = {"buf": BytesIO(buf.getvalue()), "ts": time.time()}
        if len(self.cache) > 15:
            oldest = min(self.cache.items(), key=lambda kv: kv[1]["ts"])[0]
            self.cache.pop(oldest, None)

    def _ownership_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Return {map_id: {"provinces": [...], "name": "..."}} merging union members."""
        if self.gdf is None:
            return {}
        territories = self.db.get_all_territories()
        ownership: Dict[str, Dict[str, Any]] = {}
        for province_name, data in territories.items():
            owner_id = data.get("owner_id")
            if not owner_id:
                continue
            civ = self.civ_manager.get_civilization(owner_id)
            union = (civ or {}).get("union")
            if union and union.get("members"):
                members = sorted(str(m) for m in union.get("members", []))
                map_id = "union:" + ":".join(members)
                name = union.get("name") or (civ["name"] if civ else owner_id[:6])
            else:
                map_id = str(owner_id)
                name = civ["name"] if civ else owner_id[:6]
            ownership.setdefault(map_id, {"provinces": [], "name": name})
            ownership[map_id]["provinces"].append(province_name)
        return ownership

    def _division_snapshot(self, owner_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Return {province_name: [division_docs...]}."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        try:
            stream = self.db.client.collection("divisions").stream()
            for doc in stream:
                data = doc.to_dict()
                if owner_id and str(data.get("owner_id")) != str(owner_id):
                    continue
                loc = data.get("location")
                if not loc:
                    continue
                data["id"] = doc.id
                grouped.setdefault(loc, []).append(data)
        except Exception as e:
            logger.error(f"_division_snapshot error: {e}")
        return grouped

    def _subregion_bounds(self, subregion: str):
        if self.gdf is None or subregion not in PROVINCES:
            return None
        countries = set(PROVINCES.get(subregion, []))
        filtered = self.gdf[self.gdf["_name"].isin(countries)]
        if filtered.empty:
            return None
        return filtered.total_bounds

    def _player_bounds(self, ownership: Dict[str, Dict[str, Any]], user_ids: List[str]):
        if self.gdf is None:
            return None
        provinces = set()
        for uid in user_ids:
            info = ownership.get(str(uid))
            if info:
                provinces.update(info["provinces"])
        if not provinces:
            return None
        filtered = self.gdf[self.gdf["_name"].isin(provinces)]
        if filtered.empty:
            return None
        return filtered.total_bounds

    def _apply_padding(self, bounds, padding: float):
        minx, miny, maxx, maxy = bounds
        dx = (maxx - minx) * padding
        dy = (maxy - miny) * padding
        return (minx - dx, miny - dy, maxx + dx, maxy + dy)

    # =================================================================
    # CORE RENDER
    # =================================================================
    def _render(
        self,
        ownership: Dict[str, Dict[str, Any]],
        divisions: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        bounds=None,
        view_mode: str = "world",
        attacker_id: Optional[str] = None,
        defender_id: Optional[str] = None,
        division_color_owner: Optional[str] = None,
    ) -> BytesIO:
        """Synchronous render. Caller must wrap in asyncio.to_thread."""
        if self.gdf is None:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.text(0.5, 0.5, "Map data not available",
                    ha="center", va="center", fontsize=14)
            ax.set_axis_off()
            buf = BytesIO()
            plt.savefig(buf, format="png", dpi=100, bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            return buf

        padding = config.MAP_RENDER["padding"]
        font_sizes = config.MAP_RENDER["font_size"]
        label_min_area = config.MAP_RENDER["label_min_area"]
        label_max_count = config.MAP_RENDER["label_max_count"]
        marker_size = config.MAP_RENDER["marker_size"]
        marker_alpha = config.MAP_RENDER["marker_alpha"]

        # ---- Build color map for owners ----
        # Normalize every color to a plain 4-tuple of floats. Mixing numpy
        # arrays and tuples in the same list crashes matplotlib's array
        # conversion ("inhomogeneous shape").
        raw_colors = plt.cm.tab20.colors
        user_colors: Dict[str, tuple] = {}
        for i, (map_id, info) in enumerate(ownership.items()):
            user_colors[map_id] = _normalize_color(raw_colors[i % len(raw_colors)])

        # ---- Build province -> owner lookup ----
        province_owner: Dict[str, str] = {}
        for map_id, info in ownership.items():
            for province in info.get("provinces", []) or []:
                province_owner[province.lower()] = map_id

        def resolve_owner(name: str) -> Optional[str]:
            if not name:
                return None
            low = name.lower()
            direct = province_owner.get(low)
            if direct:
                return direct
            for pname, mid in province_owner.items():
                if pname in low or low in pname:
                    return mid
            return None

        # ---- Color resolver for every polygon — always returns 4-tuple floats ----
        def row_color(row) -> tuple:
            name = row.get("_name")
            owner = resolve_owner(name)
            if not owner:
                return FALLBACK_COLOR
            if view_mode == "warfront" and attacker_id is not None and defender_id is not None:
                if owner == str(attacker_id):
                    return ATTACKER_COLOR
                if owner == str(defender_id):
                    return DEFENDER_COLOR
            return user_colors.get(owner, FALLBACK_COLOR)

        # Build the color array, and sanity-normalize every entry.
        color_array: List[tuple] = []
        for _, row in self.gdf.iterrows():
            color_array.append(_normalize_color(row_color(row)))

        # ---- Figure ----
        fig, ax = plt.subplots(figsize=(15, 10))
        try:
            self.gdf.plot(ax=ax, color=color_array, edgecolor="white", linewidth=0.4)
        except ValueError as ve:
            # Last-resort fallback if the array still trips up — plot uniform grey
            logger.error(f"Color array plot failed ({ve}); falling back to uniform fill.")
            self.gdf.plot(ax=ax, color=FALLBACK_COLOR, edgecolor="white", linewidth=0.4)

        # ---- Apply zoom ----
        if bounds is not None:
            padded = self._apply_padding(bounds, padding)
            ax.set_xlim(padded[0], padded[2])
            ax.set_ylim(padded[1], padded[3])

        # ---- Labels (country names) ----
        label_candidates = []
        for _, row in self.gdf.iterrows():
            name = row.get("_name")
            if not name:
                continue
            area = PROVINCE_AREAS.get(name, 0)
            if area < label_min_area:
                continue
            owner = resolve_owner(name)
            if owner is None:
                continue
            cx, cy = row["_centroid"].x, row["_centroid"].y
            label_candidates.append((area, name, owner, cx, cy))

        label_candidates.sort(key=lambda t: t[0], reverse=True)
        label_candidates = label_candidates[:label_max_count]

        font_size = font_sizes.get(view_mode, 8)
        for area, name, owner, cx, cy in label_candidates:
            owner_name = ownership.get(owner, {}).get("name", "")
            label_text = name if view_mode != "warfront" else f"{name}\n{owner_name}"
            ax.text(
                cx, cy, label_text,
                fontsize=font_size, ha="center", va="center",
                color="black", weight="bold",
                bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1.5),
                zorder=5,
            )

        # ---- Division markers ----
        if divisions:
            marker_color = MARKER_BLUE
            if view_mode == "warfront" and defender_id is not None:
                # If the caller is showing defender divisions
                if division_color_owner and str(division_color_owner) == str(defender_id):
                    marker_color = MARKER_RED
            elif division_color_owner and str(division_color_owner) != str(attacker_id or ""):
                marker_color = MARKER_RED

            for province, div_list in divisions.items():
                if not div_list:
                    continue
                row = self.gdf[self.gdf["_name"] == province]
                if row.empty:
                    row = self.gdf[self.gdf["_name"].str.lower() == province.lower()]
                if row.empty:
                    continue
                centroid = row.iloc[0]["_centroid"]
                cx, cy = centroid.x, centroid.y

                marker_y = cy - 0.6

                type_counts: Dict[str, int] = {}
                for d in div_list:
                    role_key = d.get("type", "line_infantry")
                    role = config.DIVISION_ROLES.get(role_key, {})
                    branch = role.get("branch", "infantry")
                    type_counts[branch] = type_counts.get(branch, 0) + 1

                x_offset = 0
                for branch, count in type_counts.items():
                    symbol = ROLE_BRANCH_SYMBOLS.get(branch, "o")
                    try:
                        ax.scatter(
                            cx + x_offset, marker_y,
                            marker=symbol, s=marker_size,
                            c=marker_color, alpha=marker_alpha,
                            edgecolors="black", linewidths=0.8,
                            zorder=6,
                        )
                    except Exception:
                        # If marker glyph unsupported, use a plain circle
                        ax.scatter(
                            cx + x_offset, marker_y,
                            marker="o", s=marker_size,
                            c=marker_color, alpha=marker_alpha,
                            edgecolors="black", linewidths=0.8,
                            zorder=6,
                        )
                    if count > 1:
                        ax.text(
                            cx + x_offset, marker_y - 0.4,
                            f"×{count}", fontsize=6, ha="center", va="top",
                            color="black", weight="bold",
                            bbox=dict(facecolor="white", alpha=0.6, edgecolor="none", pad=0.5),
                            zorder=7,
                        )
                    x_offset += 0.9

        # ---- Title ----
        titles = {
            "world": "World Map of Civilizations",
            "region": "Regional Map",
            "warfront": "Warfront",
            "divisionmap": "Divisions of the World",
        }
        ax.set_title(titles.get(view_mode, "Map"), fontsize=14)
        ax.set_axis_off()

        # ---- Save ----
        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    # =================================================================
    # ASYNC RENDER WRAPPER
    # =================================================================
    async def _render_async(self, *args, **kwargs) -> BytesIO:
        return await asyncio.to_thread(self._render, *args, **kwargs)

    # =================================================================
    # COMMANDS
    # =================================================================
    @commands.command(name="map")
    @app_commands.describe(subregion="Optional subregion to zoom into (e.g. 'Western Europe')")
    async def show_map(self, ctx, *, subregion: str = None):
        if self.gdf is None:
            await ctx.send("❌ Map data is not available. Please run `generate_geojson.py`.")
            return

        ownership = self._ownership_snapshot()

        if subregion is None:
            key = "world:" + hashlib.md5(
                json.dumps(ownership, sort_keys=True).encode()
            ).hexdigest()
            buf = self._get_cached(key, config.MAP_RENDER["cache_ttl"]["world"])
            if buf is None:
                async with ctx.typing():
                    buf = await self._render_async(
                        ownership, divisions=None, bounds=None, view_mode="world"
                    )
                self._store_cache(key, buf)
            file = discord.File(buf, filename="world_map.png")
            await ctx.send("🗺️ Here's the current world map:", file=file)
            return

        # ---- Subregion view ----
        matched = None
        for sub in ALL_SUBREGIONS:
            if sub.lower() == subregion.strip().lower():
                matched = sub
                break
        if matched is None:
            for sub in ALL_SUBREGIONS:
                if subregion.strip().lower() in sub.lower():
                    matched = sub
                    break
        if matched is None:
            await ctx.send(f"❌ Unknown subregion `{subregion}`. Try `.map` for the world.")
            return

        bounds = self._subregion_bounds(matched)
        if bounds is None:
            await ctx.send(f"❌ No data for subregion **{matched}**.")
            return

        key = f"region:{matched}:" + hashlib.md5(
            json.dumps(ownership, sort_keys=True).encode()
        ).hexdigest()
        buf = self._get_cached(key, config.MAP_RENDER["cache_ttl"]["region"])
        if buf is None:
            async with ctx.typing():
                buf = await self._render_async(
                    ownership, divisions=None, bounds=bounds, view_mode="region"
                )
            self._store_cache(key, buf)
        file = discord.File(buf, filename=f"map_{matched.replace(' ', '_')}.png")
        await ctx.send(f"🗺️ **{matched}** — regional map:", file=file)

    @commands.command(name="divisionmap")
    @app_commands.describe(target="Optional: show another user's divisions")
    async def division_map(self, ctx, target: discord.Member = None):
        if self.gdf is None:
            await ctx.send("❌ Map data is not available. Please run `generate_geojson.py`.")
            return

        owner_id = str(target.id) if target else str(ctx.author.id)
        owner_civ = self.civ_manager.get_civilization(owner_id)
        if not owner_civ:
            await ctx.send("❌ That user has no civilization.")
            return

        ownership = self._ownership_snapshot()
        divisions = self._division_snapshot(owner_id=owner_id)

        if not divisions:
            await ctx.send(f"📭 **{owner_civ['name']}** has no divisions on the map.")
            return

        key = f"divisionmap:{owner_id}:" + hashlib.md5(
            json.dumps({"o": ownership, "d": {k: len(v) for k, v in divisions.items()}}, sort_keys=True).encode()
        ).hexdigest()
        buf = self._get_cached(key, config.MAP_RENDER["cache_ttl"]["divisionmap"])
        if buf is None:
            async with ctx.typing():
                buf = await self._render_async(
                    ownership,
                    divisions=divisions,
                    bounds=None,
                    view_mode="divisionmap",
                    division_color_owner=owner_id,
                )
            self._store_cache(key, buf)

        file = discord.File(buf, filename="division_map.png")
        await ctx.send(f"🗺️ Divisions of **{owner_civ['name']}**:", file=file)

    @commands.command(name="warfront")
    @app_commands.describe(target="The opponent to show the warfront against")
    async def warfront(self, ctx, target: discord.Member = None):
        if self.gdf is None:
            await ctx.send("❌ Map data is not available. Please run `generate_geojson.py`.")
            return
        if target is None:
            await ctx.send("Usage: `.warfront @user`")
            return

        my_id = str(ctx.author.id)
        their_id = str(target.id)
        if my_id == their_id:
            await ctx.send("❌ Pick someone else.")
            return

        my_civ = self.civ_manager.get_civilization(my_id)
        their_civ = self.civ_manager.get_civilization(their_id)
        if not my_civ or not their_civ:
            await ctx.send("❌ Both parties need a civilization.")
            return

        ownership = self._ownership_snapshot()
        if my_id not in ownership and their_id not in ownership:
            await ctx.send("❌ Neither of you own any provinces.")
            return

        bounds = self._player_bounds(ownership, [my_id, their_id])
        if bounds is None:
            await ctx.send("❌ No owned provinces to show.")
            return

        my_div = self._division_snapshot(owner_id=my_id)
        their_div = self._division_snapshot(owner_id=their_id)
        merged_div: Dict[str, List[Dict[str, Any]]] = {}
        for src in (my_div, their_div):
            for province, lst in src.items():
                merged_div.setdefault(province, []).extend(lst)

        key = f"warfront:{my_id}:{their_id}:" + hashlib.md5(
            json.dumps({
                "o": ownership,
                "d": {k: len(v) for k, v in merged_div.items()},
            }, sort_keys=True).encode()
        ).hexdigest()
        buf = self._get_cached(key, config.MAP_RENDER["cache_ttl"]["warfront"])
        if buf is None:
            async with ctx.typing():
                buf = await self._render_async(
                    ownership,
                    divisions=merged_div,
                    bounds=bounds,
                    view_mode="warfront",
                    attacker_id=my_id,
                    defender_id=their_id,
                )
            self._store_cache(key, buf)

        file = discord.File(buf, filename="warfront.png")
        await ctx.send(
            f"⚔️ **Warfront** — {my_civ['name']} (blue) vs {their_civ['name']} (red)",
            file=file,
        )


async def setup(bot):
    await bot.add_cog(MapCog(bot))
