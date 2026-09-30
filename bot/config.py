# bot/config.py
# All game balance parameters in one place.

# ================================================================
# ECONOMY GAINS (rebalanced for workforce scaling)
# ================================================================
ECONOMY = {
    # ---- Base per-action yields (used as fallback when workforce is empty) ----
    "gather_base_min": 8, "gather_base_max": 30, "gather_chance": 0.75,
    "gather_employment_coeff": 0.4, "gather_cap": 500_000,

    "work_gold_per_citizen_min": 3, "work_gold_per_citizen_max": 8,
    "work_employment_coeff": 0.4, "work_cap": 1_000_000,

    # Base values are LOW now — workforce multipliers scale them up dramatically
    "farm_base_min": 15, "farm_base_max": 50, "farm_citizen_divisor": 20,
    "farm_employment_coeff": 0.4, "farm_cap": 200_000,

    "mine_stone_base_min": 12, "mine_stone_base_max": 40,
    "mine_wood_base_min": 8, "mine_wood_base_max": 30,
    "mine_employment_coeff": 0.4,
    "mine_stone_cap": 150_000, "mine_wood_cap": 150_000,
    "mine_bonus_gold_chance": 0.25, "mine_bonus_gold_min": 10,
    "mine_bonus_gold_max": 50, "mine_bonus_gold_cap": 25_000,

    "harvest_base_min": 60, "harvest_base_max": 180,
    "harvest_citizen_divisor": 10, "harvest_happiness_divisor": 4,
    "harvest_employment_coeff": 0.4, "harvest_cap": 500_000,

    "drill_minerals_min": 30, "drill_minerals_max": 100,
    "drill_employment_coeff": 0.4,
    "drill_gold_cap": 500_000, "drill_stone_cap": 250_000,
    "drill_bonus_gold_chance": 0.2,
    "drill_bonus_gold_min": 150, "drill_bonus_gold_max": 600,

    "fish_food_base_min": 12, "fish_food_base_max": 40,
    "fish_treasure_base_min": 30, "fish_treasure_base_max": 180,
    "fish_employment_coeff": 0.4, "fish_cap": 200_000,

    "tax_base_per_citizen": 1, "tax_employment_coeff": 0.3,
    "tax_happiness_penalty": -5, "tax_fascism_extra_penalty": -8,
    "tax_cap": 600_000, "tax_population_loss_threshold": 50,
    "tax_population_loss_chance": 0.35,
    "tax_population_loss_min": 10, "tax_population_loss_max": 30,
    # Tax rate system — new
    "tax_rates": {
        "low":    {"mult": 0.50, "happiness": -2, "label": "Low"},
        "normal": {"mult": 1.00, "happiness": -5, "label": "Normal"},
        "high":   {"mult": 1.60, "happiness": -12, "label": "High"},
        "brutal": {"mult": 2.50, "happiness": -25, "label": "Brutal"},
    },

    "raid_gold_min": 400, "raid_gold_max": 1200,
    "raid_food_min": 200, "raid_food_max": 500,
    "raid_wood_min": 100, "raid_wood_max": 300,
    "raid_stone_min": 80, "raid_stone_max": 250,
    "raid_employment_coeff": 0.6, "raid_cap": 8_000_000,
    "raid_bonus_gold_chance": 0.15,
    "raid_bonus_gold_min": 500, "raid_bonus_gold_max": 1500,
    "raid_min_soldiers": 5,

    "labor_gold_min": 400, "labor_gold_max": 1200,
    "labor_food_min": 200, "labor_food_max": 500,
    "labor_wood_min": 200, "labor_wood_max": 500,
    "labor_stone_min": 150, "labor_stone_max": 400,
    "labor_employment_coeff": 0.6, "labor_cap": 3_000_000,
    "labor_happiness_cost": -8, "labor_min_soldiers": 5,

    "advertise_citizen_min": 300, "advertise_citizen_max": 900,
    "advertise_employment_coeff": 0.6, "advertise_cap": 20_000,
    "advertise_cost": 50,
    "immigration_citizen_min": 250, "immigration_citizen_max": 700,
    "immigration_employment_coeff": 0.5, "immigration_cap": 2_500,
    "immigration_happiness_loss_min": 8, "immigration_happiness_loss_max": 18,
    "immigration_riot_chance": 0.25,
    "immigration_riot_happiness_loss_min": 6,
    "immigration_riot_happiness_loss_max": 15,
    "immigration_riot_soldier_loss_min": 2,
    "immigration_riot_soldier_loss_max": 8,

    "sell_common_min": 250, "sell_common_max": 600,
    "sell_rare_min": 700, "sell_rare_max": 1500,
    "sell_legendary_min": 1200, "sell_legendary_max": 2500,
    "sell_cap": 50_000,
}

EXPANSION = {
    "soldier_per_area_small": 595, "soldier_per_area_large": 2000,
    "min_soldier_cost": 10, "max_soldier_cost": 5000,
    "rapid_multiplier": 2,
    "rapid_min_soldier_cost": 20, "rapid_max_soldier_cost": 10000,
    "base_gold_per_province": 300, "base_food_per_province": 100,
    "base_wood_per_province": 20, "base_stone_per_province": 20,
    "resource_cost_multiplier": 0.75,
}

# ================================================================
# WORKFORCE — sector-based economy (new)
# ================================================================
WORKFORCE = {
    "sectors": {
        "farming": {
            "name": "Farming", "emoji": "🌾",
            "desc": "Food production. Feeds the nation and its armies.",
            "primary_resource": "food",
            "base_yield_per_worker": 4.0,
        },
        "mining": {
            "name": "Mining", "emoji": "⛏️",
            "desc": "Stone and wood extraction. Fuels industry.",
            "primary_resource": "stone",
            "base_yield_per_worker": 3.5,
        },
        "industry": {
            "name": "Industry", "emoji": "🏭",
            "desc": "Converts raw materials into goods and gold.",
            "primary_resource": "gold",
            "base_yield_per_worker": 3.0,
        },
        "trade": {
            "name": "Trade", "emoji": "💼",
            "desc": "Direct gold income. Amplified by coasts and cities.",
            "primary_resource": "gold",
            "base_yield_per_worker": 3.5,
        },
    },

    # Diminishing returns per sector — each tier covers a range
    "tiers": [
        {"up_to": 10,   "mult": 1.00, "label": "Full yield"},
        {"up_to": 50,   "mult": 0.70, "label": "70% yield"},
        {"up_to": 150,  "mult": 0.45, "label": "45% yield"},
        {"up_to": 500,  "mult": 0.30, "label": "30% yield"},
        {"up_to": None, "mult": 0.20, "label": "20% yield (diminishing)"},
    ],

    # Minimum citizens that can't be unassigned (government overhead)
    "min_unassigned": 5,

    # Ideology modifiers per sector
    "ideology_mods": {
        "fascism":     {"industry": 1.20, "trade": 0.85, "mining": 1.05, "farming": 1.00},
        "democracy":   {"trade": 1.15, "farming": 1.00, "industry": 1.00, "mining": 0.95},
        "communism":   {"farming": 1.15, "industry": 1.05, "trade": 0.80, "mining": 1.00},
        "theocracy":   {"farming": 1.10, "trade": 0.95, "industry": 0.95, "mining": 0.95},
        "anarchy":     {"mining": 1.15, "trade": 1.10, "farming": 0.90, "industry": 0.90},
        "destruction": {"industry": 1.35, "mining": 1.10, "farming": 0.75, "trade": 0.70},
        "pacifist":    {"farming": 1.20, "trade": 1.15, "industry": 0.85, "mining": 0.90},
        "socialism":   {"farming": 1.10, "industry": 1.10, "trade": 0.90, "mining": 1.00},
        "terrorism":   {"mining": 1.10, "industry": 1.15, "trade": 0.80, "farming": 0.80},
        "capitalism":  {"trade": 1.30, "industry": 1.05, "farming": 0.90, "mining": 0.95},
        "federalism":  {"trade": 1.10, "farming": 1.05, "industry": 1.05, "mining": 1.00},
        "monarchy":    {"farming": 1.10, "industry": 1.05, "trade": 1.00, "mining": 1.05},
    },
}

# ================================================================
# TOOLS — permanent buyable upgrades for economy commands (new)
# ================================================================
TOOLS = {
    # ---- Tier 1 (basic) ----
    "hoe": {
        "name": "Iron Hoe", "emoji": "🪓",
        "cost": 5_000,
        "boosts": {"farm": 0.15},
        "desc": "+15% farm yield",
    },
    "pickaxe": {
        "name": "Iron Pickaxe", "emoji": "⛏️",
        "cost": 8_000,
        "boosts": {"mine": 0.20},
        "desc": "+20% mine yield",
    },
    "fishing_rod": {
        "name": "Steel Fishing Rod", "emoji": "🎣",
        "cost": 12_000,
        "boosts": {"fish": 0.25},
        "desc": "+25% fish yield",
    },
    "ledger": {
        "name": "Merchant Ledger", "emoji": "📒",
        "cost": 20_000,
        "boosts": {"tax": 0.10, "market_sell": 0.10},
        "desc": "+10% tax, +10% market sell price",
    },
    "cart": {
        "name": "Ox Cart", "emoji": "🐂",
        "cost": 18_000,
        "boosts": {"gather": 0.25, "work": 0.15},
        "desc": "+25% gather, +15% work yield",
    },
    "smugglers_map": {
        "name": "Smuggler's Map", "emoji": "🗺️",
        "cost": 50_000,
        "boosts": {"smuggle": 0.20, "smuggle_detection": -0.10},
        "desc": "+20% smuggle yield, −10% detection chance",
    },

    # ---- Tier 2 (advanced, cost 50K+) ----
    "tractor": {
        "name": "Tractor", "emoji": "🚜",
        "cost": 75_000,
        "boosts": {"farm": 0.30, "harvest": 0.30},
        "desc": "+30% farm and harvest yield",
        "requires": "hoe",
    },
    "power_drill": {
        "name": "Power Drill", "emoji": "🔨",
        "cost": 85_000,
        "boosts": {"mine": 0.35, "drill": 0.25},
        "desc": "+35% mine, +25% drill yield",
        "requires": "pickaxe",
    },
    "refinery_license": {
        "name": "Refinery License", "emoji": "📜",
        "cost": 100_000,
        "boosts": {"refine": 0.20},
        "desc": "+20% refine output",
    },
    "trade_charter": {
        "name": "Trade Charter", "emoji": "🏛️",
        "cost": 120_000,
        "boosts": {"market_buy": 0.10, "market_sell": 0.15, "globaltrade": 0.20},
        "desc": "−10% market buy price, +15% market sell price",
        "requires": "ledger",
    },

    # ---- Tier 3 (endgame, cost 250K+) ----
    "titanium_pickaxe": {
        "name": "Titanium Pickaxe", "emoji": "⚒️",
        "cost": 250_000,
        "boosts": {"mine": 0.50, "drill": 0.40},
        "desc": "+50% mine, +40% drill (replaces Power Drill bonus)",
        "requires": "power_drill",
    },
    "industrial_combine": {
        "name": "Industrial Combine", "emoji": "🏗️",
        "cost": 300_000,
        "boosts": {"industry": 0.35, "refine": 0.25},
        "desc": "+35% industry, +25% refine",
    },
    "banking_network": {
        "name": "Banking Network", "emoji": "🏦",
        "cost": 400_000,
        "boosts": {"invest": 0.30, "tax": 0.20, "market_sell": 0.10},
        "desc": "+30% invest returns, +20% tax, +10% market sell",
        "requires": "trade_charter",
    },
    "grain_silo": {
        "name": "Grain Silo", "emoji": "🌾",
        "cost": 150_000,
        "boosts": {"farm": 0.20, "food_storage": 1.0},
        "desc": "+20% farm, prevents food loss during famines",
        "requires": "tractor",
    },
}

