import os
import random
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Game Data Storage
players = {}
wars = {}
peace_offers = {}
borders = {}
unlocked_cards = {}

# Game Constants
IDEOLOGIES = ['fascism', 'democracy', 'communism', 'theocracy', 'anarchy', 
              'destruction', 'pacifist', 'socialism', 'terrorism', 'capitalism', 
              'federalism', 'monarchy']

REGIONS = ['Northlands', 'Southlands', 'Eastlands', 'Westlands', 'Central Valley', 
           'Coastal Plains', 'Mountain Realm', 'Desert Kingdom', 'Forest Domain']

RESOURCES = ['gold', 'food', 'stone', 'wood']
MILITARY_UNITS = ['soldiers', 'spies']

CARDS = {
    'lightning_strike': {'name': 'Lightning Strike', 'effect': 'Double attack damage for one battle'},
    'fortify': {'name': 'Fortify', 'effect': 'Instantly build maximum border defense'},
    'espionage': {'name': 'Espionage', 'effect': 'Steal 20% of enemy resources'},
    'rebellion': {'name': 'Rebellion', 'effect': 'Cause enemy to lose 30% soldiers'},
    'harvest': {'name': 'Bountiful Harvest', 'effect': 'Gain 500 food'},
    'gold_rush': {'name': 'Gold Rush', 'effect': 'Gain 1000 gold'},
    'propaganda': {'name': 'Propaganda', 'effect': 'Increase happiness by 50%'},
    'blitzkrieg': {'name': 'Blitzkrieg', 'effect': 'Triple damage but lose 50% soldiers'}
}

class Player:
    def __init__(self, user_id):
        self.user_id = user_id
        self.ideology = None
        self.resources = {'gold': 100, 'food': 200, 'stone': 50, 'wood': 100}
        self.military = {'soldiers': 10, 'spies': 2, 'tech_level': 1}
        self.population = {'citizens': 50, 'happiness': 100, 'hunger': 0}
        self.territory = {'land_size': 100}
        self.region = None
        self.started = False

def get_player(user_id):
    if user_id not in players:
        players[user_id] = Player(user_id)
    return players[user_id]

def calculate_ideology_bonuses(ideology):
    bonuses = {
        'fascism': {'soldiers': 1.3, 'happiness': 0.7, 'tech_growth': 0.8},
        'democracy': {'soldiers': 0.9, 'happiness': 1.4, 'tech_growth': 1.2},
        'communism': {'soldiers': 1.1, 'food': 1.3, 'gold': 0.8},
        'theocracy': {'happiness': 1.3, 'spies': 0.7, 'citizens': 1.2},
        'anarchy': {'random_bonus': 2.0, 'stability': 0.5},
        'destruction': {'soldiers': 1.5, 'happiness': 0.5, 'resources': 0.7},
        'pacifist': {'happiness': 1.6, 'soldiers': 0.3, 'food': 1.4},
        'socialism': {'happiness': 1.3, 'food': 1.2, 'gold': 0.9},
        'terrorism': {'spies': 2.0, 'soldiers': 0.8, 'happiness': 0.6},
        'capitalism': {'gold': 1.5, 'happiness': 1.1, 'food': 0.9},
        'federalism': {'stability': 1.4, 'tech_growth': 1.3},
        'monarchy': {'soldiers': 1.2, 'gold': 1.2, 'happiness': 1.1}
    }
    return bonuses.get(ideology, {})

# ============ BASIC COMMANDS ============

@bot.command()
async def start(ctx):
    """Start a new civilization with cinematic intro"""
    player = get_player(ctx.author.id)
    
    if player.started:
        await ctx.send("You already have a civilization!")
        return
    
    intro = """
🌅 **THE DAWN OF CIVILIZATION** 🌅

As the mists of time part, a new civilization emerges from the wilderness...
Your people look to you for guidance, for protection, for greatness.

The world is vast and untamed. Resources are scarce, dangers lurk in shadowed lands,
and other civilizations will rise to challenge your dominion.

Will you build an empire that stands the test of time?
Or will your name be lost to the sands of history?

**YOUR JOURNEY BEGINS NOW...**
    """
    
    player.started = True
    await ctx.send(intro)
    await ctx.send(f"🎯 **Use `!ideology` to choose your government type and begin your rule!**")

@bot.command()
async def ideology(ctx, *, ideology_choice: str = None):
    """Choose your civilization's government ideology"""
    player = get_player(ctx.author.id)
    
    if not player.started:
        await ctx.send("You must first start your civilization with `!start`")
        return
    
    if ideology_choice is None:
        ideology_list = "\n".join([f"• {ideology.capitalize()}" for ideology in IDEOLOGIES])
        await ctx.send(f"**Available Ideologies:**\n{ideology_list}\n\nUse `!ideology [name]` to choose your path.")
        return
    
    ideology_choice = ideology_choice.lower()
    
    if ideology_choice not in IDEOLOGIES:
        await ctx.send(f"Invalid ideology! Use `!ideology` to see available options.")
        return
    
    player.ideology = ideology_choice
    bonuses = calculate_ideology_bonuses(ideology_choice)
    
    bonus_text = []
    for stat, multiplier in bonuses.items():
        bonus_text.append(f"{stat}: {multiplier}x")
    
    await ctx.send(f"""
🏛️ **{ctx.author.display_name} has chosen {ideology_choice.upper()}!** 🏛️

Your civilization now follows the path of {ideology_choice.capitalize()}.
**Ideology Bonuses:** {', '.join(bonus_text)}

Your people await your commands, great leader!
Use `!status` to view your civilization's current state.
    """)

