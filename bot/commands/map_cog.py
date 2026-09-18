import discord
from discord.ext import commands
import logging
import asyncio
import hashlib
import json
import os
import time
from io import BytesIO
from typing import Dict, Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import geopandas as gpd

logger = logging.getLogger(__name__)

FALLBACK_COLOR = (0.88, 0.88, 0.88, 1.0)


def _normalize_color(c) -> tuple:
    """Force any color-like value into a 4-tuple of floats."""
    try:
        if c is None:
            return FALLBACK_COLOR
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
                self.gdf["_name"] = self.gdf.apply(self._row_name, axis=1)
                logger.info(f"Loaded regions.geojson with {len(self.gdf)} rows")
            except Exception as e:
                logger.error(f"Failed to load regions.geojson: {e}")
                self.gdf = None

        self.cache: Dict[str, Dict[str, Any]] = {}

    def _row_name(self, row) -> str:
        for k in ("NAME", "ADMIN", "NAME_LONG", "name"):
            if k in row and row[k] is not None:
                return str(row[k])
        return "Unknown"

    def _get_cached(self, key: str, ttl: float) -> Optional[BytesIO]:
        entry = self.cache.get(key)
        if entry and (time.time() - entry["ts"]) < ttl:
            buf = entry["buf"]
            buf.seek(0)
            return BytesIO(buf.getvalue())
        return None

    def _store_cache(self, key: str, buf: BytesIO):
        buf.seek(0)
        self.cache[key] = {"buf": BytesIO(buf.getvalue()), "ts": time.time()}
        if len(self.cache) > 5:
            oldest = min(self.cache.items(), key=lambda kv: kv[1]["ts"])[0]
            self.cache.pop(oldest, None)

    def _ownership_snapshot(self) -> Dict[str, Dict[str, Any]]:
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

    def _render(self, ownership: Dict[str, Dict[str, Any]]) -> BytesIO:
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

        # ---- Assign a color per owner (normalized) ----
        raw_colors = plt.cm.tab20.colors
        user_colors: Dict[str, tuple] = {}
        for i, (map_id, info) in enumerate(ownership.items()):
            user_colors[map_id] = _normalize_color(raw_colors[i % len(raw_colors)])

        # ---- province -> owner lookup ----
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

        def row_color(row) -> tuple:
            owner = resolve_owner(row.get("_name"))
            if not owner:
                return FALLBACK_COLOR
            return user_colors.get(owner, FALLBACK_COLOR)

        # ---- Build a guaranteed-uniform color array ----
        color_array = [_normalize_color(row_color(row)) for _, row in self.gdf.iterrows()]

        # ---- Plot ----
        fig, ax = plt.subplots(figsize=(15, 10))
        try:
            self.gdf.plot(ax=ax, color=color_array, edgecolor="white", linewidth=0.4)
        except ValueError as ve:
            logger.error(f"Color array plot failed ({ve}); falling back to uniform fill.")
            self.gdf.plot(ax=ax, color=FALLBACK_COLOR, edgecolor="white", linewidth=0.4)

        # ---- Legend ----
        patches = []
        for map_id, color in user_colors.items():
            try:
                patches.append(mpatches.Patch(color=color, label=ownership[map_id]["name"]))
            except Exception:
                continue
        if patches:
            ax.legend(handles=patches, loc="lower left", fontsize=8)

        ax.set_title("World Map of Civilizations", fontsize=14)
        ax.set_axis_off()

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    @commands.command(name="map")
    async def show_map(self, ctx):
        if self.gdf is None:
            await ctx.send("❌ Map data is not available. Please run `generate_geojson.py`.")
            return

        ownership = self._ownership_snapshot()
        key = "world:" + hashlib.md5(json.dumps(ownership, sort_keys=True).encode()).hexdigest()

        buf = self._get_cached(key, 300)
        if buf is None:
            async with ctx.typing():
                buf = await asyncio.to_thread(self._render, ownership)
            self._store_cache(key, buf)

        file = discord.File(buf, filename="world_map.png")
        await ctx.send("🗺️ Here's the current world map:", file=file)


async def setup(bot):
    await bot.add_cog(MapCog(bot))