# ================================================================
# MARKET — NPC shop with 48h restock cycle (new)
# ================================================================
MARKET = {
    "restock_interval_hours": 48,
    "price_variance": 0.15,           # ±15% per restock
    "starting_prices": {
        "gold":   {"buy": 100,  "sell": 90},
        "food":   {"buy": 8,    "sell": 6},
        "wood":   {"buy": 10,   "sell": 8},
        "stone":  {"buy": 12,   "sell": 10},
        "tools":  {"buy": 500,  "sell": 450},
        "metal":  {"buy": 800,  "sell": 700},
        "luxury": {"buy": 2500, "sell": 2200},
        "rations": {"buy": 200, "sell": 170},
        "weapons": {"buy": 3000, "sell": 2700},
    },
    "stock_per_cycle": {
        "food":    50_000,
        "wood":    30_000,
        "stone":   30_000,
        "gold":    100_000,
        "tools":   500,
        "metal":   300,
        "luxury":  100,
        "rations": 200,
        "weapons": 50,
    },
    "stock_regen_per_hour": {
        "food":  500,
        "wood":  300,
        "stone": 300,
    },
    "min_buy": 100,
    "max_single_transaction": 50_000,
    "smuggle": {
        "price_mult": 1.40,
        "detection_chance": 0.30,
        "sanction_hours": 12,
        "loss_on_detect": 0.50,
        "cooldown_seconds": 1800,     # 30 min
    },
}

# ================================================================
# REFINERY — resource chains (new)
# ================================================================
REFINERY = {
    "chains": {
        "rations": {
            "name": "Rations", "emoji": "🍱",
            "inputs": {"food": 300, "gold": 50},
            "output": 1,
            "tech_required": 2,
            "desc": "Soldier food supply. Boosts military morale.",
        },
        "tools": {
            "name": "Tools", "emoji": "🔧",
            "inputs": {"wood": 500, "stone": 200},
            "output": 1,
            "tech_required": 3,
            "desc": "Craft goods. Sold high or used in weapon chains.",
        },
        "metal": {
            "name": "Metal", "emoji": "🔩",
            "inputs": {"stone": 800, "gold": 100},
            "output": 1,
            "tech_required": 4,
            "desc": "Refined ore. Needed for weapons and megaprojects.",
        },
        "weapons": {
            "name": "Weapons", "emoji": "⚔️",
            "inputs": {"metal": 1, "tools": 1},
            "output": 10,
            "tech_required": 5,
            "desc": "Equip 10 soldiers with better gear. Boost combat.",
        },
        "luxury": {
            "name": "Luxury Goods", "emoji": "💎",
            "inputs": {"wood": 200, "food": 100, "gold": 50},
            "output": 1,
            "tech_required": 6,
            "desc": "Trade goods. Sells for high prices, raises happiness.",
        },
    },
    "batch_multiplier": 1.0,           # applied to all outputs
    "happiness_per_luxury_sold": 0.5,  # selling luxury goods raises happiness
}

# ================================================================
# CLIMATE — terrain types with big positives AND big negatives (new)
# ================================================================
CLIMATE_TYPES = {
    "temperate": {
        "name": "Temperate", "emoji": "🌤️",
        "desc": "Mild climate. Industrial backbone of the world.",
        "modifiers": {"farming": 1.00, "mining": 0.80, "industry": 1.25, "trade": 1.10},
        "pros": ["+25% industry", "+10% trade"],
        "cons": ["−20% mining"],
    },
    "mediterranean": {
        "name": "Mediterranean", "emoji": "🍇",
        "desc": "Sun-drenched coasts. Wine, olives, and shipping lanes.",
        "modifiers": {"farming": 1.30, "mining": 0.65, "industry": 0.95, "trade": 1.25},
        "pros": ["+30% farming", "+25% trade"],
        "cons": ["−35% mining"],
    },
    "plains": {
        "name": "Fertile Plains", "emoji": "🌾",
        "desc": "Breadbaskets of the world. Huge farmlands, poor ore.",
        "modifiers": {"farming": 1.50, "mining": 0.70, "industry": 0.95, "trade": 0.85},
        "pros": ["+50% farming"],
        "cons": ["−30% mining", "−15% trade"],
    },
    "boreal": {
        "name": "Boreal Forest", "emoji": "🌲",
        "desc": "Cold northern woods. Timber, furs, and ore.",
        "modifiers": {"farming": 0.50, "mining": 1.20, "industry": 1.05, "trade": 0.90},
        "pros": ["+20% mining", "+5% industry"],
        "cons": ["−50% farming"],
    },
    "tundra": {
        "name": "Tundra", "emoji": "❄️",
        "desc": "Frozen ground. Miners and smelters thrive, farms die.",
        "modifiers": {"farming": 0.40, "mining": 1.30, "industry": 1.15, "trade": 0.90},
        "pros": ["+30% mining", "+15% industry"],
        "cons": ["−60% farming"],
    },
    "arctic": {
        "name": "Polar", "emoji": "🧊",
        "desc": "Ice and research stations. Nothing grows, but the drills never stop.",
        "modifiers": {"farming": 0.20, "mining": 1.30, "industry": 1.00, "trade": 0.80},
        "pros": ["+30% mining", "Unique discoveries"],
        "cons": ["−80% farming"],
    },
    "desert": {
        "name": "Desert", "emoji": "🏜️",
        "desc": "Sand and sun. Oil, gold, and salt beneath the dunes.",
        "modifiers": {"farming": 0.30, "mining": 1.60, "industry": 1.00, "trade": 1.40},
        "pros": ["+60% mining", "+40% trade (oil)"],
        "cons": ["−70% farming"],
    },
    "steppe": {
        "name": "Steppe", "emoji": "🌿",
        "desc": "Dry grassland. Grain, herds, and horses.",
        "modifiers": {"farming": 1.20, "mining": 1.25, "industry": 0.90, "trade": 0.75},
        "pros": ["+25% mining", "+20% farming"],
        "cons": ["−25% trade"],
    },
    "tropical": {
        "name": "Tropical", "emoji": "🌴",
        "desc": "Hot, wet, and lush. Crops and timber thrive.",
        "modifiers": {"farming": 1.45, "mining": 0.85, "industry": 0.65, "trade": 1.00},
        "pros": ["+45% farming", "+40% wood"],
        "cons": ["−35% industry"],
    },
    "monsoon": {
        "name": "Monsoon", "emoji": "🌧️",
        "desc": "Heavy rains. Rice paddies yield plenty.",
        "modifiers": {"farming": 1.70, "mining": 0.70, "industry": 0.85, "trade": 0.95},
        "pros": ["+70% farming"],
        "cons": ["−30% mining"],
    },
    "mountainous": {
        "name": "Mountainous", "emoji": "⛰️",
        "desc": "Rugged terrain. Rich in ore, hard to farm.",
        "modifiers": {"farming": 0.55, "mining": 1.55, "industry": 1.00, "trade": 0.75},
        "pros": ["+55% mining", "+30% defense"],
        "cons": ["−45% farming", "−25% trade"],
    },
    "coastal": {
        "name": "Coastal", "emoji": "🌊",
        "desc": "Sea-faring nations. Trade hubs and fishing fleets.",
        "modifiers": {"farming": 0.90, "mining": 0.60, "industry": 0.95, "trade": 1.40},
        "pros": ["+40% trade", "+35% fish"],
        "cons": ["−40% mining"],
    },
    "island": {
        "name": "Island", "emoji": "🏝️",
        "desc": "Isolated specks of land. Trade and fishing, nothing else.",
        "modifiers": {"farming": 0.85, "mining": 0.50, "industry": 0.70, "trade": 1.50},
        "pros": ["+50% trade", "+40% fish", "Naval advantage"],
        "cons": ["−50% mining", "−30% industry"],
    },
}