@bot.command()
async def status(ctx):
    """View your civilization status"""
    player = get_player(ctx.author.id)
    
    if not player.started:
        await ctx.send("Start your civilization with `!start`")
        return
    
    if not player.ideology:
        await ctx.send("Choose your ideology with `!ideology`")
        return
    
    # Calculate resource production based on ideology
    ideology_bonus = calculate_ideology_bonuses(player.ideology)
    
    status_msg = f"""
🏰 **{ctx.author.display_name}'s Civilization** 🏰
**Ideology:** {player.ideology.upper()}
**Region:** {player.region if player.region else 'Not chosen'}

💰 **RESOURCES:**
• Gold: {player.resources['gold']}
• Food: {player.resources['food']}
• Stone: {player.resources['stone']}
• Wood: {player.resources['wood']}

⚔️ **MILITARY:**
• Soldiers: {player.military['soldiers']}
• Spies: {player.military['spies']}
• Tech Level: {player.military['tech_level']}

👥 **POPULATION:**
• Citizens: {player.population['citizens']}
• Happiness: {player.population['happiness']}/100
• Hunger: {player.population['hunger']}/100

🗺️ **TERRITORY:**
• Land Size: {player.territory['land_size']} sq km
"""
    
    await ctx.send(status_msg)

@bot.command()
async def warhelp(ctx):
    """Display help information"""
    help_msg = """
🎯 **CIVILIZATION WARS - COMMAND GUIDE** 🎯

**BASIC COMMANDS:**
`!start` - Begin your civilization journey
`!ideology` - Choose your government type  
`!status` - Check your civilization status
`!regions` - View/select your region

**ECONOMY COMMANDS:**
`!work` - Gather resources
`!store` - Check marketplace
`!inventory` - View your items
`!gamble` - Risk resources for reward
`!give @user resource amount` - Trade with others

**MILITARY & DIPLOMACY:**
`!train soldier/spy amount` - Build your military
`!find` - Search for wandering soldiers
`!declare @user` - Declare war
`!attack @user` - Direct assault
`!siege @user` - Long-term siege
`!stealthbattle @user` - Spy attack
`!peace @user` - Offer peace
`!accept_peace @user` - Accept peace offer

**BORDER MANAGEMENT:**
`!addborder soldiers` - Build defensive border
`!removeborder` - Remove border defense
`!rectract percent` - Assign soldiers to border
`!retrieve percent` - Retrieve border soldiers
`!borderinfo` - Check border status

**CARDS SYSTEM:**
`!cards` - View/use unlocked cards
• Cards unlock randomly (20% chance) after military actions
• Powerful but risky effects
"""
    await ctx.send(help_msg)

@bot.command()
async def regions(ctx, *, region_choice: str = None):
    """View or select your civilization's region"""
    player = get_player(ctx.author.id)
    
    if not player.started:
        await ctx.send("Start your civilization with `!start`")
        return
    
    if region_choice is None:
        regions_list = "\n".join([f"• {region}" for region in REGIONS])
        await ctx.send(f"**Available Regions:**\n{regions_list}\n\nUse `!regions [name]` to claim your homeland.")
        return
    
    region_choice = region_choice.title()
    
    if region_choice not in REGIONS:
        await ctx.send("Invalid region! Use `!regions` to see available options.")
        return
    
    player.region = region_choice
    
    region_bonuses = {
        'Northlands': "Bonus: +20% stone, hardy citizens",
        'Southlands': "Bonus: +30% food, fertile lands", 
        'Eastlands': "Bonus: +25% gold, trade routes",
        'Westlands': "Bonus: +25% wood, vast forests",
        'Central Valley': "Bonus: Balanced resources, strategic position",
        'Coastal Plains': "Bonus: +15% all resources, naval advantage",
        'Mountain Realm': "Bonus: +40% stone, natural defense",
        'Desert Kingdom': "Bonus: +50% gold, unique trade goods",
        'Forest Domain': "Bonus: +40% wood, stealth bonuses"
    }
    
    await ctx.send(f"""
🗺️ **REGION CLAIMED: {region_choice.upper()}** 🗺️

Your civilization now calls {region_choice} home!
**{region_bonuses[region_choice]}**

The land provides for your people. Use it wisely!
    """)

# ============ ECONOMY COMMANDS ============