# Country → climate mapping. Covers all ~180 countries with geojson data.
# (Small nations like Monaco, Vatican, Liechtenstein, etc. are intentionally omitted.)
PROVINCE_CLIMATE = {
    # ---- Europe ----
    "France": "temperate",
    "Germany": "temperate",
    "United Kingdom": "coastal",
    "Ireland": "coastal",
    "Netherlands": "coastal",
    "Belgium": "temperate",
    "Luxembourg": "temperate",
    "Switzerland": "mountainous",
    "Austria": "mountainous",
    "Poland": "plains",
    "Czechia": "temperate",
    "Czech Republic": "temperate",
    "Slovakia": "mountainous",
    "Hungary": "plains",
    "Romania": "temperate",
    "Bulgaria": "temperate",
    "Ukraine": "plains",
    "Belarus": "boreal",
    "Moldova": "plains",
    "Russia": "boreal",
    "Portugal": "mediterranean",
    "Spain": "mediterranean",
    "Italy": "mediterranean",
    "Greece": "mediterranean",
    "Croatia": "mediterranean",
    "Slovenia": "mountainous",
    "Bosnia and Herzegovina": "mountainous",
    "Bosnia and Herz.": "mountainous",
    "Serbia": "temperate",
    "Montenegro": "mountainous",
    "Albania": "mediterranean",
    "North Macedonia": "mountainous",
    "Macedonia": "mountainous",
    "Kosovo": "mountainous",
    "Cyprus": "mediterranean",
    "N. Cyprus": "mediterranean",
    "Norway": "boreal",
    "Sweden": "boreal",
    "Finland": "boreal",
    "Denmark": "coastal",
    "Iceland": "tundra",
    "Estonia": "boreal",
    "Latvia": "boreal",
    "Lithuania": "boreal",
    "Greenland": "arctic",

    # ---- Asia ----
    "Kazakhstan": "steppe",
    "Uzbekistan": "steppe",
    "Turkmenistan": "desert",
    "Kyrgyzstan": "mountainous",
    "Tajikistan": "mountainous",
    "Afghanistan": "mountainous",
    "China": "temperate",
    "Japan": "island",
    "South Korea": "temperate",
    "Korea": "temperate",
    "North Korea": "mountainous",
    "Dem. Rep. Korea": "mountainous",
    "Mongolia": "steppe",
    "Taiwan": "island",
    "India": "monsoon",
    "Pakistan": "desert",
    "Bangladesh": "monsoon",
    "Sri Lanka": "tropical",
    "Nepal": "mountainous",
    "Bhutan": "mountainous",
    "Thailand": "tropical",
    "Vietnam": "monsoon",
    "Indonesia": "tropical",
    "Philippines": "island",
    "Malaysia": "tropical",
    "Singapore": "island",
    "Cambodia": "tropical",
    "Laos": "tropical",
    "Timor-Leste": "tropical",
    "Brunei": "tropical",
    "Myanmar": "tropical",
    "Turkey": "mediterranean",
    "Iran": "desert",
    "Iraq": "desert",
    "Syria": "desert",
    "Lebanon": "mediterranean",
    "Israel": "mediterranean",
    "Palestine": "mediterranean",
    "Jordan": "desert",
    "Saudi Arabia": "desert",
    "Yemen": "desert",
    "Oman": "desert",
    "United Arab Emirates": "desert",
    "UAE": "desert",
    "Qatar": "desert",
    "Kuwait": "desert",
    "Bahrain": "desert",
    "Georgia": "mountainous",
    "Armenia": "mountainous",
    "Azerbaijan": "mountainous",

    # ---- Africa ----
    "Morocco": "mediterranean",
    "Algeria": "desert",
    "Tunisia": "mediterranean",
    "Libya": "desert",
    "Egypt": "desert",
    "Western Sahara": "desert",
    "W. Sahara": "desert",
    "Mauritania": "desert",
    "Senegal": "steppe",
    "Gambia": "tropical",
    "Mali": "desert",
    "Burkina Faso": "steppe",
    "Benin": "tropical",
    "Togo": "tropical",
    "Ghana": "tropical",
    "Ivory Coast": "tropical",
    "Côte d'Ivoire": "tropical",
    "Liberia": "tropical",
    "Sierra Leone": "tropical",
    "Guinea": "tropical",
    "Guinea-Bissau": "tropical",
    "Cape Verde": "island",
    "Nigeria": "tropical",
    "Niger": "desert",
    "Chad": "desert",
    "Cameroon": "tropical",
    "Central African Republic": "tropical",
    "Central African Rep.": "tropical",
    "C.A.R.": "tropical",
    "DR Congo": "tropical",
    "Democratic Republic of the Congo": "tropical",
    "Dem. Rep. Congo": "tropical",
    "Congo (Kinshasa)": "tropical",
    "Republic of Congo": "tropical",
    "Republic of the Congo": "tropical",
    "Congo (Brazzaville)": "tropical",
    "Congo": "tropical",
    "Gabon": "tropical",
    "Equatorial Guinea": "tropical",
    "Eq. Guinea": "tropical",
    "Sao Tome and Principe": "tropical",
    "Sudan": "desert",
    "South Sudan": "tropical",
    "S. Sudan": "tropical",
    "Eritrea": "desert",
    "Ethiopia": "mountainous",
    "Djibouti": "desert",
    "Somalia": "desert",
    "Somaliland": "desert",
    "Kenya": "steppe",
    "Uganda": "tropical",
    "Rwanda": "mountainous",
    "Burundi": "mountainous",
    "Tanzania": "steppe",
    "United Republic of Tanzania": "steppe",
    "Mozambique": "tropical",
    "Madagascar": "tropical",
    "Comoros": "island",
    "Seychelles": "island",
    "Mauritius": "island",
    "Angola": "tropical",
    "Zambia": "steppe",
    "Malawi": "tropical",
    "Zimbabwe": "steppe",
    "Botswana": "desert",
    "Namibia": "desert",
    "South Africa": "steppe",
    "Eswatini": "steppe",
    "eSwatini": "steppe",
    "Swaziland": "steppe",
    "Lesotho": "mountainous",

    # ---- North America ----
    "Canada": "boreal",
    "United States": "temperate",
    "United States of America": "temperate",
    "USA": "temperate",
    "US": "temperate",
    "Mexico": "desert",
    "Guatemala": "tropical",
    "Belize": "tropical",
    "Honduras": "tropical",
    "El Salvador": "tropical",
    "Nicaragua": "tropical",
    "Costa Rica": "tropical",
    "Panama": "tropical",

    # ---- Caribbean ----
    "Cuba": "tropical",
    "Haiti": "tropical",
    "Dominican Republic": "tropical",
    "Dominican Rep.": "tropical",
    "Jamaica": "tropical",
    "Bahamas": "island",
    "Trinidad and Tobago": "tropical",
    "Barbados": "island",
    "Saint Lucia": "island",
    "St. Lucia": "island",
    "Grenada": "island",
    "Antigua and Barbuda": "island",
    "Dominica": "island",
    "St. Kitts and Nevis": "island",
    "Saint Kitts and Nevis": "island",
    "Saint Vincent and the Grenadines": "island",
    "St. Vincent": "island",

    # ---- South America ----
    "Venezuela": "tropical",
    "Colombia": "tropical",
    "Guyana": "tropical",
    "Suriname": "tropical",
    "French Guiana": "tropical",
    "Ecuador": "tropical",
    "Peru": "mountainous",
    "Bolivia": "mountainous",
    "Chile": "desert",
    "Brazil": "tropical",
    "Argentina": "steppe",
    "Uruguay": "plains",
    "Paraguay": "tropical",
    "Falkland Is.": "tundra",

    # ---- Oceania ----
    "Australia": "desert",
    "New Zealand": "temperate",
    "Fiji": "island",
    "Solomon Islands": "tropical",
    "Solomon Is.": "tropical",
    "Vanuatu": "island",
    "Papua New Guinea": "tropical",
    "Samoa": "island",
    "Tonga": "island",
    "Micronesia": "island",
    "Marshall Islands": "island",
    "Marshall Is.": "island",
    "Palau": "island",
    "Nauru": "island",
    "Kiribati": "island",
    "Tuvalu": "island",

    # ---- Antarctica ----
    "Antarctica": "arctic",
}

# ================================================================
# MILITARY
# ================================================================
MILITARY = {
    "soldier_buy_cost": 20, "tech_upgrade_cost": 500,
    "train_cost_soldier_gold": 50, "train_cost_soldier_food": 10,
    "train_cost_spy_gold": 100, "train_cost_spy_food": 5,
    "ship_costs": {
        "frigate": {"gold": 1000, "wood": 200, "stone": 100},
        "destroyer": {"gold": 2000, "wood": 300, "stone": 150},
        "battleship": {"gold": 4000, "wood": 500, "stone": 300},
        "aircraft_carrier": {"gold": 6000, "wood": 800, "stone": 400},
        "submarine": {"gold": 1500, "wood": 100, "stone": 50},
    },
    "plane_costs": {
        "fighter": {"gold": 3000, "wood": 200, "stone": 50},
        "attacker": {"gold": 5000, "wood": 300, "stone": 100},
        "bomber": {"gold": 8000, "wood": 500, "stone": 200},
    },
    "border_cost": {"gold": 1000, "stone": 500, "wood": 300},
}

# ================================================================
# COOLDOWNS (in minutes)
# ================================================================
COOLDOWNS = {
    "gather": 1, "work": 1, "farm": 1, "mine": 1, "harvest": 2,
    "drill": 2, "fish": 1, "labor": 3, "raidcaravan": 3,
    "tax": 5, "lottery": 1, "invest": 5, "advertise": 5,
    "immigration": 5, "sell": 0, "festival": 2, "cheer": 1, "cheerup": 5,
    "buytech": 0, "buysoldiers": 0, "buyspys": 0, "burn": 0, "buycard": 0,
    # New
    "workforce": 0, "assign": 0, "unassign": 0,
    "refine": 3, "market": 0, "market_buy": 0, "market_sell": 0,
    "smuggle": 30, "tools": 0, "tools_buy": 0,

    "train": 2, "find": 1, "attack": 3, "siege": 10,
    "stealthbattle": 4, "navalattack": 3, "airattack": 3,
    "navalblockade": 20, "buildship": 0, "buildplane": 0,
    "tech": 0, "trainboost": 0,
    "addborder": 0, "removeborder": 0, "rectract": 0,
    "retrieve": 0, "borderinfo": 0,

    "ally": 0, "acceptally": 0, "rejectally": 0, "break": 0,
    "send": 0, "trade": 0, "accepttrade": 0, "rejecttrade": 0,
    "mail": 0, "inbox": 0, "coalition": 0,
    "sanction": 0, "liftsanction": 0, "sanctions": 0,

    "blackmarket": 0, "store": 0, "inventory": 0, "market_store": 0,
    "expand": 0, "rapidexpansion": 0, "territories": 0,
    "map": 0,
    "reclaim": 0, "civilwar": 0,

    "openpacks": 0, "evolve": 0, "packs": 0,
    "activate": 0, "deactivate": 0, "synergies": 0,

    "industrial_start": 0, "industrial_status": 0,
    "industrial_build": 2, "industrial_tech": 2, "industrial_workers": 2,
    "industrial_cleanup": 2, "industrial_railway": 2, "industrial_transport": 2,
    "industrial_army": 2, "industrial_policy": 2, "industrial_import": 2,
    "industrial_export": 2, "industrial_steam": 2, "industrial_mine": 2,
    "industrial_hospital": 2, "industrial_school": 2, "industrial_law": 2,
    "industrial_trade": 2, "industrial_aid": 2, "industrial_suppress": 2,
    "industrial_bribe": 2, "industrial_automate": 2, "industrial_upgrade": 2,
    "industrial_relief": 2, "industrial_expand": 2,
    "industrial_banking": 10, "industrial_nationalize": 5, "indushelp": 0,

    "extrawork": 5, "extragamble": 1, "extracards": 1, "slots": 1,
    "blackjack": 1, "job": 1, "arrest": 1, "rob": 1, "code": 0,
    "darkweb": 0, "extrastore": 1, "extrainventory": 0, "setbalance": 0,

    "laststand": 60, "luckystrike": 60, "propaganda": 3,
    "hiremercs": 10, "boosttech": 5, "mintgold": 10, "superharvest": 10,
    "superspy": 10, "megainvent": 5, "backstab": 180, "bomb": 1,
    "nuke": 5, "obliterate": 13, "sacrifice": 1440,
    "clone": 30, "fakeflag": 30, "glitch_protocol": 30,
    "bankraid": 0,

    "megaproject": 0, "policy": 0, "policieshelp": 0,
    "bank": 0, "bank_deposit": 0, "bank_withdraw": 0,
    "bank_loan": 0, "bank_repay": 0,
    "factions": 0, "unionstatus": 0,

    "unite": 0, "acceptunite": 0, "declineunite": 0, "leave": 0,
    "annex": 0, "acceptannex": 0, "declineannex": 0,

    "createdivision": 0, "divisions": 0, "deletedivision": 0,
    "renamedivision": 0, "movedivision": 0,
    "creategeneral": 0, "generals": 0, "deletegeneral": 0,
    "assigngeneral": 0, "unassigngeneral": 0,
    "doctrine": 0, "setdoctrine": 0,
    "tactics": 0,

    "corp": 0, "corp_build": 0,
    "corp_leaderboard": 0, "corp_takeover": 0,

    "daily": 0, "streak": 0,
}