@bot.command()
async def work(ctx):
    """Gather resources through labor"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    # Base resource gain
    gold_gain = random.randint(50, 150)
    food_gain = random.randint(80, 200)
    stone_gain = random.randint(20, 80)
    wood_gain = random.randint(60, 120)
    
    # Apply ideology bonuses
    ideology_bonus = calculate_ideology_bonuses(player.ideology)
    
    if 'gold' in ideology_bonus:
        gold_gain = int(gold_gain * ideology_bonus['gold'])
    if 'food' in ideology_bonus:
        food_gain = int(food_gain * ideology_bonus['food'])
    
    player.resources['gold'] += gold_gain
    player.resources['food'] += food_gain
    player.resources['stone'] += stone_gain
    player.resources['wood'] += wood_gain
    
    # Small chance for extra event
    event_text = ""
    if random.random() < 0.2:
        bonus_resource = random.choice(RESOURCES)
        bonus_amount = random.randint(50, 100)
        player.resources[bonus_resource] += bonus_amount
        event_text = f"\n🎁 **BONUS:** Found extra {bonus_amount} {bonus_resource}!"
    
    await ctx.send(f"""
💼 **WORK COMPLETE** 💼
Your citizens have labored and gathered:

💰 +{gold_gain} Gold
🌾 +{food_gain} Food  
🪨 +{stone_gain} Stone
🪵 +{wood_gain} Wood
{event_text}
    """)

@bot.command()
async def store(ctx):
    """Check marketplace and trade"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    store_msg = """
🏪 **CIVILIZATION MARKETPLACE** 🏪

**Exchange Rates (Buy/Sell):**
• 1 Gold ←→ 2 Food
• 1 Gold ←→ 1 Stone  
• 1 Gold ←→ 1 Wood
• 1 Soldier ←→ 10 Gold + 5 Food

**Special Deals:**
• Tech Upgrade: 500 Gold + 200 Stone
• Land Expansion: 300 Gold + 100 Wood

*Use trading to optimize your resource balance!*
"""
    await ctx.send(store_msg)

@bot.command()
async def inventory(ctx):
    """View your items and resources"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    # Check for unlocked cards
    user_cards = unlocked_cards.get(ctx.author.id, [])
    
    cards_text = "\n".join([f"• {card}: {CARDS[card]['effect']}" for card in user_cards]) if user_cards else "No cards unlocked yet"
    
    inventory_msg = f"""
🎒 **INVENTORY & ASSETS** 🎒

**Resources:**
💰 Gold: {player.resources['gold']}
🌾 Food: {player.resources['food']}
🪨 Stone: {player.resources['stone']}
🪵 Wood: {player.resources['wood']}

**Military Assets:**
⚔️ Soldiers: {player.military['soldiers']}
🕵️ Spies: {player.military['spies']}
🔬 Tech Level: {player.military['tech_level']}

**Unlocked Cards:**
{cards_text}

*Military actions have 20% chance to unlock powerful cards!*
"""
    await ctx.send(inventory_msg)

@bot.command()
async def gamble(ctx, amount: int = None):
    """Gamble resources for potential reward"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if amount is None:
        await ctx.send("Usage: `!gamble [amount]` - Risk gold for 2x reward or total loss!")
        return
    
    if player.resources['gold'] < amount:
        await ctx.send("You don't have enough gold to gamble that much!")
        return
    
    # 45% chance to win, 55% chance to lose
    if random.random() < 0.45:
        player.resources['gold'] += amount  # Double your money
        await ctx.send(f"🎰 **JACKPOT!** 🎰\nYou won {amount} gold! Total gained: {amount * 2}!")
    else:
        player.resources['gold'] -= amount
        await ctx.send(f"💸 **BUST!** 💸\nYou lost {amount} gold in the gamble...")

@bot.command()
async def slots(ctx, bet: int = 10):
    """Slot machine game"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if player.resources['gold'] < bet:
        await ctx.send("Not enough gold to play slots!")
        return
    
    symbols = ['💰', '🌾', '🪨', '🪵', '⚔️', '🏰', '👑', '💎']
    result = [random.choice(symbols) for _ in range(3)]
    
    slots_display = f"🎰 | {' | '.join(result)} | 🎰"
    
    # Check for wins
    if result[0] == result[1] == result[2]:
        win_amount = bet * 10
        player.resources['gold'] += win_amount
        await ctx.send(f"{slots_display}\n**JACKPOT!** 🎉 You won {win_amount} gold!")
    elif result[0] == result[1] or result[1] == result[2]:
        win_amount = bet * 2
        player.resources['gold'] += win_amount
        await ctx.send(f"{slots_display}\n**WINNER!** 🎊 You won {win_amount} gold!")
    else:
        player.resources['gold'] -= bet
        await ctx.send(f"{slots_display}\n**No win this time...** Lost {bet} gold")

@bot.command()
async def blackjack(ctx, bet: int = 10):
    """Simple blackjack game"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if player.resources['gold'] < bet:
        await ctx.send("Not enough gold to play blackjack!")
        return
    
    player_cards = [random.randint(1, 11) for _ in range(2)]
    dealer_cards = [random.randint(1, 11)]
    
    player_total = sum(player_cards)
    dealer_total = sum(dealer_cards)
    
    # Simple blackjack logic
    if player_total == 21:
        win_amount = int(bet * 2.5)
        player.resources['gold'] += win_amount
        await ctx.send(f"♠️♥️♣️♦️ **BLACKJACK!** ♦️♣️♥️♠️\nYour cards: {player_cards} = {player_total}\nYou win {win_amount} gold!")
    elif player_total > 21:
        player.resources['gold'] -= bet
        await ctx.send(f"💥 **BUST!** 💥\nYour cards: {player_cards} = {player_total}\nDealer shows: {dealer_cards}\nLost {bet} gold!")
    else:
        # Dealer draws
        dealer_cards.append(random.randint(1, 11))
        dealer_total = sum(dealer_cards)
        
        if dealer_total > 21 or player_total > dealer_total:
            win_amount = bet * 2
            player.resources['gold'] += win_amount
            await ctx.send(f"🎯 **YOU WIN!** 🎯\nYour cards: {player_cards} = {player_total}\nDealer: {dealer_cards} = {dealer_total}\nWon {win_amount} gold!")
        else:
            player.resources['gold'] -= bet
            await ctx.send(f"😞 **DEALER WINS** 😞\nYour cards: {player_cards} = {player_total}\nDealer: {dealer_cards} = {dealer_total}\nLost {bet} gold!")

@bot.command()
async def give(ctx, member: discord.Member, resource: str, amount: int):
    """Give resources to another player"""
    player = get_player(ctx.author.id)
    target_player = get_player(member.id)
    
    if not check_civilization_ready(ctx, player) or not check_civilization_ready(ctx, target_player):
        return
    
    resource = resource.lower()
    
    if resource not in RESOURCES:
        await ctx.send(f"Invalid resource! Choose from: {', '.join(RESOURCES)}")
        return
    
    if player.resources[resource] < amount:
        await ctx.send(f"You don't have enough {resource}!")
        return
    
    player.resources[resource] -= amount
    target_player.resources[resource] += amount
    
    await ctx.send(f"🤝 **TRADE COMPLETE** 🤝\nYou gave {member.display_name} {amount} {resource}!")

@bot.command()
async def setbalance(ctx, resource: str, amount: int):
    """[ADMIN] Set resource balance"""
    # Simple admin check - in real bot, use proper permissions
    if ctx.author.id != ctx.guild.owner_id:
        await ctx.send("Only server owners can use this command!")
        return
    
    player = get_player(ctx.author.id)
    resource = resource.lower()
    
    if resource not in RESOURCES:
        await ctx.send(f"Invalid resource! Choose from: {', '.join(RESOURCES)}")
        return
    
    player.resources[resource] = amount
    await ctx.send(f"Set {resource} to {amount}!")

# ============ MILITARY & DIPLOMACY COMMANDS ============

@bot.command()
async def train(ctx, unit_type: str, amount: int = 1):
    """Train soldiers or spies"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    unit_type = unit_type.lower()
    
    if unit_type not in MILITARY_UNITS:
        await ctx.send("Train either 'soldiers' or 'spies'!")
        return
    
    cost_per_soldier = {'gold': 5, 'food': 3}
    cost_per_spy = {'gold': 20, 'food': 5}
    
    if unit_type == 'soldiers':
        total_gold_cost = cost_per_soldier['gold'] * amount
        total_food_cost = cost_per_soldier['food'] * amount
        
        if player.resources['gold'] < total_gold_cost or player.resources['food'] < total_food_cost:
            await ctx.send(f"Not enough resources! Need {total_gold_cost} gold and {total_food_cost} food for {amount} soldiers.")
            return
        
        player.resources['gold'] -= total_gold_cost
        player.resources['food'] -= total_food_cost
        player.military['soldiers'] += amount
        
        await ctx.send(f"⚔️ **TRAINING COMPLETE** ⚔️\nTrained {amount} new soldiers!\nCost: {total_gold_cost} gold, {total_food_cost} food")
    
    else:  # spies
        total_gold_cost = cost_per_spy['gold'] * amount
        total_food_cost = cost_per_spy['food'] * amount
        
        if player.resources['gold'] < total_gold_cost or player.resources['food'] < total_food_cost:
            await ctx.send(f"Not enough resources! Need {total_gold_cost} gold and {total_food_cost} food for {amount} spies.")
            return
        
        player.resources['gold'] -= total_gold_cost
        player.resources['food'] -= total_food_cost
        player.military['spies'] += amount
        
        await ctx.send(f"🕵️ **ESPIONAGE TRAINING** 🕵️\nTrained {amount} new spies!\nCost: {total_gold_cost} gold, {total_food_cost} food")
    
    # Chance to unlock card after military training
    if random.random() < 0.2:
        unlock_random_card(ctx.author.id)
        await ctx.send("🎴 **CARD UNLOCKED!** Use `!cards` to view your new card!")