CAPS = {
    "gather": 500_000, "work": 1_000_000, "farm": 200_000,
    "mine_stone": 150_000, "mine_wood": 150_000,
    "harvest": 500_000, "drill_gold": 500_000, "drill_stone": 250_000,
    "fish": 200_000, "tax": 600_000, "raidcaravan": 8_000_000,
    "labor": 3_000_000, "advertise": 20_000, "immigration": 2_500, "sell": 50_000,
}

# ================================================================
# IDEOLOGY MODIFIERS
# ================================================================
IDEOLOGY_MODIFIERS = {
    "fascism": {"soldier_training_speed": 1.25, "diplomacy_success": 0.85, "luck_modifier": 0.90},
    "democracy": {"happiness_boost": 1.20, "trade_profit": 1.10, "soldier_training_speed": 0.85},
    "communism": {"citizen_productivity": 1.10, "tech_speed": 0.90},
    "theocracy": {"propaganda_success": 1.15, "happiness_boost": 1.05, "tech_speed": 0.90},
    "anarchy": {"random_event_frequency": 2.0, "soldier_upkeep": 0.0, "spy_success": 0.80},
    "destruction": {"combat_strength": 1.35, "resource_production": 0.75, "soldier_training_speed": 1.40, "happiness_boost": 0.70, "diplomacy_success": 0.50},
    "pacifist": {"happiness_boost": 1.35, "population_growth": 1.25, "trade_profit": 1.20, "soldier_training_speed": 0.40, "combat_strength": 0.60, "diplomacy_success": 1.25},
    "socialism": {"citizen_productivity": 1.15, "happiness_boost": 1.10, "trade_profit": 0.90},
    "terrorism": {"guerrilla_effectiveness": 1.40, "spy_success": 1.30, "diplomacy_success": 0.50, "resource_production": 0.80, "unrest_multiplier": 1.25},
    "capitalism": {"trade_profit": 1.20, "gold_generation": 1.15, "happiness_boost": 0.90},
    "federalism": {"stability": 1.10, "diplomacy_success": 1.10, "regional_production": 1.05},
    "monarchy": {"loyalty": 1.10, "soldier_morale": 1.10, "reform_speed": 0.90, "happiness_boost": 1.10},
}

REGION_MODIFIERS = {
    "Asia": {"food_production": 1.20, "population_capacity": 1.25},
    "Europe": {"tech_research": 1.25, "gold_production": 1.15},
    "Africa": {"mining_efficiency": 1.30, "stone_production": 1.20},
    "North America": {"balanced_production": 1.10, "trade_efficiency": 1.15},
    "South America": {"food_production": 1.25, "wood_production": 1.15},
    "Middle East": {"gold_production": 1.40, "oil_resources": 1.30},
    "Oceania": {"happiness": 1.15, "naval_advantage": 1.20},
    "Antarctica": {"research_speed": 1.25, "unique_discoveries": 1.30},
}

BLACK_MARKET = {"entry_cost": 1000, "pity_uncommon": 3, "pity_rare": 6, "pity_legendary": 10}

CARD_POOL = [
    {"name": "Resource Boost", "type": "bonus", "effect": {"resource_production": 10}, "description": "+10% resource production"},
    {"name": "Military Training", "type": "bonus", "effect": {"soldier_training_speed": 15}, "description": "+15% soldier training speed"},
    {"name": "Trade Advantage", "type": "bonus", "effect": {"trade_profit": 10}, "description": "+10% trade profit"},
    {"name": "Population Surge", "type": "bonus", "effect": {"population_growth": 10}, "description": "+10% population growth"},
    {"name": "Tech Breakthrough", "type": "one_time", "effect": {"tech_level": 1}, "description": "+1 tech level (max 10)"},
    {"name": "Gold Cache", "type": "one_time", "effect": {"gold": 500}, "description": "Gain 500 gold"},
    {"name": "Food Reserves", "type": "one_time", "effect": {"food": 300}, "description": "Gain 300 food"},
    {"name": "Mercenary Band", "type": "one_time", "effect": {"soldiers": 20}, "description": "Recruit 20 soldiers"},
    {"name": "Spy Network", "type": "one_time", "effect": {"spies": 5}, "description": "Recruit 5 spies"},
    {"name": "Fortification", "type": "bonus", "effect": {"defense_strength": 15}, "description": "+15% defense strength"},
    {"name": "Stone Quarry", "type": "one_time", "effect": {"stone": 200}, "description": "Gain 200 stone"},
    {"name": "Lumber Mill", "type": "one_time", "effect": {"wood": 200}, "description": "Gain 200 wood"},
    {"name": "Intelligence Agency", "type": "bonus", "effect": {"spy_effectiveness": 20}, "description": "+20% spy effectiveness"},
    {"name": "Economic Boom", "type": "one_time", "effect": {"gold": 800, "happiness": 10}, "description": "Gain 800 gold and +10 happiness"},
    {"name": "Military Academy", "type": "bonus", "effect": {"soldier_training_speed": 25}, "description": "+25% soldier training speed"},
]

TERRITORY_FACTOR = {"coefficient": 0.8, "max": 3.0}

STARTING_RESOURCES = {
    "gold": 500, "food": 300, "stone": 100, "wood": 100,
    "citizens": 100, "happiness": 50,
    "soldiers": 10, "spies": 2, "tech_level": 1,
    "land_size": 1000, "hyper_items": ["Anti-Nuke Shield"],
}

EASTER_EGGS = {
    "ncsw": {"bonuses": {"soldier_training_speed": 20, "happiness_boost": -5}, "hyper_item": "Confederate Battle Flag", "message": "⚔️ The spirit of the Confederacy lives on! (+20% soldier training, -5% happiness)"},
    "confederate democracy": {"bonuses": {"diplomacy_success": 10, "happiness_boost": 10}, "message": "📜 A unique blend of Southern charm and democratic ideals! (+10% diplomacy, +10% happiness)"},
    "uspr": {"bonuses": {"resource_production": 15, "trade_profit": -10}, "hyper_item": "Red Banner", "message": "☭ The people's republic rises! (+15% resource production, -10% trade profit)"},
}

INDUSTRIAL = {"banking_max_uses": 5}

EXTRACONOMY = {
    "extrawork_base_salary": 100,
    "extrawork_salary_multipliers": {
        "Teller": 200, "Manager": 400, "Executive": 600,
        "Recruit": 300, "Officer": 500, "Captain": 700,
        "Guard": 240, "Supervisor": 440, "Chief": 640,
        "Clerk": 360, "Minister": 560, "President": 1000,
        "Prime Minister": 1200, "Private": 260, "Sergeant": 460, "Commander": 660,
    },
    "job_application_roles": {
        "bank": ["Rejected", "Teller", "Manager", "Executive"],
        "police": ["Rejected", "Recruit", "Officer", "Captain"],
        "security": ["Rejected", "Guard", "Supervisor", "Chief"],
        "government": ["Rejected", "Clerk", "Minister", "President", "Prime Minister"],
        "military": ["Rejected", "Private", "Sergeant", "Commander"],
    },
    "extrastore_prices": {"ak": 500, "ammo": 100, "glock17": 800, "crypto_miner": 4000},
    "extrastore_stock": {"ak": 5, "ammo": 10, "glock17": 5, "crypto_miner": 2},
    "extrastore_item_names": {"ak": "AK-47", "ammo": "Ammo Box", "glock17": "Glock 17", "crypto_miner": "Crypto Miner"},
    "darkweb_items": {"forged_documents": 5000, "stolen_data": 3000, "silencer": 1500, "explosives": 5000, "crypto_miner": 3500},
    "darkweb_scam_chance": 0.5,
    "slots_jackpot_multiplier": 10, "slots_triple_multiplier": 2,
    "blackjack_win_multiplier": 1, "extracards_win_multiplier": 1,
    "extragamble_win_chance": 0.45, "extragamble_jackpot_chance": 0.10,
    "arrest_success_chance": 0.6, "arrest_seize_amount": 200,
    "rob_success_chance": 0.5, "rob_stolen_min": 100, "rob_stolen_max": 300,
    "coding_projects": {
        "virus": {"cost": 250, "duration_seconds": 1500, "reward_min": 250, "reward_max": 763, "risk": 0.25},
        "website": {"cost": 50, "duration_seconds": 600, "reward_min": 50, "reward_max": 150, "risk": 0},
        "messenger": {"cost": 3500, "duration_seconds": 18000, "reward_type": "product", "viral_chance": 0.45},
    },
    "crypto_miner_income": 200, "crypto_miner_interval": 3600,
    "product_messenger_base_interval": 10800, "product_messenger_viral_interval": 18000,
    "product_messenger_base_payout": 10,
    "product_messenger_viral_payout_min": 1000, "product_messenger_viral_payout_max": 5000,
}

MEGAPROJECTS = {
    "great_wall": {"name": "Great Wall", "cost": {"gold": 5000000, "stone": 2000000}, "effect": {"defense_strength": 50}, "description": "Permanent +50% defense bonus", "tech_required": 5},
    "space_program": {"name": "Space Program", "cost": {"gold": 10000000, "wood": 500000, "stone": 500000}, "effect": {"tech_speed": 100}, "description": "Permanent +100% tech research speed", "tech_required": 7},
    "global_bank": {"name": "Global Bank", "cost": {"gold": 8000000, "food": 1000000}, "effect": {"tax_bonus": 50}, "description": "Permanent +50% tax income", "tech_required": 6},
    "ai_network": {"name": "AI Network", "cost": {"gold": 15000000, "wood": 1000000, "stone": 1000000}, "effect": {"resource_production": 100}, "description": "Permanent +100% all resource production", "tech_required": 8},
    "green_energy": {"name": "Green Energy Grid", "cost": {"gold": 6000000, "wood": 300000, "stone": 300000}, "effect": {"happiness_boost": 20}, "description": "Permanent +20 happiness", "tech_required": 4},
}

POLICIES = {
    "military_service": {"name": "Military Service", "levels": {
        1: {"gold_cost": 50000, "effect": {"soldier_training_speed": 5}, "desc": "+5% soldier training"},
        2: {"gold_cost": 150000, "effect": {"soldier_training_speed": 10}, "desc": "+10% soldier training"},
        3: {"gold_cost": 300000, "effect": {"soldier_training_speed": 20}, "desc": "+20% soldier training"},
    }, "max_level": 3, "base_desc": "Boosts soldier training speed."},
    "agricultural_subsidies": {"name": "Agricultural Subsidies", "levels": {
        1: {"gold_cost": 40000, "food_cost": 20000, "effect": {"farm_bonus": 10}, "desc": "+10% farm yield"},
        2: {"gold_cost": 120000, "food_cost": 60000, "effect": {"farm_bonus": 20}, "desc": "+20% farm yield"},
        3: {"gold_cost": 250000, "food_cost": 120000, "effect": {"farm_bonus": 35}, "desc": "+35% farm yield"},
    }, "max_level": 3, "base_desc": "Increases food production from farming."},
    "trade_agreements": {"name": "Trade Agreements", "levels": {
        1: {"gold_cost": 60000, "effect": {"trade_profit": 5}, "desc": "+5% trade profit"},
        2: {"gold_cost": 180000, "effect": {"trade_profit": 12}, "desc": "+12% trade profit"},
        3: {"gold_cost": 400000, "effect": {"trade_profit": 25}, "desc": "+25% trade profit"},
    }, "max_level": 3, "base_desc": "Increases profit from trades."},
    "public_education": {"name": "Public Education", "levels": {
        1: {"gold_cost": 80000, "effect": {"tech_speed": 5}, "desc": "+5% tech research speed"},
        2: {"gold_cost": 200000, "effect": {"tech_speed": 12}, "desc": "+12% tech research speed"},
        3: {"gold_cost": 500000, "effect": {"tech_speed": 25}, "desc": "+25% tech research speed"},
    }, "max_level": 3, "base_desc": "Accelerates technology research."},
    "environmental_protection": {"name": "Environmental Protection", "levels": {
        1: {"gold_cost": 70000, "stone_cost": 30000, "effect": {"happiness_boost": 5, "resource_production": -5}, "desc": "+5% happiness, -5% resource production"},
        2: {"gold_cost": 180000, "stone_cost": 80000, "effect": {"happiness_boost": 10, "resource_production": -3}, "desc": "+10% happiness, -3% resource production"},
        3: {"gold_cost": 350000, "stone_cost": 150000, "effect": {"happiness_boost": 15, "resource_production": 0}, "desc": "+15% happiness"},
    }, "max_level": 3, "base_desc": "Boosts happiness but may reduce production initially."},
    "industrial_innovation": {"name": "Industrial Innovation", "levels": {
        1: {"gold_cost": 90000, "effect": {"resource_production": 5}, "desc": "+5% all resource production"},
        2: {"gold_cost": 220000, "effect": {"resource_production": 12}, "desc": "+12% all resource production"},
        3: {"gold_cost": 500000, "effect": {"resource_production": 25}, "desc": "+25% all resource production"},
    }, "max_level": 3, "base_desc": "Increases all resource production."},
}

TESTING_GAIN = 0

VICTORY = {
    "domination_percentage": 0.80, "domination_min_territories": 25,
    "economic_gold": 500_000_000, "economic_gdp_per_citizen": 100_000,
    "diplomatic_alliances": 3, "diplomatic_score": 5,
    "industrial_megaprojects": 3, "industrial_policies": 6,
    "conquest_required": True, "united_nations_members": 5,
    "announcement_channels": [],
}

POWER_CURVE = {
    "tech_gather_per_level":  0.012,
    "tech_work_per_level":    0.012,
    "tech_farm_per_level":    0.012,
    "tech_mine_per_level":    0.012,
    "tech_harvest_per_level": 0.012,
    "tech_drill_per_level":   0.012,
    "tech_labor_per_level":   0.012,
    "tech_raid_per_level":    0.012,
    "tech_gold_per_level":    0.03,
    "territory_coefficient":  0.15,
    "territory_cap":          1.30,
    "hyperitem_tech_mult":    0.06,
    "hyperitem_pop_divisor":  40000,
}

FACTIONS = {
    "military": {
        "name": "Military", "emoji": "⚔️",
        "desc": "Wants war, borders, and glory. Angered by peace and passivity.",
        "warning_threshold": 20, "danger_threshold": 10, "blessing_threshold": 80,
        "blessing_effect": {"soldier_strength_mult": 1.15},
        "bane_effect": {"soldier_training_speed": 0.75},
        "civil_war_rebel_kind": "military",
    },
    "merchant": {
        "name": "Merchant", "emoji": "💰",
        "desc": "Wants trade, treaties, and profit. Angered by war and blockades.",
        "warning_threshold": 20, "danger_threshold": 10, "blessing_threshold": 80,
        "blessing_effect": {"gold_income_mult": 1.10},
        "bane_effect": {"gold_income_mult": 0.80},
        "civil_war_rebel_kind": "merchant",
    },
    "people": {
        "name": "People", "emoji": "👥",
        "desc": "Wants food, safety, and low taxes. Angered by labor and heavy taxation.",
        "warning_threshold": 20, "danger_threshold": 10, "blessing_threshold": 80,
        "blessing_effect": {"happiness_boost": 5, "population_growth": 1.02},
        "bane_effect": {"resource_income_mult": 0.80},
        "civil_war_rebel_kind": "people",
    },
}

FACTION_STARTING = {"military": 50, "merchant": 50, "people": 50}

FACTION_EFFECTS = {
    "gather":        {"people": +2},
    "farm":          {"people": +4},
    "mine":          {"merchant": +2, "people": -2},
    "work":          {"merchant": +2},
    "harvest":       {"people": +4},
    "drill":         {"military": +2, "people": -2},
    "labor":         {"military": +2, "people": -6},
    "raidcaravan":   {"military": +4, "merchant": -2},
    "tax":           {"merchant": +2, "people": -5},
    "festival":      {"people": +6},
    "cheer":         {"people": +4},
    "cheerup":       {"people": +6},
    "advertise":     {"people": +2, "merchant": +2},
    "immigration":   {"merchant": +4, "military": -2},
    "invest":        {"merchant": +4},
    "globaltrade":   {"merchant": +6},
    "immigration_riot": {"people": -4},
    "build_corporation": {"merchant": +4},
    "build_megaproject": {"merchant": +3, "military": +2},

    # New workforce/faction interplay
    "assign_industry": {"military": +1},
    "assign_trade":    {"merchant": +1},
    "assign_farming":  {"people": +1},
    "refine":          {"merchant": +2, "military": -1},
    "market_buy":      {"merchant": +1},
    "market_sell":     {"merchant": +2},
    "smuggle":         {"merchant": +3, "people": -2},
    "tool_purchase":   {"merchant": +1},

    "train_soldiers":   {"military": +4},
    "train_spies":      {"military": +2, "merchant": -2},
    "declare_war":      {"military": +4, "merchant": -2},
    "attack":           {"military": +6, "merchant": -4},
    "siege":            {"military": +4, "merchant": -4},
    "stealthbattle":    {"military": +2, "merchant": -2},
    "peace_offer":      {"merchant": +4, "military": -2},
    "accept_peace":     {"merchant": +6, "military": -4},
    "find_soldiers":    {"military": +2},
    "buildship":        {"military": +2},
    "buildplane":       {"military": +2},
    "naval_attack":     {"military": +4, "merchant": -2},
    "air_attack":       {"military": +4, "merchant": -2},
    "naval_blockade":   {"military": +2, "merchant": -6},
    "battle_victory":   {"military": +2},
    "battle_defeat":    {"military": -4},

    "ally":             {"merchant": +4, "people": +2},
    "break_alliance":   {"merchant": -4, "people": -2},
    "trade_accepted":   {"merchant": +6},
    "send_resources":   {"people": +2},
    "coalition":        {"military": +2, "merchant": -2},
    "ceasefire":        {"merchant": +4},

    "impose_sanction":  {"military": +2, "merchant": -4},
    "lift_sanction":    {"merchant": +2},

    "bank_deposit":     {"merchant": +2},
    "bank_loan":        {"merchant": +2, "people": -2},
    "bank_default":     {"merchant": -10, "people": -4},

    "expand":           {"military": +2},
    "rapidexpansion":   {"military": +4, "merchant": -2},
    "reclaim_win":      {"military": +4},
    "lost_province":    {"people": -4},
}

SANCTIONS = {
    "impose_cost_gold": 10_000,
    "duration_hours": 24,
    "max_active_per_imposer": 3,
    "resource_income_multiplier": 0.60,
    "happiness_penalty_per_tick": 3,
    "blocked_commands": [
        "globaltrade", "trade", "market", "market_buy", "market_sell",
        "bank", "bank_deposit", "bank_withdraw", "bank_loan", "bank_repay",
    ],
}

BANKING = {
    "deposit_rate":    0.001,
    "loan_rate":       0.006,
    "max_loan_absolute": 50_000,
    "max_loan_fraction": 0.30,
    "default_days": 5,
    "bank_ban_days": 30,
    "reputation_penalty_days": 7,
    "reputation_income_mult": 0.80,
    "tick_interval_seconds": 3600,
}