@bot.command()
async def find(ctx):
    """Search for wandering soldiers"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    # 60% chance to find soldiers, 30% to find resources, 10% to find nothing
    roll = random.random()
    
    if roll < 0.6:
        found_soldiers = random.randint(1, 5)
        player.military['soldiers'] += found_soldiers
        await ctx.send(f"🎯 **RECRUITS FOUND!** 🎯\nYou discovered {found_soldiers} wandering soldiers who joined your army!")
    
    elif roll < 0.9:
        found_gold = random.randint(10, 50)
        player.resources['gold'] += found_gold
        await ctx.send(f"💰 **TREASURE FOUND!** 💰\nYou discovered {found_gold} gold while searching!")
    
    else:
        await ctx.send("🔍 **SEARCH COMPLETE** 🔍\nYour scouts found nothing of value this time...")
    
    # Chance to unlock card
    if random.random() < 0.2:
        unlock_random_card(ctx.author.id)
        await ctx.send("🎴 **CARD UNLOCKED!** Use `!cards` to view your new card!")

@bot.command()
async def declare(ctx, member: discord.Member):
    """Declare war on another civilization"""
    player = get_player(ctx.author.id)
    target_player = get_player(member.id)
    
    if not check_civilization_ready(ctx, player) or not check_civilization_ready(ctx, target_player):
        return
    
    if ctx.author.id == member.id:
        await ctx.send("You cannot declare war on yourself!")
        return
    
    war_key = tuple(sorted([ctx.author.id, member.id]))
    
    if war_key in wars:
        await ctx.send("You are already at war with this civilization!")
        return
    
    # Declare war
    wars[war_key] = {
        'started_by': ctx.author.id,
        'start_time': ctx.message.created_at,
        'battles_fought': 0
    }
    
    await ctx.send(f"""
⚔️ **WAR DECLARED!** ⚔️

**{ctx.author.display_name}** has declared war on **{member.display_name}**!

The fate of both civilizations hangs in the balance...
Use `!attack @user` to launch assaults or `!peace @user` to seek peace.
    """)

@bot.command()
async def attack(ctx, member: discord.Member):
    """Launch direct attack on enemy"""
    player = get_player(ctx.author.id)
    target_player = get_player(member.id)
    
    if not check_civilization_ready(ctx, player) or not check_civilization_ready(ctx, target_player):
        return
    
    war_key = tuple(sorted([ctx.author.id, member.id]))
    
    if war_key not in wars:
        await ctx.send("You must declare war first with `!declare @user`!")
        return
    
    if player.military['soldiers'] < 5:
        await ctx.send("You need at least 5 soldiers to launch an attack!")
        return
    
    # Calculate battle outcome
    attacker_power = player.military['soldiers'] * player.military['tech_level']
    defender_power = target_player.military['soldiers'] * target_player.military['tech_level']
    
    # Border defense bonus
    border_defense = borders.get(member.id, {}).get('strength', 0)
    defender_power += border_defense
    
    total_power = attacker_power + defender_power
    attacker_victory_chance = attacker_power / total_power
    
    # Battle resolution
    if random.random() < attacker_victory_chance:
        # Attacker wins
        damage_to_defender = random.randint(10, 30)
        damage_to_attacker = random.randint(5, 15)
        
        # Apply damage
        target_player.military['soldiers'] = max(0, target_player.military['soldiers'] - damage_to_defender)
        player.military['soldiers'] = max(0, player.military['soldiers'] - damage_to_attacker)
        
        # Loot resources
        loot_gold = min(random.randint(50, 150), target_player.resources['gold'] // 2)
        loot_food = min(random.randint(80, 200), target_player.resources['food'] // 2)
        
        target_player.resources['gold'] -= loot_gold
        target_player.resources['food'] -= loot_food
        player.resources['gold'] += loot_gold
        player.resources['food'] += loot_food
        
        await ctx.send(f"""
🎯 **VICTORY!** 🎯

**{ctx.author.display_name}** defeats **{member.display_name}** in battle!

**Casualties:**
• Enemy lost {damage_to_defender} soldiers
• You lost {damage_to_attacker} soldiers

**Plunder:**
💰 {loot_gold} Gold
🌾 {loot_food} Food

The enemy civilization reels from your assault!
        """)
    
    else:
        # Defender wins
        damage_to_attacker = random.randint(15, 35)
        damage_to_defender = random.randint(3, 10)
        
        player.military['soldiers'] = max(0, player.military['soldiers'] - damage_to_attacker)
        target_player.military['soldiers'] = max(0, target_player.military['soldiers'] - damage_to_defender)
        
        await ctx.send(f"""
🛡️ **DEFEAT!** 🛡️

**{member.display_name}** repels your attack!

**Casualties:**
• You lost {damage_to_attacker} soldiers  
• Enemy lost {damage_to_defender} soldiers

Your forces retreat in disarray. The enemy's defenses were too strong!
        """)
    
    wars[war_key]['battles_fought'] += 1
    
    # Chance to unlock card after battle
    if random.random() < 0.2:
        unlock_random_card(ctx.author.id)
        await ctx.send("🎴 **CARD UNLOCKED!** Use `!cards` to view your new card!")

@bot.command()
async def siege(ctx, member: discord.Member):
    """Lay siege to enemy territory"""
    player = get_player(ctx.author.id)
    target_player = get_player(member.id)
    
    if not check_civilization_ready(ctx, player) or not check_civilization_ready(ctx, target_player):
        return
    
    war_key = tuple(sorted([ctx.author.id, member.id]))
    
    if war_key not in wars:
        await ctx.send("You must declare war first with `!declare @user`!")
        return
    
    if player.military['soldiers'] < 20:
        await ctx.send("You need at least 20 soldiers to lay siege!")
        return
    
    # Siege mechanics
    siege_duration = random.randint(3, 7)  # "days"
    siege_damage = random.randint(5, 15) * siege_duration
    
    target_player.military['soldiers'] = max(0, target_player.military['soldiers'] - siege_damage)
    player.military['soldiers'] = max(0, player.military['soldiers'] - random.randint(5, 10))
    
    # Siege reduces enemy happiness and resources
    target_player.population['happiness'] = max(0, target_player.population['happiness'] - 10)
    resource_loss = min(100, target_player.resources['food'] // 4)
    target_player.resources['food'] -= resource_loss
    
    await ctx.send(f"""