# ================================================================
# MILITARY — TACTICAL LAYER
# ================================================================
DOCTRINES = {
    "mobile_warfare": {
        "name": "Mobile Warfare", "emoji": "🏎️",
        "desc": "Fast armored thrusts. Speed over firepower.",
        "attack_mult": 1.15, "defense_mult": 0.90,
        "mobility_mult": 1.30, "supply_mult": 1.20, "casualty_mult": 1.10,
        "allowed_roles": ["breakthrough_armor", "exploitation_armor", "screening_armor",
                          "line_infantry", "ifv_infantry", "cavalry", "field_artillery"],
        "allowed_instructions": ["concentrate_armor", "avoid_urban", "commit_reserves_early",
                                 "sacrifice_supply_for_speed", "project_strength", "pursue_relentlessly"],
    },
    "superior_firepower": {
        "name": "Superior Firepower", "emoji": "💥",
        "desc": "Artillery-heavy. Win by shell, not bullet.",
        "attack_mult": 1.25, "defense_mult": 1.00,
        "mobility_mult": 0.75, "supply_mult": 1.40, "casualty_mult": 0.80,
        "allowed_roles": ["line_infantry", "engineers", "siege_artillery", "field_artillery",
                          "rocket_artillery", "apc_infantry", "assault_guns"],
        "allowed_instructions": ["neutralize_air_first", "destroy_industry", "raid_logistics",
                                 "avoid_urban", "accept_high_casualties", "hold_reserves_late"],
    },
    "mass_assault": {
        "name": "Mass Assault", "emoji": "🌊",
        "desc": "Cheap infantry, huge numbers. Win by attrition.",
        "attack_mult": 1.10, "defense_mult": 0.95,
        "mobility_mult": 0.85, "supply_mult": 0.70, "casualty_mult": 1.40,
        "allowed_roles": ["line_infantry", "assault_infantry", "garrison_infantry",
                          "field_artillery", "engineers", "apc_infantry"],
        "allowed_instructions": ["accept_high_casualties", "ignore_flanks",
                                 "force_enemy_into_open", "hold_high_ground",
                                 "commit_reserves_early"],
    },
    "grand_battleplan": {
        "name": "Grand Battleplan", "emoji": "📋",
        "desc": "Balanced. Predictable. Reliable.",
        "attack_mult": 1.05, "defense_mult": 1.05,
        "mobility_mult": 1.00, "supply_mult": 1.00, "casualty_mult": 0.95,
        "allowed_roles": ["line_infantry", "assault_infantry", "breakthrough_armor",
                          "field_artillery", "siege_artillery", "ifv_infantry",
                          "special_forces"],
        "allowed_instructions": ["neutralize_air_first", "avoid_urban", "hold_high_ground",
                                 "hold_reserves_late", "concentrate_armor", "project_strength"],
    },
    "defense_in_depth": {
        "name": "Defense in Depth", "emoji": "🛡️",
        "desc": "Layered defense. Almost unbreakable on home soil.",
        "attack_mult": 0.80, "defense_mult": 1.35,
        "mobility_mult": 0.85, "supply_mult": 0.90, "casualty_mult": 0.85,
        "allowed_roles": ["garrison_infantry", "engineers", "line_infantry",
                          "siege_artillery", "field_artillery", "screening_armor",
                          "assault_guns"],
        "allowed_instructions": ["hold_high_ground", "refuse_to_leave_flanks_open",
                                 "scorched_earth_on_retreat", "destroy_industry",
                                 "minimize_own_losses", "raid_logistics"],
    },
    "asymmetric": {
        "name": "Asymmetric Warfare", "emoji": "🎭",
        "desc": "Guerrilla, sabotage, high variance.",
        "attack_mult": 1.20, "defense_mult": 0.85,
        "mobility_mult": 1.15, "supply_mult": 0.80, "casualty_mult": 1.15,
        "allowed_roles": ["special_forces", "paratroopers", "air_assault",
                          "garrison_infantry", "screening_armor", "cavalry"],
        "allowed_instructions": ["feign_weakness", "raid_logistics", "destroy_industry",
                                 "ignore_flanks", "avoid_urban", "project_strength"],
    },
}

DOCTRINE_SWITCH_COST = 5_000_000

MENTALITIES = {
    "cautious":   {"name": "Cautious",  "emoji": "🐢", "attack_mult": 0.80, "defense_mult": 1.30, "casualty_mult": 0.65, "happiness_delta": -2, "desc": "Preserve the army. Low risk."},
    "measured":   {"name": "Measured",  "emoji": "⚖️", "attack_mult": 0.95, "defense_mult": 1.15, "casualty_mult": 0.85, "happiness_delta": 0,  "desc": "Controlled aggression."},
    "balanced":   {"name": "Balanced",  "emoji": "➖", "attack_mult": 1.00, "defense_mult": 1.00, "casualty_mult": 1.00, "happiness_delta": 0,  "desc": "Standard engagement."},
    "aggressive": {"name": "Aggressive", "emoji": "🔥", "attack_mult": 1.20, "defense_mult": 0.90, "casualty_mult": 1.20, "happiness_delta": -3, "desc": "Push hard. Take losses."},
    "total_war":  {"name": "Total War", "emoji": "💀", "attack_mult": 1.35, "defense_mult": 0.80, "casualty_mult": 1.50, "happiness_delta": -8, "desc": "No restraint. Maximum damage both ways."},
}

DIVISION_ROLES = {
    "line_infantry":      {"name": "Line Infantry",      "branch": "infantry",   "symbol": "o", "attack_mult": 1.00, "defense_mult": 1.20, "speed": 1.0, "cost_gold": 5,  "cost_food": 3, "desc": "Standard foot soldiers. Reliable."},
    "assault_infantry":   {"name": "Assault Infantry",   "branch": "infantry",   "symbol": "o", "attack_mult": 1.25, "defense_mult": 0.95, "speed": 1.0, "cost_gold": 7,  "cost_food": 4, "desc": "Trained for urban and forest fighting."},
    "garrison_infantry":  {"name": "Garrison Infantry",  "branch": "infantry",   "symbol": "o", "attack_mult": 0.70, "defense_mult": 1.45, "speed": 0.8, "cost_gold": 3,  "cost_food": 2, "desc": "Cheap defensive troops."},
    "engineers":          {"name": "Combat Engineers",   "branch": "infantry",   "symbol": "e", "attack_mult": 1.10, "defense_mult": 1.10, "speed": 0.9, "cost_gold": 8,  "cost_food": 4, "desc": "Reduce enemy fortification bonus."},

    "breakthrough_armor": {"name": "Breakthrough Armor", "branch": "armor",      "symbol": "s", "attack_mult": 1.55, "defense_mult": 0.90, "speed": 1.4, "cost_gold": 18, "cost_food": 7, "desc": "Crack the line. Heavy losses both sides."},
    "exploitation_armor": {"name": "Exploitation Armor", "branch": "armor",      "symbol": "s", "attack_mult": 1.30, "defense_mult": 0.85, "speed": 1.8, "cost_gold": 15, "cost_food": 6, "desc": "Fast push after breakthrough."},
    "screening_armor":    {"name": "Screening Armor",    "branch": "armor",      "symbol": "s", "attack_mult": 0.80, "defense_mult": 1.10, "speed": 1.6, "cost_gold": 10, "cost_food": 5, "desc": "Recon and screening."},
    "assault_guns":       {"name": "Assault Guns",       "branch": "armor",      "symbol": "s", "attack_mult": 1.20, "defense_mult": 1.15, "speed": 0.7, "cost_gold": 12, "cost_food": 6, "desc": "Slow, tough, infantry-support."},

    "field_artillery":    {"name": "Field Artillery",    "branch": "artillery",  "symbol": "P", "attack_mult": 1.25, "defense_mult": 0.85, "speed": 0.8, "cost_gold": 10, "cost_food": 5, "desc": "General-purpose support."},
    "siege_artillery":    {"name": "Siege Artillery",    "branch": "artillery",  "symbol": "P", "attack_mult": 1.45, "defense_mult": 0.75, "speed": 0.6, "cost_gold": 14, "cost_food": 7, "desc": "Destroys fortifications."},
    "rocket_artillery":   {"name": "Rocket Artillery",   "branch": "artillery",  "symbol": "P", "attack_mult": 1.60, "defense_mult": 0.70, "speed": 1.0, "cost_gold": 16, "cost_food": 8, "desc": "Massive burst damage."},

    "paratroopers":       {"name": "Paratroopers",       "branch": "airborne",   "symbol": "^", "attack_mult": 1.30, "defense_mult": 0.90, "speed": 2.2, "cost_gold": 18, "cost_food": 7, "desc": "Seize key points behind lines."},
    "air_assault":        {"name": "Air Assault",        "branch": "airborne",   "symbol": "^", "attack_mult": 1.25, "defense_mult": 0.95, "speed": 2.0, "cost_gold": 20, "cost_food": 8, "desc": "Helicopter insertion."},
    "special_forces":     {"name": "Special Forces",     "branch": "airborne",   "symbol": "^", "attack_mult": 1.40, "defense_mult": 0.85, "speed": 1.8, "cost_gold": 22, "cost_food": 9, "desc": "Sabotage. High variance."},

    "apc_infantry":       {"name": "APC Infantry",       "branch": "mechanized", "symbol": "D", "attack_mult": 1.05, "defense_mult": 1.15, "speed": 1.4, "cost_gold": 10, "cost_food": 5, "desc": "Standard mobile infantry."},
    "ifv_infantry":       {"name": "IFV Infantry",       "branch": "mechanized", "symbol": "D", "attack_mult": 1.20, "defense_mult": 1.05, "speed": 1.3, "cost_gold": 13, "cost_food": 6, "desc": "Heavier armament."},
    "cavalry":            {"name": "Cavalry",            "branch": "mechanized", "symbol": "c", "attack_mult": 0.90, "defense_mult": 0.85, "speed": 2.0, "cost_gold": 6,  "cost_food": 3, "desc": "Fast recon. +5% army speed."},
}

COMBINED_ARMS = {
    ("breakthrough_armor", "line_infantry"):      {"attack": 0.20, "defense": 0.10, "name": "Armored Fist"},
    ("breakthrough_armor", "assault_infantry"):   {"attack": 0.25, "name": "Urban Breakthrough"},
    ("exploitation_armor", "paratroopers"):       {"breakthrough": 0.35, "name": "Air-Land Blitz"},
    ("exploitation_armor", "cavalry"):            {"speed": 0.30, "name": "Recon Screen"},
    ("field_artillery", "line_infantry"):         {"attack": 0.15, "supply_cost": 0.20, "name": "Rolling Barrage"},
    ("rocket_artillery", "breakthrough_armor"):   {"attack": 0.30, "name": "Shock & Awe"},
    ("siege_artillery", "engineers"):             {"fortification_bypass": 0.70, "name": "Sapper Assault"},
    ("special_forces", "paratroopers"):           {"sabotage": 0.40, "name": "Deep Strike"},
    ("ifv_infantry", "assault_guns"):             {"attack": 0.20, "defense": 0.15, "name": "Combined Arms Team"},
    ("garrison_infantry", "siege_artillery"):     {"defense": 0.35, "name": "Fortress Doctrine"},
    ("screening_armor", "exploitation_armor"):    {"speed": 0.25, "name": "Cavalry Screen"},
    ("air_assault", "special_forces"):            {"attack": 0.25, "speed": 0.15, "name": "Rapid Strike"},
}