🏰 **SIEGE LAID!** 🏰

**{ctx.author.display_name}** besieges **{member.display_name}** for {siege_duration} days!

**Siege Results:**
• Enemy lost {siege_damage} soldiers to attrition
• Enemy lost {resource_loss} food to supply cuts  
• Enemy happiness decreased by 10

The enemy civilization suffers under your relentless siege!
    """)
    
    # Chance to unlock card
    if random.random() < 0.2:
        unlock_random_card(ctx.author.id)
        await ctx.send("🎴 **CARD UNLOCKED!** Use `!cards` to view your new card!")

@bot.command()
async def stealthbattle(ctx, member: discord.Member):
    """Spy-based stealth attack"""
    player = get_player(ctx.author.id)
    target_player = get_player(member.id)
    
    if not check_civilization_ready(ctx, player) or not check_civilization_ready(ctx, target_player):
        return
    
    war_key = tuple(sorted([ctx.author.id, member.id]))
    
    if war_key not in wars:
        await ctx.send("You must declare war first with `!declare @user`!")
        return
    
    if player.military['spies'] < 3:
        await ctx.send("You need at least 3 spies for a stealth operation!")
        return
    
    # Stealth battle mechanics
    success_chance = player.military['spies'] / (player.military['spies'] + target_player.military['spies'] + 1)
    
    if random.random() < success_chance:
        # Successful sabotage
        sabotage_damage = random.randint(5, 15)
        stolen_gold = min(random.randint(100, 300), target_player.resources['gold'] // 3)
        
        target_player.military['soldiers'] = max(0, target_player.military['soldiers'] - sabotage_damage)
        target_player.resources['gold'] -= stolen_gold
        player.resources['gold'] += stolen_gold
        
        # Chance to lose spies
        if random.random() < 0.3:
            spy_loss = random.randint(1, 2)
            player.military['spies'] = max(0, player.military['spies'] - spy_loss)
            spy_loss_text = f"\n• {spy_loss} spies were caught and eliminated"
        else:
            spy_loss_text = "\n• All spies returned safely"
        
        await ctx.send(f"""
🕵️ **SABOTAGE SUCCESS!** 🕵️

Your spies infiltrate **{member.display_name}**'s civilization!

**Operation Results:**
• Enemy lost {sabotage_damage} soldiers to sabotage
• Stole {stolen_gold} gold from enemy treasury{spy_loss_text}

The enemy never saw it coming!
        """)
    
    else:
        # Failed operation
        spy_loss = random.randint(2, 4)
        player.military['spies'] = max(0, player.military['spies'] - spy_loss)
        
        await ctx.send(f"""
🚨 **OPERATION FAILED!** 🚨

Your spies were detected by **{member.display_name}**'s counter-intelligence!

**Losses:**
• {spy_loss} spies captured or eliminated

Your espionage network has been compromised!
        """)
    
    # Chance to unlock card
    if random.random() < 0.2:
        unlock_random_card(ctx.author.id)
        await ctx.send("🎴 **CARD UNLOCKED!** Use `!cards` to view your new card!")

@bot.command()
async def cards(ctx):
    """View and use unlocked cards"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    user_cards = unlocked_cards.get(ctx.author.id, [])
    
    if not user_cards:
        await ctx.send("You haven't unlocked any cards yet! Cards have a 20% chance to unlock after military actions.")
        return
    
    cards_list = "\n".join([f"**{card}** - {CARDS[card]['effect']}" for card in user_cards])
    
    await ctx.send(f"""
🎴 **YOUR UNLOCKED CARDS** 🎴

{cards_list}

Use a card with `!use [card_name]` during critical moments!
    """)