OPERATIONAL_INSTRUCTIONS = {
    "commit_reserves_early":       {"name": "Commit Reserves Early",       "emoji": "⚡", "effect": {"attack": 0.10, "casualty": 0.15}, "desc": "+10% attack, +15% casualties."},
    "hold_reserves_late":          {"name": "Hold Reserves Late",          "emoji": "⏳", "effect": {"defense": 0.15, "casualty": -0.10}, "desc": "+15% defense, -10% casualties."},
    "concentrate_armor":           {"name": "Concentrate Armor",           "emoji": "🎯", "effect": {"breakthrough": 0.25}, "desc": "+25% breakthrough chance."},
    "avoid_urban":                 {"name": "Avoid Urban Combat",          "emoji": "🚧", "effect": {"attack": -0.10, "casualty": -0.15}, "desc": "-10% attack, -15% casualties in cities."},
    "accept_high_casualties":      {"name": "Accept High Casualties",      "emoji": "💀", "effect": {"attack": 0.20, "casualty": 0.30}, "desc": "+20% attack, +30% casualties."},
    "minimize_own_losses":         {"name": "Minimize Own Losses",         "emoji": "🛡️", "effect": {"attack": -0.15, "casualty": -0.30}, "desc": "-15% attack, -30% casualties."},
    "ignore_flanks":               {"name": "Ignore Flanks",               "emoji": "➡️", "effect": {"attack": 0.15, "risk_encirclement": 0.20}, "desc": "+15% attack, 20% encirclement risk."},
    "refuse_to_leave_flanks_open": {"name": "Refuse Flanks",               "emoji": "🔒", "effect": {"defense": 0.15, "attack": -0.10}, "desc": "+15% defense, -10% attack."},
    "hold_high_ground":            {"name": "Hold High Ground",            "emoji": "⛰️", "effect": {"defense": 0.25}, "desc": "+25% defense."},
    "sacrifice_supply_for_speed":  {"name": "Sacrifice Supply for Speed",  "emoji": "💨", "effect": {"speed": 0.30, "supply": -0.40}, "desc": "+30% speed, -40% supply endurance."},
    "raid_logistics":              {"name": "Raid Logistics",              "emoji": "🚂", "effect": {"enemy_supply_drain": 0.30}, "desc": "Drains enemy supply 30% faster."},
    "destroy_industry":            {"name": "Destroy Industry",            "emoji": "🏭", "effect": {"extra_loot": -0.30, "enemy_long_term_damage": 0.40}, "desc": "Less loot, more damage long-term."},
    "neutralize_air_first":        {"name": "Neutralize Air First",        "emoji": "✈️", "effect": {"enemy_air_penalty": 0.30, "own_ground_penalty": 0.10}, "desc": "-30% enemy air, -10% own ground."},
    "scorched_earth_on_retreat":   {"name": "Scorched Earth",              "emoji": "🔥", "effect": {"enemy_loot_on_loss": -0.40}, "desc": "-40% enemy loot if you lose."},
    "feign_weakness":              {"name": "Feign Weakness",              "emoji": "🎭", "effect": {"enemy_overconfidence": 0.15, "attack": 0.10}, "desc": "+10% ambush chance."},
    "project_strength":            {"name": "Project Strength",            "emoji": "📣", "effect": {"enemy_morale_penalty": 0.10, "own_casualty": 0.05}, "desc": "-10% enemy morale, +5% own casualties."},
    "force_enemy_into_open":       {"name": "Force Enemy Into Open",       "emoji": "🌾", "effect": {"terrain_penalty_negate": 0.50}, "desc": "Ignores half of terrain penalties."},
    "pursue_relentlessly":         {"name": "Pursue Relentlessly",         "emoji": "🏃", "effect": {"loot_on_win": 0.25, "casualty": 0.10}, "desc": "+25% loot on win, +10% casualties."},
}

BATTLE_PHASES = {
    "opening": {
        "name": "Opening Phase", "emoji": "🎬",
        "options": {
            "artillery_barrage":  {"name": "Artillery Barrage",  "effect": {"enemy_defense": -0.15}},
            "air_strike":         {"name": "Air Strike",         "effect": {"enemy_defense": -0.10, "enemy_air": -0.20}},
            "armored_spearhead":  {"name": "Armored Spearhead",  "effect": {"own_attack": 0.15}},
            "infantry_probe":     {"name": "Infantry Probe",     "effect": {"intel": 0.30}},
            "feint":              {"name": "Feint",              "effect": {"enemy_confusion": 0.20}},
        },
    },
    "main": {
        "name": "Main Phase", "emoji": "⚔️",
        "options": {
            "frontal_assault":   {"name": "Frontal Assault",   "effect": {"attack": 0.20, "casualty": 0.15}},
            "flanking_maneuver": {"name": "Flanking Maneuver", "effect": {"attack": 0.15, "enemy_flank": 0.20}},
            "encirclement":      {"name": "Encirclement",      "effect": {"enemy_supply": -0.40}},
            "attrition_grind":   {"name": "Attrition Grind",   "effect": {"casualty": -0.20, "attack": -0.10}},
        },
    },
    "exploitation": {
        "name": "Exploitation Phase", "emoji": "🏆",
        "options": {
            "pursue":      {"name": "Pursue",      "effect": {"extra_loot": 0.25, "casualty": 0.15}},
            "consolidate": {"name": "Consolidate", "effect": {"defense_bonus": 0.20}},
            "fortify":     {"name": "Fortify",     "effect": {"territory_hold": 0.30}},
            "withdraw":    {"name": "Withdraw",    "effect": {"casualty": -0.30, "no_loot": 1.0}},
        },
    },
}

ATTACK_DIRECTIONS = {
    "N":  {"name": "North",     "emoji": "⬆️"},
    "NE": {"name": "Northeast", "emoji": "↗️"},
    "E":  {"name": "East",      "emoji": "➡️"},
    "SE": {"name": "Southeast", "emoji": "↘️"},
    "S":  {"name": "South",     "emoji": "⬇️"},
    "SW": {"name": "Southwest", "emoji": "↙️"},
    "W":  {"name": "West",      "emoji": "⬅️"},
    "NW": {"name": "Northwest", "emoji": "↖️"},
}

TECHNIQUES = {
    "blitzkrieg":       {"name": "Blitzkrieg",       "emoji": "⚡", "attack_mult": 1.40, "defense_mult": 0.90, "cost": {"gold": 5000, "food": 1000}, "terrain_bonus": ["plains"], "terrain_penalty": ["mountain", "urban", "forest"], "counter": "attrition",       "countered_by": "defense_in_depth", "desc": "Fast armored assault. Weak in cities and mountains.", "doctrines": ["mobile_warfare", "grand_battleplan"]},
    "attrition":        {"name": "Attrition",        "emoji": "🪓", "attack_mult": 1.00, "defense_mult": 0.85, "cost": {"gold": 2000, "food": 3000}, "terrain_bonus": ["forest", "mountain"], "terrain_penalty": ["plains"], "counter": "defense_in_depth", "countered_by": "blitzkrieg",       "desc": "Grind the enemy down. Slow but reliable.", "doctrines": ["mass_assault", "superior_firepower", "defense_in_depth"]},
    "encirclement":     {"name": "Encirclement",     "emoji": "🔗", "attack_mult": 1.35, "defense_mult": 0.80, "cost": {"gold": 8000, "food": 2000}, "terrain_bonus": ["plains", "urban"], "terrain_penalty": ["mountain"], "counter": "blitzkrieg",      "countered_by": "attrition",        "desc": "Cut supply lines. Devastating against mobile forces.", "doctrines": ["mobile_warfare", "grand_battleplan"]},
    "defense_in_depth": {"name": "Defense in Depth", "emoji": "🛡️", "attack_mult": 0.85, "defense_mult": 1.30, "cost": {"gold": 3000, "food": 1500}, "terrain_bonus": ["mountain", "urban", "forest"], "terrain_penalty": ["plains"], "counter": "blitzkrieg",      "countered_by": "encirclement",     "desc": "Layered defense. Very hard to break.", "doctrines": ["defense_in_depth", "superior_firepower"]},
    "human_wave":       {"name": "Human Wave",       "emoji": "🌊", "attack_mult": 1.20, "defense_mult": 0.75, "cost": {"gold": 1000, "food": 4000}, "terrain_bonus": [], "terrain_penalty": [], "counter": "attrition",             "countered_by": "blitzkrieg",       "desc": "Sheer numbers. Cheap, costly in lives.", "doctrines": ["mass_assault"]},
    "feint":            {"name": "Feint",            "emoji": "🎭", "attack_mult": 0.90, "defense_mult": 1.00, "cost": {"gold": 4000, "food": 1000}, "terrain_bonus": ["urban"], "terrain_penalty": [], "counter": "encirclement",          "countered_by": "human_wave",       "desc": "Draw enemy forces away. Frees other fronts.", "doctrines": ["asymmetric", "grand_battleplan"]},
}

GENERAL_POSITIVE_TRAITS = {
    "aggressive":  {"name": "Aggressive",  "effect": "attack_mult_bonus",           "value": 1.10, "description": "+10% attack strength."},
    "defensive":   {"name": "Defensive",   "effect": "defense_mult_bonus",          "value": 1.10, "description": "+10% defense strength."},
    "logistician": {"name": "Logistician", "effect": "supply_drain_reduction",      "value": 0.30, "description": "Supply drains 30% slower."},
    "inspiring":   {"name": "Inspiring",   "effect": "morale_recovery_bonus",       "value": 1.15, "description": "+15% morale recovery."},
    "tactician":   {"name": "Tactician",   "effect": "technique_effectiveness_bonus","value": 1.05, "description": "+5% technique effectiveness."},
    "veteran":     {"name": "Veteran",     "effect": "experience_gain_bonus",       "value": 1.20, "description": "+20% experience gain."},
}

GENERAL_NEGATIVE_TRAITS = {
    "reckless":    {"name": "Reckless",    "effect": "casualty_mult",              "value": 1.20, "description": "+20% casualties suffered."},
    "cautious":    {"name": "Cautious",    "effect": "attack_mult_penalty",        "value": 0.85, "description": "-15% attack strength."},
    "glory_hound": {"name": "Glory Hound", "effect": "ignore_orders_chance",       "value": 0.10, "description": "10% chance to ignore orders."},
    "paranoid":    {"name": "Paranoid",    "effect": "morale_penalty",             "value": 0.90, "description": "-10% morale."},
    "stubborn":    {"name": "Stubborn",    "effect": "retreat_refusal_loss_mult",  "value": 1.30, "description": "Won't retreat. +30% losses if losing."},
    "alcoholic":   {"name": "Alcoholic",   "effect": "supply_efficiency_penalty",  "value": 0.80, "description": "Supply runs 20% less efficiently."},
}

DIVISION_LIMITS = {
    "max_per_user": 10,
    "min_size": 500,
    "max_size": 50000,
    "min_name_length": 2,
    "max_name_length": 32,
    "min_soldiers_in_civ": 500,
}

GENERAL_LIMITS = {
    "max_per_user": 5,
    "min_name_length": 2,
    "max_name_length": 32,
}

# ================================================================
# MAP RENDERING
# ================================================================
MAP_RENDER = {
    "padding": 0.08,
    "label_min_area": 30000,
    "label_max_count": 40,
    "font_size": {"world": 6, "region": 8, "warfront": 9, "province": 10},
    "marker_size": 120,
    "marker_alpha": 0.9,
    "cache_ttl": {"world": 300, "region": 120, "warfront": 60, "divisionmap": 60, "province": 120},
}

# ================================================================
# CORPORATIONS
# ================================================================
INDUSTRIES = {
    "agriculture": {
        "name": "Agriculture", "emoji": "🌾",
        "startup_cost": 50_000, "tech_required": 1,
        "consumes": {},
        "produces": {"food": 300},
        "base_wage": 2,
        "desc": "Feeds the nation. Cheap entry, reliable income.",
    },
    "mining": {
        "name": "Mining", "emoji": "⛏️",
        "startup_cost": 150_000, "tech_required": 2,
        "consumes": {},
        "produces": {"stone": 400, "wood": 200},
        "base_wage": 3,
        "desc": "Extract resources. Best in Africa/Central Asia.",
    },
    "manufacturing": {
        "name": "Manufacturing", "emoji": "🏭",
        "startup_cost": 400_000, "tech_required": 4,
        "consumes": {"stone": 200, "wood": 100},
        "produces": {"gold": 3500},
        "base_wage": 4,
        "desc": "Turn raw materials into gold.",
    },
    "banking": {
        "name": "Banking", "emoji": "🏦",
        "startup_cost": 800_000, "tech_required": 5,
        "consumes": {},
        "produces": {"gold": 5500},
        "base_wage": 5,
        "desc": "Financial services. Stable, low risk.",
    },
    "trade": {
        "name": "Trade Company", "emoji": "🚢",
        "startup_cost": 600_000, "tech_required": 3,
        "consumes": {},
        "produces": {"gold": 4500},
        "base_wage": 4,
        "desc": "Trade routes. Needs 3+ provinces.",
        "requires_provinces": 3,
    },
    "arms": {
        "name": "Arms Manufacturing", "emoji": "⚔️",
        "startup_cost": 1_000_000, "tech_required": 6,
        "consumes": {"stone": 300, "wood": 200},
        "produces": {"gold": 4000, "soldiers": 25},
        "base_wage": 6,
        "desc": "Weapons factory. Produces gold AND trains soldiers.",
    },
}

BUSINESS_EVENTS = [
    {"name": "Trade boom",           "desc": "+30% revenue",           "effect": {"revenue_mult": 1.3},  "prob": 0.15, "type": "positive"},
    {"name": "Viral marketing",      "desc": "+5 marketing",            "effect": {"marketing": 5},        "prob": 0.10, "type": "positive"},
    {"name": "Worker innovation",    "desc": "+3 R&D",                  "effect": {"r_and_d": 3},          "prob": 0.10, "type": "positive"},
    {"name": "Government contract",  "desc": "+5,000 gold",             "effect": {"gold_bonus": 5000},    "prob": 0.05, "type": "positive"},
    {"name": "Worker strike",        "desc": "No production, -20 morale","effect": {"skip_production": True, "morale": -20}, "prob": 0.05, "type": "negative"},
    {"name": "Equipment breakdown",  "desc": "-15 efficiency",          "effect": {"efficiency": -15},     "prob": 0.05, "type": "negative"},
    {"name": "Industrial espionage", "desc": "-10 R&D, -2,000 gold",    "effect": {"r_and_d": -10, "gold_bonus": -2000}, "prob": 0.03, "type": "negative"},
    {"name": "Market crash",         "desc": "-40% revenue",            "effect": {"revenue_mult": 0.6},   "prob": 0.03, "type": "negative"},
]

CORP_LIMITS = {
    "max_per_user": 5,
    "min_name_length": 2,
    "max_name_length": 32,
    "starting_efficiency": 100,
    "starting_morale": 100,
    "starting_reputation": 50,
    "max_level": 10,
    "max_employees": 500,
    "max_assets": 100,
    "max_marketing": 100,
    "max_r_and_d": 100,
    "upgrade_base_cost": 50_000,
    "asset_cost_per_point": 2_000,
    "marketing_cost_per_point": 1_500,
    "rd_cost_per_point": 5_000,
    "dividend_min": 1_000,
}

CORP_LEVEL_REQUIREMENTS = {
    "base_cost": 100_000,
    "cost_growth": 1.55,
    "output_bonus_per_level": 0.05,
    "employees_per_level": 50,
    "assets_per_level": 5,
    "marketing_per_level": 5,
    "rd_per_level": 5,
    "branch_slots_per_level": [1, 1, 2, 2, 3, 3, 4, 4, 5, 6],
}

CORP_RESEARCH_TIERS = {
    10: {"key": "automation_1", "name": "Automation I",   "desc": "+5% efficiency floor",
         "bonus": {"efficiency_floor": 5}},
    30: {"key": "automation_2", "name": "Automation II",  "desc": "+10% production output",
         "bonus": {"output_mult": 1.10}},
    50: {"key": "logistics",    "name": "Logistics Network", "desc": "+1 contract slot",
         "bonus": {"contract_slots": 1}},
    70: {"key": "synergy",      "name": "Industrial Synergy", "desc": "+15% output",
         "bonus": {"output_mult": 1.15}},
    90: {"key": "ai_core",      "name": "AI Core",        "desc": "+25% output, +1 reputation/hr",
         "bonus": {"output_mult": 1.25, "rep_rate": 1}},
}

CORP_BRANCH_COST_MULT = 75_000

CORP_CONTRACT_POOL = [
    {"name": "Grain Shipment",    "resource": "food",     "amount": 500,    "reward_gold": 3_000,  "reward_rep": 3, "hours": 24},
    {"name": "Timber Delivery",   "resource": "wood",     "amount": 400,    "reward_gold": 3_500,  "reward_rep": 3, "hours": 24},
    {"name": "Stone Order",       "resource": "stone",    "amount": 600,    "reward_gold": 4_000,  "reward_rep": 3, "hours": 24},
    {"name": "Military Contract", "resource": "soldiers", "amount": 100,    "reward_gold": 8_000,  "reward_rep": 5, "hours": 36},
    {"name": "Rush Order",        "resource": "food",     "amount": 1000,   "reward_gold": 7_000,  "reward_rep": 4, "hours": 12},
    {"name": "Bankroll Deal",     "resource": "gold",     "amount": 15_000, "reward_gold": 20_000, "reward_rep": 6, "hours": 48},
]

CORP_CONTRACT_SLOT_BASE = 1

CORP_TAKEOVER = {
    "min_attacker_rep": 80,
    "cost_per_level": 100_000,
    "success_rep_ratio": 0.60,
}

# ================================================================
# CIVIL WAR
# ================================================================
CIVIL_WAR = {
    "rebel_strength_by_cause": {
        "military": (0.65, 0.85),
        "merchant": (0.45, 0.60),
        "people":   (0.50, 0.70),
    },
    "initial_population_loss_divisor": 10,
    "initial_soldier_loss_divisor": 5,
    "offensive_boost": 1.15,
    "rebel_strength_decay_on_win": 0.92,
    "rebel_strength_growth_on_loss": 1.20,
    "player_losses_on_win_range": (0.08, 0.18),
    "player_losses_on_loss_range": (0.15, 0.30),
    "rebel_capture_chance_on_player_loss": 0.50,
    "ai_title_model": "poolside/laguna-s-2.1:free",
}

# ================================================================
# DAILIES + STREAKS
# ================================================================
DAILY = {
    "cooldown_hours": 24,
    "base_gold": 200,
    "base_food": 100,
    "max_multiplier": 10.0,

    "milestones": {
        3:   {"mult": 1.50, "gold": 300,   "label": "🌱 FIRST STEPS"},
        5:   {"mult": 1.75, "gold": 600,   "label": "🌿 BUILDING"},
        7:   {"mult": 2.00, "gold": 1500,  "label": "🔥 ONE WEEK STRONG"},
        10:  {"mult": 2.25, "gold": 3000,  "label": "⚡ DOUBLE DIGITS"},
        14:  {"mult": 2.50, "gold": 5000,  "label": "💎 TWO WEEKS", "item": "common"},
        21:  {"mult": 3.00, "gold": 10000, "label": "🚀 THREE WEEKS"},
        30:  {"mult": 4.00, "gold": 30000, "label": "👑 ONE MONTH", "item": "rare"},
        45:  {"mult": 5.00, "gold": 60000, "label": "⭐ VETERAN"},
        60:  {"mult": 6.00, "gold": 100000,"label": "🏆 TWO MONTHS"},
        90:  {"mult": 8.00, "gold": 250000,"label": "💠 THREE MONTHS"},
        180: {"mult": 10.00,"gold": 750000,"label": "🌟 HALF YEAR"},
        365: {"mult": 20.00,"gold": 3000000,"label": "🌌 LEGENDARY YEAR", "item": "legendary"},
    },

    "gamble_min": 500,
    "gamble_max": 10000,
    "gamble_lose_chance": 0.40,

    "item_pools": {
        "common":    ["Lucky Charm", "Propaganda Kit", "Mercenary Contract"],
        "rare":      ["Nuclear Warhead", "Dagger", "Missiles"],
        "legendary": ["HyperLaser", "Tech Core", "Anti-Nuke Shield"],
    },
}

DOPAMINE_COLORS = {
    "common": 0x22c55e,
    "good":   0x3b82f6,
    "great":  0xa855f7,
    "epic":   0xf59e0b,
    "legend": 0xff0080,
}