@bot.command()
async def use(ctx, *, card_name: str):
    """Use an unlocked card"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    user_cards = unlocked_cards.get(ctx.author.id, [])
    card_name = card_name.lower().replace(' ', '_')
    
    if card_name not in user_cards:
        await ctx.send("You haven't unlocked that card! Use `!cards` to see your available cards.")
        return
    
    # Apply card effects
    if card_name == 'lightning_strike':
        # This would need to be used in context of a battle
        await ctx.send("⚡ **Lightning Strike Activated!** ⚡\nYour next attack will deal double damage!")
        # You'd need to track this for the next battle
    
    elif card_name == 'fortify':
        border_strength = 100  # Max border strength
        if ctx.author.id not in borders:
            borders[ctx.author.id] = {'strength': 0, 'soldiers_assigned': 0}
        borders[ctx.author.id]['strength'] = border_strength
        await ctx.send("🛡️ **Fortify Activated!** 🛡️\nYour borders are instantly reinforced to maximum strength!")
    
    elif card_name == 'espionage':
        # Steal from random player
        potential_targets = [pid for pid in players if pid != ctx.author.id and players[pid].started]
        if potential_targets:
            target_id = random.choice(potential_targets)
            target_player = players[target_id]
            stolen_gold = min(200, target_player.resources['gold'] // 5)
            target_player.resources['gold'] -= stolen_gold
            player.resources['gold'] += stolen_gold
            await ctx.send(f"💰 **Espionage Activated!** 💰\nStole {stolen_gold} gold from an unsuspecting civilization!")
    
    elif card_name == 'rebellion':
        # Cause rebellion in random enemy
        potential_targets = [pid for pid in players if pid != ctx.author.id and players[pid].started]
        if potential_targets:
            target_id = random.choice(potential_targets)
            target_player = players[target_id]
            soldier_loss = max(1, target_player.military['soldiers'] // 3)
            target_player.military['soldiers'] -= soldier_loss
            await ctx.send(f"🔥 **Rebellion Activated!** 🔥\nCaused a rebellion in enemy lands! They lost {soldier_loss} soldiers!")
    
    elif card_name == 'harvest':
        food_gain = 500
        player.resources['food'] += food_gain
        await ctx.send(f"🌾 **Bountiful Harvest Activated!** 🌾\nGained {food_gain} food from miraculous harvest!")
    
    elif card_name == 'gold_rush':
        gold_gain = 1000
        player.resources['gold'] += gold_gain
        await ctx.send(f"💎 **Gold Rush Activated!** 💎\nStruck gold! Gained {gold_gain} gold!")
    
    elif card_name == 'propaganda':
        happiness_boost = 50
        player.population['happiness'] = min(100, player.population['happiness'] + happiness_boost)
        await ctx.send(f"📢 **Propaganda Activated!** 📢\nYour people are inspired! Happiness increased by {happiness_boost}!")
    
    elif card_name == 'blitzkrieg':
        # This would need battle context
        await ctx.send("⚡ **Blitzkrieg Activated!** ⚡\nYour next attack will be devastating but costly!")
    
    # Remove used card
    user_cards.remove(card_name)
    unlocked_cards[ctx.author.id] = user_cards

@bot.command()
async def peace(ctx, member: discord.Member):
    """Offer peace to enemy"""
    player = get_player(ctx.author.id)
    target_player = get_player(member.id)
    
    if not check_civilization_ready(ctx, player) or not check_civilization_ready(ctx, target_player):
        return
    
    war_key = tuple(sorted([ctx.author.id, member.id]))
    
    if war_key not in wars:
        await ctx.send("You are not at war with this civilization!")
        return
    
    # Create peace offer
    peace_offers[member.id] = peace_offers.get(member.id, []) + [ctx.author.id]
    
    await ctx.send(f"""
🕊️ **PEACE OFFERED** 🕊️

**{ctx.author.display_name}** has offered peace to **{member.display_name}**!

{member.display_name}, use `!accept_peace @{ctx.author.name}` to end the war.
    """)

@bot.command()
async def accept_peace(ctx, member: discord.Member):
    """Accept peace offer"""
    player = get_player(ctx.author.id)
    target_player = get_player(member.id)
    
    if not check_civilization_ready(ctx, player) or not check_civilization_ready(ctx, target_player):
        return
    
    war_key = tuple(sorted([ctx.author.id, member.id]))
    
    if war_key not in wars:
        await ctx.send("You are not at war with this civilization!")
        return
    
    # Check if peace was offered
    if ctx.author.id not in peace_offers.get(member.id, []):
        await ctx.send("This civilization hasn't offered you peace!")
        return
    
    # End the war
    del wars[war_key]
    peace_offers[member.id].remove(ctx.author.id)
    
    await ctx.send(f"""
🎉 **PEACE TREATY SIGNED!** 🎉

**{ctx.author.display_name}** and **{member.display_name}** have ended their war!

May this peace last for generations to come...
    """)

# ============ BORDER MANAGEMENT COMMANDS ============

@bot.command()
async def addborder(ctx, soldiers: int):
    """Build defensive border with soldiers"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if soldiers > player.military['soldiers']:
        await ctx.send("You don't have that many soldiers to assign to borders!")
        return
    
    if soldiers < 5:
        await ctx.send("You need at least 5 soldiers to build a meaningful border defense!")
        return
    
    if ctx.author.id not in borders:
        borders[ctx.author.id] = {'strength': 0, 'soldiers_assigned': 0}
    
    borders[ctx.author.id]['soldiers_assigned'] += soldiers
    borders[ctx.author.id]['strength'] += soldiers * 2  # Each soldier adds 2 strength
    player.military['soldiers'] -= soldiers
    
    await ctx.send(f"""
🛡️ **BORDER FORTIFIED** 🛡️

Assigned {soldiers} soldiers to border defense!
Border strength: {borders[ctx.author.id]['strength']}
Total soldiers on border: {borders[ctx.author.id]['soldiers_assigned']}

Your borders are now more secure against enemy attacks!
    """)

@bot.command()
async def removeborder(ctx):
    """Remove border and retrieve soldiers"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if ctx.author.id not in borders or borders[ctx.author.id]['soldiers_assigned'] == 0:
        await ctx.send("You don't have any soldiers assigned to borders!")
        return
    
    retrieved_soldiers = borders[ctx.author.id]['soldiers_assigned']
    player.military['soldiers'] += retrieved_soldiers
    
    await ctx.send(f"""
↩️ **BORDER DISMANTLED** ↩️

Retrieved {retrieved_soldiers} soldiers from border defense!

Your army grows stronger, but your borders are now vulnerable...
    """)
    
    # Remove border
    del borders[ctx.author.id]

@bot.command()
async def rectract(ctx, percentage: int):
    """Assign percentage of soldiers to border"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if percentage < 1 or percentage > 100:
        await ctx.send("Percentage must be between 1 and 100!")
        return
    
    soldiers_to_assign = max(1, player.military['soldiers'] * percentage // 100)
    
    if ctx.author.id not in borders:
        borders[ctx.author.id] = {'strength': 0, 'soldiers_assigned': 0}
    
    borders[ctx.author.id]['soldiers_assigned'] += soldiers_to_assign
    borders[ctx.author.id]['strength'] += soldiers_to_assign * 2
    player.military['soldiers'] -= soldiers_to_assign
    
    await ctx.send(f"""
🛡️ **BORDER REINFORCED** 🛡️

Assigned {soldiers_to_assign} soldiers ({percentage}% of army) to borders!
Border strength: {borders[ctx.author.id]['strength']}

Strategic deployment complete!
    """)

@bot.command()
async def retrieve(ctx, percentage: int):
    """Retrieve percentage of soldiers from border"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if ctx.author.id not in borders or borders[ctx.author.id]['soldiers_assigned'] == 0:
        await ctx.send("You don't have any soldiers on border duty!")
        return
    
    if percentage < 1 or percentage > 100:
        await ctx.send("Percentage must be between 1 and 100!")
        return
    
    soldiers_to_retrieve = max(1, borders[ctx.author.id]['soldiers_assigned'] * percentage // 100)
    
    borders[ctx.author.id]['soldiers_assigned'] -= soldiers_to_retrieve
    borders[ctx.author.id]['strength'] = max(0, borders[ctx.author.id]['strength'] - soldiers_to_retrieve * 2)
    player.military['soldiers'] += soldiers_to_retrieve
    
    await ctx.send(f"""
↩️ **SOLDIERS RETRIEVED** ↩️

Retrieved {soldiers_to_retrieve} soldiers ({percentage}%) from borders!
Remaining border strength: {borders[ctx.author.id]['strength']}

Your offensive capability increases, but defense weakens...
    """)

@bot.command()
async def borderinfo(ctx):
    """Check border status"""
    player = get_player(ctx.author.id)
    
    if not check_civilization_ready(ctx, player):
        return
    
    if ctx.author.id not in borders or borders[ctx.author.id]['soldiers_assigned'] == 0:
        await ctx.send("You have no active border defenses. Use `!addborder` to build defenses!")
        return
    
    border_data = borders[ctx.author.id]
    
    await ctx.send(f"""
🛡️ **BORDER DEFENSE STATUS** 🛡️

**Soldiers on Border:** {border_data['soldiers_assigned']}
**Border Strength:** {border_data['strength']}
**Defense Bonus:** +{border_data['strength']} to defensive power

**Border provides:**
• Protection against enemy attacks
• Reduced casualties in defense
• Deterrent against invasion

Use `!rectract` and `!retrieve` to manage border troops strategically.
    """)

# ============ HELPER FUNCTIONS ============

def check_civilization_ready(ctx, player):
    """Check if player has started civilization and chosen ideology"""
    if not player.started:
        asyncio.create_task(ctx.send("You need to start your civilization first with `!start`"))
        return False
    if not player.ideology:
        asyncio.create_task(ctx.send("You need to choose your ideology with `!ideology`"))
        return False
    return True

def unlock_random_card(user_id):
    """Unlock a random card for the user"""
    if user_id not in unlocked_cards:
        unlocked_cards[user_id] = []
    
    available_cards = [card for card in CARDS.keys() if card not in unlocked_cards[user_id]]
    
    if available_cards:
        new_card = random.choice(available_cards)
        unlocked_cards[user_id].append(new_card)
        return new_card
    return None

# ============ BOT EVENTS ============

@bot.event
async def on_ready():
    print(f'💰 {bot.user} is online and ready for civilization building!')
    print(f'Bot is in {len(bot.guilds)} servers')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Command not found! Use `!warhelp` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Missing required arguments! Check `!warhelp` for command usage.")
    else:
        await ctx.send(f"An error occurred: {str(error)}")
        print(f"Error: {error}")

# ============ RUN BOT ============

if __name__ == "__main__":
    bot.run(os.getenv('BOT_TOKEN'))
