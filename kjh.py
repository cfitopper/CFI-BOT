import discord
import random
from discord.ext import commands
from discord import app_commands
import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# ─────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ROLES = ["Admin", "CFI - Dev", "BOSS", "Head-moderator (crew)"]
ANNOUNCEMENT_CHANNEL_ID = 0
# ─────────────────────────────────────────

GOLDEN_BOOT_TIERS = [
    "Cosmic", "Universal", "Galaxy", "Global", "International",
    "Elite 1", "Elite 2", "Elite 3"
]

TIERS = [
    "Cosmic", "Universal", "Galaxy",
    "Global", "International",
    "Elite 1", "Elite 2", "Elite 3",
    "Gold 1", "Gold 2", "Gold 3",
    "Silver 1", "Silver 2", "Silver 3",
    "Bronze"
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────
def get_db():
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"), cursor_factory=RealDictCursor)
    return conn

def setup_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            name TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            goals INTEGER DEFAULT 0,
            goals_against INTEGER DEFAULT 0,
            rank_in_tier INTEGER DEFAULT 0,
            round_wins INTEGER DEFAULT 0,
            round_losses INTEGER DEFAULT 0,
            round_done INTEGER DEFAULT 0,
            licensed TEXT DEFAULT 'No',
            playstyle TEXT DEFAULT 'Balanced',
            golden_boot_goals INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS overview_ranking (
            position INTEGER PRIMARY KEY,
            player_id TEXT NOT NULL,
            tier TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            player1 TEXT,
            player2 TEXT,
            score1 INTEGER,
            score2 INTEGER,
            date TEXT,
            tier TEXT
        )
    """)
    # Migration: add tier column if not exists
    try:
        c.execute("ALTER TABLE matches ADD COLUMN tier TEXT")
        conn.commit()
    except Exception:
        conn.rollback()
    # Clean up all name formats to raw numeric ID
    try:
        c.execute("SELECT name FROM players")
        all_names = c.fetchall()
        for row in all_names:
            raw = row["name"]
            clean = raw.strip("<@>").strip()
            if clean != raw:
                c.execute("UPDATE players SET name = %s WHERE name = %s", (clean, raw))
        conn.commit()
    except Exception as e:
        print(f"Migration cleanup error: {e}")
        conn.rollback()

    # Add pending column if it doesn't exist yet
    try:
        c.execute("ALTER TABLE players ADD COLUMN pending INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        c.execute("ALTER TABLE players ADD COLUMN golden_boot_goals INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback()

    # Add new columns if they don't exist yet (migration)
    try:
        c.execute("ALTER TABLE players ADD COLUMN licensed TEXT DEFAULT 'No'")
        conn.commit()
    except Exception:
        conn.rollback()
    try:
        c.execute("ALTER TABLE players ADD COLUMN playstyle TEXT DEFAULT 'Balanced'")
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def is_admin():
    async def predicate(interaction: discord.Interaction):
        user_roles = [role.name.strip() for role in interaction.user.roles]
        if not any(r in user_roles for r in ADMIN_ROLES):
            await interaction.response.send_message("❌ You don't have admin permissions!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

def is_cfi_dev():
    async def predicate(interaction: discord.Interaction):
        user_roles = [role.name.strip() for role in interaction.user.roles]
        if "CFI - Dev" not in user_roles:
            await interaction.response.send_message("❌ Only CFI Dev can use this command!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

BRACKET_ROLES = ["Admin", "CFI - Dev", "BOSS", "Head-moderator (crew)", "League Moderator (crew)"]

def can_bracket():
    async def predicate(interaction: discord.Interaction):
        user_roles = [role.name.strip() for role in interaction.user.roles]
        if not any(r in user_roles for r in BRACKET_ROLES):
            await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

SCORE_ROLES = ["Admin", "CFI - Dev", "BOSS", "Head-moderator (crew)", "Moderator (crew)", "League Moderator (crew)"]

def can_score():
    async def predicate(interaction: discord.Interaction):
        user_roles = [role.name.strip() for role in interaction.user.roles]
        if not any(r in user_roles for r in SCORE_ROLES):
            await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

def get_player(name: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE name = %s", (name,))
    p = c.fetchone()
    conn.close()
    return dict(p) if p else None

def tier_index(tier: str):
    try:
        return TIERS.index(tier)
    except ValueError:
        return -1

def get_tier_players(tier: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE tier = %s AND (pending IS NULL OR pending = 0) ORDER BY rank_in_tier ASC", (tier,))
    players = c.fetchall()
    conn.close()
    return [dict(p) for p in players]

def update_ranks_in_tier(tier: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, wins, losses FROM players WHERE tier = %s", (tier,))
    players = [dict(p) for p in c.fetchall()]

    def score(p):
        total = p["wins"] + p["losses"]
        return p["wins"] / total if total > 0 else 0

    sorted_players = sorted(players, key=score, reverse=True)
    for i, p in enumerate(sorted_players):
        c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, p["name"]))
    conn.commit()
    conn.close()

def get_valid_matchups(tier: str):
    conn = get_db()
    c = conn.cursor()
    # Exclude pending and done players
    c.execute("SELECT * FROM players WHERE tier = %s AND round_done = 0 AND (pending IS NULL OR pending = 0) ORDER BY rank_in_tier ASC", (tier,))
    players = [dict(p) for p in c.fetchall()]
    conn.close()

    if len(players) < 2:
        return []

    # Sort by rank_in_tier so position 0=rank1, 1=rank2, 2=rank3, 3=rank4
    players = sorted(players, key=lambda p: p["rank_in_tier"])

    matchups = []
    paired = set()

    # Fixed pairings by position: position 0 vs 2 (rank1 vs rank3) and position 1 vs 3 (rank2 vs rank4)
    fixed_pairs = [(0, 2), (1, 3)]
    for i, j in fixed_pairs:
        if i < len(players) and j < len(players):
            p1 = players[i]
            p2 = players[j]
            key1 = (p1["round_wins"], p1["round_losses"])
            key2 = (p2["round_wins"], p2["round_losses"])
            if key1 == key2 and p1["name"] not in paired and p2["name"] not in paired:
                matchups.append((p1["name"], p2["name"], key1))
                paired.add(p1["name"])
                paired.add(p2["name"])

    if matchups:
        return matchups

    # Round 2 logic based on records
    # Winners final: both rank1 and rank3 won (1W/0L) → rank1 vs rank2... 
    # Actually: after round 1, winners play each other and losers play each other
    # Group remaining active players by record
    remaining = [p for p in players if p["name"] not in paired]
    groups = {}
    for p in remaining:
        key = (p["round_wins"], p["round_losses"])
        if key not in groups:
            groups[key] = []
        groups[key].append(p["name"])

    for key, names in groups.items():
        if len(names) >= 2:
            # Sort by rank so highest ranked plays first
            names_sorted = sorted(names, key=lambda n: next(p["rank_in_tier"] for p in players if p["name"] == n))
            matchups.append((names_sorted[0], names_sorted[1], key))

    return matchups


async def get_display_name(guild: discord.Guild, uid: str) -> str:
    # Strip any <@> formatting to get the raw ID
    clean = uid.strip("<@>").strip()
    try:
        member = guild.get_member(int(clean))
        if member:
            return member.display_name
        member = await guild.fetch_member(int(clean))
        if member:
            return member.display_name
    except Exception:
        pass
    return f"<@{clean}>"

def get_uid(raw: str) -> str:
    """Always return a clean numeric ID from whatever is stored."""
    return raw.strip("<@>").strip()

async def send_announcement(message: str):
    if ANNOUNCEMENT_CHANNEL_ID and ANNOUNCEMENT_CHANNEL_ID != 0:
        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            await channel.send(message)

# ─────────────────────────────────────────
# SLASH COMMANDS
# ─────────────────────────────────────────


PLAYSTYLES = ["Super Defensive", "Defensive", "Controlling", "Balanced", "Offensive", "Very Offensive"]

async def licensed_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=l, value=l)
        for l in ["Yes", "No"] if current.lower() in l.lower()
    ]

async def playstyle_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=p, value=p)
        for p in PLAYSTYLES if current.lower() in p.lower()
    ]

async def tier_autocomplete(interaction: discord.Interaction, current: str):
    try:
        return [
            app_commands.Choice(name=tier, value=tier)
            for tier in TIERS if current.lower() in tier.lower()
        ]
    except Exception:
        return []

async def player_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM players ORDER BY tier, rank_in_tier")
    players = [dict(p) for p in c.fetchall()]
    conn.close()
    results = []
    for p in players:
        uid = get_uid(p["name"])
        member = interaction.guild.get_member(int(uid))
        display = member.display_name if member else uid
        if current.lower() in display.lower():
            results.append(app_commands.Choice(name=display, value=p["name"]))
    return results[:25]

@tree.command(name="addplayer", description="Add a player to a tier (admin only)")
@is_admin()
@app_commands.describe(
    player="Select a Discord user",
    tier="Select a tier",
    rank="Rank in tier 1-4 (optional)",
    wins="Starting wins (optional)",
    losses="Starting losses (optional)",
    goals="Starting goals (optional)",
    licensed="Is the player licensed? Yes or No",
    playstyle="Player playstyle"
)
@app_commands.autocomplete(tier=tier_autocomplete, licensed=licensed_autocomplete, playstyle=playstyle_autocomplete)
async def addplayer(interaction: discord.Interaction, player: discord.Member, tier: str,
                    rank: int = None, wins: int = None, losses: int = None, goals: int = None,
                    licensed: str = None, playstyle: str = None):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
        return

    players_in_tier = get_tier_players(tier)
    if len(players_in_tier) >= 4:
        await interaction.response.send_message(f"❌ **{tier}** is full! (max 4 players)", ephemeral=True)
        return

    name = str(player.id)
    display = player.display_name

    if get_player(name):
        await interaction.response.send_message(f"❌ **{display}** already exists!", ephemeral=True)
        return

    if rank is None:
        rank = len(players_in_tier) + 1

    if rank < 1 or rank > 4:
        await interaction.response.send_message("❌ Rank must be between 1 and 4!", ephemeral=True)
        return

    w = wins if wins is not None else 0
    l = losses if losses is not None else 0
    g = goals if goals is not None else 0
    lic = licensed if licensed is not None else "No"
    ps = playstyle if playstyle is not None else "Balanced"

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO players (name, tier, rank_in_tier, wins, losses, goals, licensed, playstyle) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (name, tier, rank, w, l, g, lic, ps)
    )
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ **{display}** added to **{tier}** as rank {rank}!")

@tree.command(name="removeplayer", description="Remove a player (admin only)")
@is_admin()
@app_commands.describe(player="Select a Discord user")
async def removeplayer(interaction: discord.Interaction, player: discord.Member):
    name = str(player.id)
    display = player.display_name
    p = get_player(name)
    if not p:
        await interaction.response.send_message(f"❌ **{display}** not found!", ephemeral=True)
        return
    player_tier = p["tier"]
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM players WHERE name = %s", (name,))
    # Fix ranks in the tier after removal
    c.execute("SELECT * FROM players WHERE tier = %s ORDER BY rank_in_tier ASC", (player_tier,))
    remaining = [dict(p) for p in c.fetchall()]
    for i, rp in enumerate(remaining):
        c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, rp["name"]))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"🗑️ **{display}** removed.")

@tree.command(name="score", description="Submit a match score (admin only)")
@can_score()
@app_commands.describe(
    player1="Select player 1",
    goals1="Goals scored by player 1",
    player2="Select player 2",
    goals2="Goals scored by player 2"
)
async def score(interaction: discord.Interaction, player1: discord.Member, goals1: int, player2: discord.Member, goals2: int):
    await interaction.response.defer()

    name1 = str(player1.id)
    name2 = str(player2.id)

    p1 = get_player(name1)
    p2 = get_player(name2)

    if not p1:
        await interaction.followup.send(f"❌ {player1.display_name} not found!")
        return
    if not p2:
        await interaction.followup.send(f"❌ {player2.display_name} not found!")
        return
    if goals1 == goals2:
        await interaction.followup.send("❌ Draws are not allowed!")
        return

    if (p1["round_wins"], p1["round_losses"]) != (p2["round_wins"], p2["round_losses"]):
        await interaction.followup.send(
            f"❌ {player1.display_name} ({p1['round_wins']}W/{p1['round_losses']}L) and {player2.display_name} ({p2['round_wins']}W/{p2['round_losses']}L) don't have the same round record and can't face each other yet!"
        )
        return

    if p1["round_done"] or p2["round_done"]:
        await interaction.followup.send("❌ One of these players is already done with this round!")
        return

    winner_name = name1 if goals1 > goals2 else name2
    loser_name = name2 if goals1 > goals2 else name1
    winner_goals = max(goals1, goals2)
    loser_goals = min(goals1, goals2)

    conn = get_db()
    c = conn.cursor()
    match_tier = p1["tier"]
    c.execute(
        "INSERT INTO matches (player1, player2, score1, score2, date, tier) VALUES (%s, %s, %s, %s, %s, %s)",
        (name1, name2, goals1, goals2, datetime.now().isoformat(), match_tier)
    )

    # Check if tier counts for golden boot
    c.execute("SELECT tier FROM players WHERE name = %s", (winner_name,))
    row = c.fetchone()
    in_golden_boot_tier = row["tier"] in GOLDEN_BOOT_TIERS if row else False

    if in_golden_boot_tier:
        c.execute("""
            UPDATE players SET wins = wins + 1, goals = goals + %s, goals_against = goals_against + %s,
            golden_boot_goals = golden_boot_goals + %s,
            round_wins = round_wins + 1 WHERE name = %s
        """, (winner_goals, loser_goals, winner_goals, winner_name))
        c.execute("""
            UPDATE players SET losses = losses + 1, goals = goals + %s, goals_against = goals_against + %s,
            golden_boot_goals = golden_boot_goals + %s,
            round_losses = round_losses + 1 WHERE name = %s
        """, (loser_goals, winner_goals, loser_goals, loser_name))
    else:
        c.execute("""
            UPDATE players SET wins = wins + 1, goals = goals + %s, goals_against = goals_against + %s,
            round_wins = round_wins + 1 WHERE name = %s
        """, (winner_goals, loser_goals, winner_name))
        c.execute("""
            UPDATE players SET losses = losses + 1, goals = goals + %s, goals_against = goals_against + %s,
            round_losses = round_losses + 1 WHERE name = %s
        """, (loser_goals, winner_goals, loser_name))

    conn.commit()

    c.execute("SELECT * FROM players WHERE name = %s", (winner_name,))
    winner = dict(c.fetchone())
    c.execute("SELECT * FROM players WHERE name = %s", (loser_name,))
    loser = dict(c.fetchone())

    promo_msg = ""
    demo_msg = ""

    if winner["round_wins"] >= 2:
        c.execute("UPDATE players SET round_done = 1 WHERE name = %s", (winner_name,))
        promo_msg = f"\n🎉 <@{get_uid(winner_name)}> has 2 wins — **PROMOTION** incoming!"

    if loser["round_losses"] >= 2:
        c.execute("UPDATE players SET round_done = 1 WHERE name = %s", (loser_name,))
        demo_msg = f"\n📉 <@{get_uid(loser_name)}> has 2 losses — **DEMOTION** incoming!"

    conn.commit()
    conn.close()

    msg = f"⚽ **Match Result**\n"
    msg += f"🏆 <@{get_uid(winner_name)}> {winner_goals} - {loser_goals} <@{get_uid(loser_name)}>\n"
    msg += f"\n📊 **Round Standings — {p1['tier']}:**\n"

    tier_players = get_tier_players(p1["tier"])
    for p in tier_players:
        status = "✅ Done" if p["round_done"] else "🎮 Active"
        msg += f"• <@{get_uid(p['name'])}>: {p['round_wins']}W / {p['round_losses']}L — {status}\n"

    msg += promo_msg
    msg += demo_msg

    matchups = get_valid_matchups(p1["tier"])
    if matchups:
        msg += f"\n⚔️ **Next valid matchup(s):**\n"
        for m in matchups:
            msg += f"• <@{get_uid(m[0])}> vs <@{get_uid(m[1])}> ({m[2][0]}W/{m[2][1]}L each)\n"

    await interaction.followup.send(msg, allowed_mentions=discord.AllowedMentions(users=True))


@tree.command(name="unscore", description="Undo the last match between two players (admin only)")
@can_score()
@app_commands.describe(
    player1="First player",
    player2="Second player"
)
async def unscore(interaction: discord.Interaction, player1: discord.Member, player2: discord.Member):
    await interaction.response.defer()

    name1 = str(player1.id)
    name2 = str(player2.id)

    conn = get_db()
    c = conn.cursor()

    # Find the last match between these two players
    c.execute("""
        SELECT * FROM matches
        WHERE (player1 = %s AND player2 = %s) OR (player1 = %s AND player2 = %s)
        ORDER BY id DESC LIMIT 1
    """, (name1, name2, name2, name1))
    match = c.fetchone()

    if not match:
        await interaction.followup.send(f"❌ No match found between {player1.display_name} and {player2.display_name}!")
        conn.close()
        return

    match = dict(match)
    # Figure out winner from scores
    if match["score1"] > match["score2"]:
        winner = match["player1"]
        loser = match["player2"]
        goals_winner = match["score1"]
        goals_loser = match["score2"]
    else:
        winner = match["player2"]
        loser = match["player1"]
        goals_winner = match["score2"]
        goals_loser = match["score1"]

    # Reverse stats for winner
    c.execute("""
        UPDATE players SET
            wins = GREATEST(wins - 1, 0),
            goals = GREATEST(goals - %s, 0),
            goals_against = GREATEST(goals_against - %s, 0),
            round_wins = GREATEST(round_wins - 1, 0),
            round_done = 0
        WHERE name = %s
    """, (goals_winner, goals_loser, winner))

    # Reverse stats for loser
    c.execute("""
        UPDATE players SET
            losses = GREATEST(losses - 1, 0),
            goals = GREATEST(goals - %s, 0),
            goals_against = GREATEST(goals_against - %s, 0),
            round_losses = GREATEST(round_losses - 1, 0),
            round_done = 0
        WHERE name = %s
    """, (goals_loser, goals_winner, loser))

    # Delete the match record
    c.execute("DELETE FROM matches WHERE id = %s", (match["id"],))

    conn.commit()
    conn.close()

    winner_display = player1.display_name if winner == name1 else player2.display_name
    loser_display = player2.display_name if winner == name1 else player1.display_name

    await interaction.followup.send(
        f"↩️ Match undone between {player1.display_name} and {player2.display_name}!\n"
        f"Stats reversed for both players."
    )

@tree.command(name="updatetier", description="Process promos and demos for a tier (admin only)")
@is_admin()
@app_commands.describe(tier="Select a tier", remove_losers="Remove losers instead of demoting them")
@app_commands.autocomplete(tier=tier_autocomplete)
async def updatetier(interaction: discord.Interaction, tier: str, remove_losers: bool = False):
    await interaction.response.defer()

    tier = tier.title()
    if tier not in TIERS:
        await interaction.followup.send("❌ Invalid tier!")
        return

    players = get_tier_players(tier)
    if not players:
        await interaction.followup.send(f"❌ No players found in **{tier}**!")
        return

    results = []
    conn = get_db()
    c = conn.cursor()

    promo_list = []
    demo_list = []
    removed_list = []

    for p in players:
        name = p["name"]
        rw = p["round_wins"]
        rl = p["round_losses"]

        if rw >= 2:
            current_idx = tier_index(p["tier"])
            if current_idx > 0:
                new_tier = TIERS[current_idx - 1]
                c.execute(
                    "UPDATE players SET tier = %s, pending = 1 WHERE name = %s",
                    (new_tier, name)
                )
                promo_list.append((name, new_tier))
                results.append(f"🎉 {get_display(interaction.guild, get_uid(name))} → **{new_tier}** (pending)")
            else:
                results.append(f"🏅 {get_display(interaction.guild, get_uid(name))} is already in the highest tier!")
        elif rl >= 2:
            if remove_losers:
                c.execute("DELETE FROM players WHERE name = %s", (name,))
                removed_list.append(name)
                results.append(f"🚫 {get_display(interaction.guild, get_uid(name))} removed from the competition")
            else:
                current_idx = tier_index(p["tier"])
                if current_idx < len(TIERS) - 1:
                    new_tier = TIERS[current_idx + 1]
                    c.execute(
                        "UPDATE players SET tier = %s, pending = 1 WHERE name = %s",
                        (new_tier, name)
                    )
                    demo_list.append((name, new_tier))
                    results.append(f"📉 {get_display(interaction.guild, get_uid(name))} → **{new_tier}** (pending)")
                else:
                    c.execute("DELETE FROM players WHERE name = %s", (name,))
                    removed_list.append(name)
                    results.append(f"🚫 {get_display(interaction.guild, get_uid(name))} removed from the system (bottom of Bronze)")
        else:
            results.append(f"➡️ {get_display(interaction.guild, get_uid(name))}: {rw}W / {rl}L — no change")

    # Fix ranks in affected tiers (excluding removed players)
    affected_tiers = set([tier] + [t for _, t in promo_list] + [t for _, t in demo_list])
    for t in affected_tiers:
        c.execute("SELECT * FROM players WHERE tier = %s ORDER BY rank_in_tier ASC", (t,))
        tier_players = [dict(p) for p in c.fetchall()]
        promoted_into_names = [name for name, nt in promo_list if nt == t]
        demoted_into_names = [name for name, nt in demo_list if nt == t]
        stayers = [p["name"] for p in tier_players if p["name"] not in promoted_into_names and p["name"] not in demoted_into_names]
        # Sort promoted players: best record first (most wins then fewest losses)
        promoted_players = [p for p in players if p["name"] in promoted_into_names]
        promoted_players.sort(key=lambda x: (-x["round_wins"], x["round_losses"]))
        promoted_sorted = [p["name"] for p in promoted_players]
        # Sort demoted players: worst record last
        demoted_players = [p for p in players if p["name"] in demoted_into_names]
        demoted_players.sort(key=lambda x: (-x["round_wins"], x["round_losses"]))
        demoted_sorted = [p["name"] for p in demoted_players]
        ordered = demoted_sorted + stayers + promoted_sorted
        for i, name in enumerate(ordered):
            c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, name))

    # After removal cascade ranks down through all tiers below
    if removed_list:
        tier_idx = tier_index(tier)
        for t_idx in range(tier_idx, len(TIERS)):
            t = TIERS[t_idx]
            c.execute("SELECT * FROM players WHERE tier = %s ORDER BY rank_in_tier ASC", (t,))
            t_players = [dict(p) for p in c.fetchall()]
            for i, p in enumerate(t_players):
                c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, p["name"]))

    conn.commit()
    conn.close()

    embed = discord.Embed(title=f"🔄 Tier Update — {tier}", color=0xff9900)
    embed.description = "\n".join(results)
    embed.set_footer(text="Moved players are pending. Use /updateall to start the new round.")

    await interaction.followup.send(embed=embed)
    await send_announcement(embed.description)

@tree.command(name="bracket", description="View the current round bracket for a tier")
@can_bracket()
@app_commands.describe(tier="Select a tier")
@app_commands.autocomplete(tier=tier_autocomplete)
async def bracket(interaction: discord.Interaction, tier: str):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
        return

    players = get_tier_players(tier)
    if not players:
        await interaction.response.send_message(f"**{tier}** is empty.")
        return

    embed = discord.Embed(title=f"⚔️ Round Bracket — {tier}", color=0xff4444)

    lines = []
    for p in players:
        if p["round_done"]:
            if p["round_wins"] >= 2:
                status = "✅ PROMO (2W)"
            else:
                status = "❌ DEMO (2L)"
        else:
            status = f"🎮 {p['round_wins']}W / {p['round_losses']}L"
        member = interaction.guild.get_member(int(get_uid(p["name"])))
        name_str = member.display_name if member else get_uid(p["name"])
        lines.append(f"{name_str} — {status}")

    embed.description = "\n".join(lines)

    matchups = get_valid_matchups(tier)
    if matchups:
        def get_name(uid):
            m = interaction.guild.get_member(int(get_uid(uid)))
            return m.display_name if m else get_uid(uid)
        next_matches = "\n".join([f"• {get_name(m[0])} vs {get_name(m[1])}" for m in matchups])
        embed.add_field(name="⚔️ Next Matchup(s)", value=next_matches, inline=False)
    else:
        active = [p for p in players if not p["round_done"]]
        if not active:
            embed.add_field(name="✅ Round Complete!", value="All matches in this tier are done!", inline=False)
        else:
            embed.add_field(name="⏳ Waiting...", value="Not enough players with the same record to make a match yet.", inline=False)

    embed.set_footer(text="2 wins = Promo | 2 losses = Demo")
    await interaction.response.send_message(embed=embed)

@tree.command(name="tier", description="View all players in a tier")
@is_admin()
@app_commands.describe(tier="Select a tier")
@app_commands.autocomplete(tier=tier_autocomplete)
async def view_tier(interaction: discord.Interaction, tier: str):
    tier = tier.title()
    if tier not in TIERS:
        await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
        return

    players = get_tier_players(tier)
    if not players:
        await interaction.response.send_message(f"**{tier}** is empty.")
        return

    embed = discord.Embed(title=f"🏅 {tier}", color=0x00aaff)
    lines_list = []
    for p in players:
        member = interaction.guild.get_member(int(get_uid(p["name"])))
        name_str = member.display_name if member else get_uid(p["name"])
        lines_list.append(f"{p['rank_in_tier']}. {name_str}")
    lines = chr(10).join(lines_list)
    embed.description = lines
    await interaction.response.send_message(embed=embed)

@tree.command(name="profile", description="View a player's profile")
@app_commands.describe(player="Select a player")
async def profile(interaction: discord.Interaction, player: discord.Member):
    uid = str(player.id)
    display_name = player.display_name
    p = get_player(uid)
    if not p:
        await interaction.response.send_message(f"❌ **{display_name}** not found!", ephemeral=True)
        return

    await interaction.response.defer()

    total = p["wins"] + p["losses"]
    winrate = round((p["wins"] / total * 100)) if total > 0 else 0

    # Calculate global rank in one query
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, tier, rank_in_tier FROM players ORDER BY rank_in_tier ASC")
    all_p = [dict(r) for r in c.fetchall()]
    conn.close()

    global_rank = 1
    for tier in TIERS:
        for row in [x for x in all_p if x["tier"] == tier]:
            if row["name"] == uid:
                break
            global_rank += 1
        else:
            continue
        break

    embed = discord.Embed(title=f"⚽ {display_name}", color=0xffaa00)
    embed.set_thumbnail(url=player.display_avatar.url)
    licensed = p.get("licensed", "No")
    playstyle = p.get("playstyle", "Balanced")
    embed.description = (
        f"**Tier:** {p['tier']}\n"
        f"**Global Rank:** #{global_rank}\n"
        f"**Wins:** {p['wins']}\n"
        f"**Losses:** {p['losses']}\n"
        f"**Goals Scored:** {p['goals']}\n"
        f"**Winrate:** {winrate}%\n"
        f"**Matches Played:** {total}\n"
        f"**Licensed:** {licensed}\n"
        f"**Playstyle:** {playstyle}"
    )
    await interaction.followup.send(embed=embed)

@tree.command(name="alltiers", description="Overview of all tiers and their players")
@is_admin()
async def alltiers(interaction: discord.Interaction):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players ORDER BY rank_in_tier")
    all_players = [dict(p) for p in c.fetchall()]
    conn.close()

    if not all_players:
        await interaction.response.send_message("There are no players yet!")
        return

    embed = discord.Embed(title="🌍 CFI Ranking", color=0x00ff88)
    tier_data = {}
    for p in all_players:
        if p["tier"] not in tier_data:
            tier_data[p["tier"]] = []
        tier_data[p["tier"]].append(p)

    global_rank = 1
    for tier in TIERS:
        if tier in tier_data:
            lines = []
            for p in tier_data[tier]:
                total = p["wins"] + p["losses"]
                winrate = round((p["wins"] / total * 100)) if total > 0 else 0
                uid = get_uid(p["name"])
                lines.append(f"{global_rank}. <@{uid}>" + chr(10) + f"W: {p['wins']} | L: {p['losses']} | Goals: {p['goals']} | Winrate: {winrate}%")
                global_rank += 1
            embed.add_field(name="​", value=f"**{tier}**" + chr(10) + chr(10).join(lines), inline=False)

    await interaction.response.send_message(embed=embed)


@tree.command(name="updateall", description="Process all promos and demos for every tier at once (admin only)")
@is_cfi_dev()
async def updateall(interaction: discord.Interaction):
    await interaction.response.defer()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players")
    all_players = [dict(p) for p in c.fetchall()]
    conn.close()

    if not all_players:
        await interaction.followup.send("❌ No players found!")
        return

    # First collect all moves so we don't process cascading changes
    moves = {}
    for p in all_players:
        name = p["name"]
        rw = p["round_wins"]
        rl = p["round_losses"]
        current_idx = tier_index(p["tier"])

        if rw >= 2 and current_idx > 0:
            moves[name] = ("promo", TIERS[current_idx - 1])
        elif rl >= 2 and current_idx < len(TIERS) - 1:
            moves[name] = ("demo", TIERS[current_idx + 1])

    # Apply all moves at once
    conn = get_db()
    c = conn.cursor()

    promo_list = []
    demo_list = []
    none_list = []

    for p in all_players:
        name = p["name"]
        if name in moves:
            move_type, new_tier = moves[name]
            c.execute(
                "UPDATE players SET tier = %s, round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s",
                (new_tier, name)
            )
            if move_type == "promo":
                promo_list.append((name, new_tier))
            else:
                demo_list.append((name, new_tier))
        else:
            c.execute(
                "UPDATE players SET round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s",
                (name,)
            )
            none_list.append(f"➡️ {get_display(interaction.guild, get_uid(name))}")

    conn.commit()

    # Reset all round stats and clear pending for everyone
    c.execute("UPDATE players SET round_wins = 0, round_losses = 0, round_done = 0, pending = 0")
    conn.commit()

    # Save new ranking snapshot to overview_ranking
    c.execute("SELECT * FROM players ORDER BY rank_in_tier ASC")
    all_players_after = [dict(p) for p in c.fetchall()]
    c.execute("DELETE FROM overview_ranking")
    position = 1
    for tier in TIERS:
        for p in [x for x in all_players_after if x["tier"] == tier]:
            c.execute(
                "INSERT INTO overview_ranking (position, player_id, tier) VALUES (%s, %s, %s)",
                (position, get_uid(p["name"]), tier)
            )
            position += 1
    conn.commit()
    conn.close()

    def make_chunks(lines, max_len=1000):
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > max_len:
                chunks.append(current)
                current = line
            else:
                current += (chr(10) if current else "") + line
        if current:
            chunks.append(current)
        return chunks

    embed = discord.Embed(title="🔄 Full Ranking Update", color=0xff9900)

    if promo_list:
        chunks = make_chunks([f"🎉 {get_display(interaction.guild, get_uid(n))} → **{t}**" for n, t in promo_list])
        for i, chunk in enumerate(chunks):
            embed.add_field(name="🎉 Promotions" if i == 0 else "​", value=chunk, inline=False)
    if demo_list:
        chunks = make_chunks([f"📉 {get_display(interaction.guild, get_uid(n))} → **{t}**" for n, t in demo_list])
        for i, chunk in enumerate(chunks):
            embed.add_field(name="📉 Demotions" if i == 0 else "​", value=chunk, inline=False)
    if none_list:
        chunks = make_chunks(none_list)
        for i, chunk in enumerate(chunks):
            embed.add_field(name="➡️ No change" if i == 0 else "​", value=chunk, inline=False)

    embed.set_footer(text="All round stats reset. New round can begin!")
    await interaction.followup.send(embed=embed)



@tree.command(name="overview", description="CFI Ranking as it was after the last /updateall")
@is_cfi_dev()
async def overview(interaction: discord.Interaction):
    await interaction.response.defer()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM overview_ranking ORDER BY position ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        await interaction.followup.send("No overview available yet. Run /updateall first!")
        return

    # Get player stats from players table
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players")
    all_players = {p["name"]: dict(p) for p in c.fetchall()}
    conn.close()

    tier_data = {}
    for r in rows:
        t = r["tier"]
        if t not in tier_data:
            tier_data[t] = []
        tier_data[t].append(r["player_id"])

    embed = discord.Embed(title="🌍 CFI Ranking", color=0x00ff88)
    global_rank = 1
    for tier in TIERS:
        if tier in tier_data:
            lines = []
            for uid in tier_data[tier]:
                p = all_players.get(uid)
                if p:
                    total = p["wins"] + p["losses"]
                    winrate = round((p["wins"] / total * 100)) if total > 0 else 0
                    lines.append(f"{global_rank}. <@{uid}>" + chr(10) + f"W: {p['wins']} | L: {p['losses']} | Goals: {p['goals']} | Winrate: {winrate}%")
                else:
                    lines.append(f"{global_rank}. <@{uid}>")
                global_rank += 1

            # Split into chunks of max 1000 chars per field
            field_chunks = []
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 > 1000:
                    field_chunks.append(current)
                    current = line
                else:
                    current += (chr(10) if current else "") + line
            if current:
                field_chunks.append(current)

            for i, chunk in enumerate(field_chunks):
                embed.add_field(name="​" if i > 0 else "​", value=f"**{tier}**" + chr(10) + chunk if i == 0 else chunk, inline=False)

    await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))


@tree.command(name="goals", description="Top scorers leaderboard")
async def goals(interaction: discord.Interaction):
    await interaction.response.defer()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players ORDER BY goals DESC LIMIT 20")
    players = [dict(p) for p in c.fetchall()]
    conn.close()

    if not players:
        await interaction.followup.send("No players found!")
        return

    embed = discord.Embed(title="🥅 Top Scorers", color=0x00cc44)
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(players):
        uid = get_uid(p["name"])
        member = interaction.guild.get_member(int(uid))
        name_str = member.display_name if member else uid
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} {name_str} — {p['goals']} goals ({p['tier']})")
    embed.description = chr(10).join(lines)
    await interaction.followup.send(embed=embed)


@tree.command(name="setgoalsgoldenboot", description="Manually set golden boot goals for a player (admin only)")
@is_admin()
@app_commands.describe(player="Select a Discord user", goals="Number of golden boot goals")
async def setgoalsgoldenboot(interaction: discord.Interaction, player: discord.Member, goals: int):
    await interaction.response.defer()
    uid = str(player.id)
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE players SET golden_boot_goals = %s WHERE name = %s", (goals, uid))
    conn.commit()
    conn.close()
    name_display = get_display(interaction.guild, uid)
    await interaction.followup.send(f"✅ Golden Boot goals for **{name_display}** set to **{goals}**!")

@tree.command(name="goldenboot", description="Top 5 CFI Golden Boot scorers")
@is_admin()
async def goldenboot(interaction: discord.Interaction):
    await interaction.response.defer()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM players ORDER BY golden_boot_goals DESC LIMIT 10")
    players = [dict(p) for p in c.fetchall()]
    conn.close()

    if not players:
        await interaction.followup.send("No players found!")
        return

    medals = ["🥇", "🥈", "🥉"]
    embed = discord.Embed(title="🥅 CFI Golden Boot — Top 10", color=0xFFD700)
    lines = []
    for i, p in enumerate(players):
        uid = get_uid(p["name"])
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} <@{uid}> — {p['golden_boot_goals']} goals ({p['tier']})")
    embed.description = chr(10).join(lines)
    await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))

@tree.command(name="setstats", description="Manually update a player's stats (admin only)")
@is_admin()
@app_commands.describe(
    player="Select a player",
    wins="New win count",
    losses="New loss count",
    goals="New goals scored count",
    tier="New tier",
    rank="New rank in tier (1-4)",
    licensed="Is the player licensed? Yes or No",
    playstyle="Player playstyle",
    round_wins="New round wins count",
    round_losses="New round losses count"
)
@app_commands.autocomplete(tier=tier_autocomplete, licensed=licensed_autocomplete, playstyle=playstyle_autocomplete)
async def setstats(interaction: discord.Interaction, player: discord.Member,
                   wins: int = None, losses: int = None, goals: int = None,
                   tier: str = None, rank: int = None, licensed: str = None, playstyle: str = None,
                   round_wins: int = None, round_losses: int = None):
    uid = str(player.id)
    display = player.display_name
    p = get_player(uid)
    if not p:
        await interaction.response.send_message(f"❌ **{display}** not found!", ephemeral=True)
        return

    if tier is not None:
        tier = tier.title()
        if tier not in TIERS:
            await interaction.response.send_message("❌ Invalid tier!", ephemeral=True)
            return

    if rank is not None and (rank < 1 or rank > 4):
        await interaction.response.send_message("❌ Rank must be between 1 and 4!", ephemeral=True)
        return

    updates = []
    values = []

    if wins is not None:
        updates.append("wins = %s")
        values.append(wins)
    if losses is not None:
        updates.append("losses = %s")
        values.append(losses)
    if goals is not None:
        updates.append("goals = %s")
        values.append(goals)
    if tier is not None:
        updates.append("tier = %s")
        values.append(tier)
    if rank is not None:
        updates.append("rank_in_tier = %s")
        values.append(rank)
    if licensed is not None:
        updates.append("licensed = %s")
        values.append(licensed)
    if round_wins is not None:
        updates.append("round_wins = %s")
        values.append(round_wins)
        # Also update total wins by the difference
        old_round_wins = p["round_wins"] or 0
        diff_wins = round_wins - old_round_wins
        if diff_wins != 0:
            updates.append("wins = wins + %s")
            values.append(diff_wins)
    if round_losses is not None:
        updates.append("round_losses = %s")
        values.append(round_losses)
        # Also update total losses by the difference
        old_round_losses = p["round_losses"] or 0
        diff_losses = round_losses - old_round_losses
        if diff_losses != 0:
            updates.append("losses = losses + %s")
            values.append(diff_losses)
    if playstyle is not None:
        updates.append("playstyle = %s")
        values.append(playstyle)

    if not updates:
        await interaction.response.send_message("❌ You didn't change anything!", ephemeral=True)
        return

    values.append(uid)
    conn = get_db()
    c = conn.cursor()
    c.execute(f"UPDATE players SET {', '.join(updates)} WHERE name = %s", values)
    conn.commit()

    # If rank changed, fix conflicts in that tier
    if rank is not None:
        target_tier = tier if tier else p["tier"]
        # Push any other player that has the same rank down by 1
        c.execute(
            "UPDATE players SET rank_in_tier = rank_in_tier + 1 WHERE tier = %s AND rank_in_tier = %s AND name != %s",
            (target_tier, rank, uid)
        )
        conn.commit()

    conn.close()

    changed = []
    if wins is not None: changed.append(f"Wins: {wins}")
    if losses is not None: changed.append(f"Losses: {losses}")
    if goals is not None: changed.append(f"Goals: {goals}")
    if tier is not None: changed.append(f"Tier: {tier}")
    if rank is not None: changed.append(f"Rank: {rank}")
    if licensed is not None: changed.append(f"Licensed: {licensed}")
    if playstyle is not None: changed.append(f"Playstyle: {playstyle}")

    await interaction.response.send_message(f"✅ Updated **{display}**: {' | '.join(changed)}")


@tree.command(name="removeandfill", description="Remove a player and cascade ranks down through all tiers (admin only)")
@is_admin()
@app_commands.describe(player="Select the player to remove")
async def removeandfill(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer()

    uid = str(player.id)
    display = player.display_name
    p = get_player(uid)
    if not p:
        await interaction.followup.send(f"❌ **{display}** not found!")
        return

    removed_tier = p["tier"]
    removed_rank = p["rank_in_tier"]

    conn = get_db()
    c = conn.cursor()

    # Remove the player
    c.execute("DELETE FROM players WHERE name = %s", (uid,))
    conn.commit()
    conn.close()

    log = [f"🗑️ **{display}** removed from **{removed_tier}** (Rank {removed_rank})"]

    # Cascade: for each tier starting from removed_tier going down
    current_tier_idx = tier_index(removed_tier)

    while current_tier_idx < len(TIERS) - 1:
        current_tier = TIERS[current_tier_idx]
        next_tier = TIERS[current_tier_idx + 1]

        # Re-rank current tier (fill gaps)
        players_in_current = get_tier_players(current_tier)
        conn = get_db()
        c = conn.cursor()
        for i, p in enumerate(players_in_current):
            c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, p["name"]))
        conn.commit()
        conn.close()

        # Check if current tier now has less than 4 players
        players_in_current = get_tier_players(current_tier)
        if len(players_in_current) >= 4:
            break

        # Get rank 1 player from next tier
        players_in_next = get_tier_players(next_tier)
        if not players_in_next:
            log.append(f"⚠️ **{next_tier}** is empty, no one to promote.")
            break

        promoted = players_in_next[0]
        new_rank = len(players_in_current) + 1

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "UPDATE players SET tier = %s, rank_in_tier = %s, round_wins = 0, round_losses = 0, round_done = 0 WHERE name = %s",
            (current_tier, new_rank, promoted["name"])
        )
        conn.commit()
        conn.close()

        log.append(f"⬆️ {get_display(interaction.guild, get_uid(promoted['name']))} moved from **{next_tier}** rank 1 → **{current_tier}** rank {new_rank}")

        # Re-rank next tier
        players_in_next = get_tier_players(next_tier)
        conn = get_db()
        c = conn.cursor()
        for i, p in enumerate(players_in_next):
            c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, p["name"]))
        conn.commit()
        conn.close()

        current_tier_idx += 1

    # Final re-rank of last tier
    last_tier = TIERS[-1]
    players_last = get_tier_players(last_tier)
    conn = get_db()
    c = conn.cursor()
    for i, p in enumerate(players_last):
        c.execute("UPDATE players SET rank_in_tier = %s WHERE name = %s", (i + 1, p["name"]))
    conn.commit()
    conn.close()

    log.append(f"\n✅ A spot is now open in **{TIERS[-1]}**. Use `/addplayer` to fill it!")

    embed = discord.Embed(title="🔄 Player Removed — Ranks Cascaded", color=0xff4444)
    embed.description = "\n".join(log)
    await interaction.followup.send(embed=embed)

# ─────────────────────────────────────────
# BOT EVENTS
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    try:
        print(f"⏳ on_ready started for {bot.user}")
        setup_db()
        # Setup ranked tables
        conn_r = get_db()
        setup_ranked_db(conn_r)
        conn_r.close()
        print("📊 Database ready")
        print("👥 Skipping member cache preload")
        synced = await tree.sync()
        print(f"✅ Bot is online as {bot.user}!")
        print(f"🎮 Slash commands synced: {len(synced)} commands")
    except Exception as e:
        print(f"❌ on_ready error: {e}")

from flask import Flask
from threading import Thread

app = Flask(__name__)

@tree.command(name="showscores", description="Show matches and stats for a tier")
@is_admin()
@app_commands.describe(tier="Select a tier")
@app_commands.autocomplete(tier=tier_autocomplete)
async def showscores(interaction: discord.Interaction, tier: str):
    await interaction.response.defer()
    tier = tier.title()
    if tier not in TIERS:
        await interaction.followup.send("❌ Invalid tier!", ephemeral=True)
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM matches WHERE tier = %s ORDER BY date ASC", (tier,))
    matches = [dict(m) for m in c.fetchall()]
    c.execute("SELECT * FROM players WHERE tier = %s ORDER BY rank_in_tier ASC", (tier,))
    players = [dict(p) for p in c.fetchall()]
    conn.close()

    def get_display(uid):
        member = interaction.guild.get_member(int(uid))
        return member.display_name if member else uid

    embed = discord.Embed(title=f"📊 {tier} — Match Overview", color=0x00ff88)

    # Match list
    if matches:
        match_lines = []
        for m in matches:
            n1 = get_display(m["player1"])
            n2 = get_display(m["player2"])
            match_lines.append(f"{n1} {m['score1']} — {m['score2']} {n2}")
        embed.add_field(name="⚽ Matches", value=chr(10).join(match_lines), inline=False)

    # Per-player summary from matches in this tier
    stats = {}
    for m in matches:
        for uid, goals_for, goals_against, won in [
            (m["player1"], m["score1"], m["score2"], int(str(m["score1"])) > int(str(m["score2"]))),
            (m["player2"], m["score2"], m["score1"], int(str(m["score2"])) > int(str(m["score1"])))
        ]:
            if uid not in stats:
                stats[uid] = {"w": 0, "l": 0, "goals": 0}
            if won:
                stats[uid]["w"] += 1
            else:
                stats[uid]["l"] += 1
            stats[uid]["goals"] += int(str(goals_for))

    if stats:
        summary_lines = []
        for p in players:
            uid = get_uid(p["name"])
            name = get_display(uid)
            s = stats.get(uid, {"w": 0, "l": 0, "goals": 0})
            summary_lines.append(f"{name} — W: {s['w']} | L: {s['l']} | Goals: {s['goals']}")
        embed.add_field(name="📈 Summary", value=chr(10).join(summary_lines), inline=False)

    await interaction.followup.send(embed=embed)

@tree.command(name="log", description="View bot activity log for today (admin only)")
@is_admin()
async def log(interaction: discord.Interaction):
    await interaction.response.defer()
    conn = get_db()
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""
        SELECT player1, player2, score1, score2, date FROM matches
        WHERE date LIKE %s ORDER BY date DESC LIMIT 30
    """, (today + "%",))
    matches = [dict(m) for m in c.fetchall()]
    conn.close()
    if not matches:
        await interaction.followup.send("📋 No activity logged today.")
        return
    embed = discord.Embed(title=f"📋 Bot Log — {today}", color=0x5865F2)
    lines = []
    for m in matches:
        member1 = interaction.guild.get_member(int(m["player1"]))
        member2 = interaction.guild.get_member(int(m["player2"]))
        n1 = member1.display_name if member1 else m["player1"]
        n2 = member2.display_name if member2 else m["player2"]
        time_str = m["date"][11:16] if m["date"] else "?"
        tier_str = f" ({m['tier']})" if m.get("tier") else ""
        lines.append(f"`{time_str}`{tier_str} {n1} {m['score1']} — {m['score2']} {n2}")
    embed.description = chr(10).join(lines)
    await interaction.followup.send(embed=embed)


# ============================================================
# RANKED SYSTEM ADDITION
# ============================================================

RANKED_RANKS = [
    {"name": "Bronze",    "min": 0,    "max": 200},
    {"name": "Silver",    "min": 200,  "max": 400},
    {"name": "Gold",      "min": 400,  "max": 650},
    {"name": "Elite",     "min": 650,  "max": 950},
    {"name": "Emerald",   "min": 950,  "max": 1300},
    {"name": "Emperor",   "min": 1300, "max": 1700},
    {"name": "Supernova", "min": 1700, "max": 2150},
    {"name": "Eternal",   "min": 2150, "max": 999999},
]

RANKED_K = 32

def get_ranked_rank(elo):
    for r in reversed(RANKED_RANKS):
        if elo >= r["min"]:
            return r["name"]
    return "Bronze"

def calc_elo(winner_elo, loser_elo):
    expected_w = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_l = 1 - expected_w
    new_winner = round(winner_elo + RANKED_K * (1 - expected_w))
    new_loser = round(loser_elo + RANKED_K * (0 - expected_l))
    new_loser = max(0, new_loser)
    gain = new_winner - winner_elo
    loss = loser_elo - new_loser
    return new_winner, new_loser, gain, loss

def setup_ranked_db(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ranked_players (
            name TEXT PRIMARY KEY,
            elo INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ranked_matches (
            id SERIAL PRIMARY KEY,
            player1 TEXT,
            player2 TEXT,
            score1 INTEGER,
            score2 INTEGER,
            elo_change INTEGER,
            date TEXT
        )
    """)
    conn.commit()

# Pending ranked scores: {message_id: {player1, player2, score1, score2}}
pending_ranked_scores = {}
# Active matchmaking: {message_id: seeker_id}
active_matchmaking = {}

@tree.command(name="rankedregister", description="Register yourself for CFI Ranked")
async def rankedregister(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM ranked_players WHERE name = %s", (uid,))
    if c.fetchone():
        conn.close()
        await interaction.followup.send("❌ You are already registered for Ranked!", ephemeral=True)
        return
    c.execute("INSERT INTO ranked_players (name, elo, wins, losses) VALUES (%s, 0, 0, 0)", (uid,))
    conn.commit()
    conn.close()
    await interaction.followup.send("✅ You are now registered for CFI Ranked! Starting Elo: **0** (Bronze)", ephemeral=True)

@tree.command(name="rankedprofile", description="View a player's ranked profile")
@app_commands.describe(player="Select a player")
async def rankedprofile(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer()
    target = player
    uid = str(target.id)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ranked_players WHERE name = %s", (uid,))
    p = c.fetchone()
    if not p:
        conn.close()
        await interaction.followup.send(f"❌ **{target.display_name}** is not registered for Ranked!")
        return
    p = dict(p)
    # Global rank position
    c.execute("SELECT name FROM ranked_players ORDER BY elo DESC, name ASC")
    all_ranked = [dict(r) for r in c.fetchall()]
    global_pos = next((i + 1 for i, r in enumerate(all_ranked) if r["name"] == uid), 1)
    conn.close()

    rank_name = get_ranked_rank(p["elo"])
    total = p["wins"] + p["losses"]
    winrate = round((p["wins"] / total * 100)) if total > 0 else 0

    embed = discord.Embed(title=f"⚽ {target.display_name}", color=0xffaa00)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.description = (
        f"**Elo:** {p['elo']} pts\n"
        f"**Global Position:** #{global_pos}\n"
        f"**Rank:** {rank_name}\n"
        f"**Wins:** {p['wins']}\n"
        f"**Losses:** {p['losses']}\n"
        f"**Matches Played:** {total}\n"
        f"**Winrate:** {winrate}%"
    )
    await interaction.followup.send(embed=embed)

@tree.command(name="rankedleaderboard", description="Top 10 CFI Ranked players")
async def rankedleaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ranked_players ORDER BY elo DESC, name ASC LIMIT 10")
    players = [dict(p) for p in c.fetchall()]
    conn.close()

    if not players:
        await interaction.followup.send("No ranked players yet!")
        return

    medals = ["🥇", "🥈", "🥉"]
    embed = discord.Embed(title="🏆 CFI Ranked Leaderboard", color=0xFFD700)
    lines = []
    for i, p in enumerate(players):
        member = interaction.guild.get_member(int(p["name"]))
        name = member.display_name if member else p["name"]
        medal = medals[i] if i < 3 else f"{i+1}."
        rank_name = get_ranked_rank(p["elo"])
        lines.append(f"{medal} **{name}** — {p['elo']} pts ({rank_name})")
    embed.description = chr(10).join(lines)
    await interaction.followup.send(embed=embed)

@tree.command(name="rankedmatchmaking", description="Open anonymous matchmaking for Ranked")
async def rankedmatchmaking(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = str(interaction.user.id)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ranked_players WHERE name = %s", (uid,))
    p = c.fetchone()
    conn.close()
    if not p:
        await interaction.followup.send("❌ You are not registered for Ranked! Use /rankedregister first.", ephemeral=True)
        return

    p = dict(p)
    rank_name = get_ranked_rank(p["elo"])

    embed = discord.Embed(title="🕵️ Ranked Matchmaking", color=0x5865F2)
    embed.description = (
        "An **anonymous player** is looking for a match!\n\n"
        "Click **Accept** to play!"
    )

    accept_btn = discord.ui.Button(label="Accept", style=discord.ButtonStyle.green, custom_id="ranked_accept")
    cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.red, custom_id="ranked_cancel")
    view = discord.ui.View(timeout=300)
    view.add_item(accept_btn)
    view.add_item(cancel_btn)

    msg = await interaction.followup.send(embed=embed, view=view)
    active_matchmaking[msg.id] = uid

@tree.command(name="rankedscore", description="Submit a ranked match score")
@app_commands.describe(opponent="Your opponent", goals_you="Your goals", goals_opponent="Opponent goals")
async def rankedscore(interaction: discord.Interaction, opponent: discord.Member, goals_you: int, goals_opponent: int):
    await interaction.response.defer()
    uid = str(interaction.user.id)
    opp_uid = str(opponent.id)

    if goals_you == goals_opponent:
        await interaction.followup.send("❌ Draws are not allowed!")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ranked_players WHERE name = %s", (uid,))
    p1 = c.fetchone()
    c.execute("SELECT * FROM ranked_players WHERE name = %s", (opp_uid,))
    p2 = c.fetchone()
    conn.close()

    if not p1:
        await interaction.followup.send("❌ You are not registered for Ranked!", ephemeral=True)
        return
    if not p2:
        await interaction.followup.send(f"❌ {opponent.display_name} is not registered for Ranked!")
        return

    embed = discord.Embed(title="⚽ Ranked Score Submission", color=0xff9900)
    embed.description = (
        f"**{interaction.user.display_name}** {goals_you} — {goals_opponent} **{opponent.display_name}**\n\n"
        f"<@{opp_uid}> please confirm this score!"
    )
    embed.set_footer(text=f"Submitted by {interaction.user.display_name}")

    confirm_btn = discord.ui.Button(label="✅ Confirm", style=discord.ButtonStyle.green, custom_id="ranked_confirm")
    deny_btn = discord.ui.Button(label="❌ Deny", style=discord.ButtonStyle.red, custom_id="ranked_deny")
    view = discord.ui.View(timeout=300)
    view.add_item(confirm_btn)
    view.add_item(deny_btn)

    msg = await interaction.followup.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions(users=True))
    pending_ranked_scores[msg.id] = {
        "player1": uid,
        "player2": opp_uid,
        "score1": goals_you,
        "score2": goals_opponent,
        "submitter": uid
    }


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id", "")
    uid = str(interaction.user.id)
    msg_id = interaction.message.id

    # ---- MATCHMAKING ACCEPT ----
    if custom_id == "ranked_accept":
        if msg_id not in active_matchmaking:
            await interaction.response.send_message("❌ This matchmaking session has expired.", ephemeral=True)
            return
        seeker_id = active_matchmaking[msg_id]
        if str(uid) == str(seeker_id):
            await interaction.response.send_message("❌ You can't accept your own matchmaking!", ephemeral=True)
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM ranked_players WHERE name = %s", (uid,))
        accepter = c.fetchone()
        conn.close()
        if not accepter:
            await interaction.response.send_message("❌ You are not registered for Ranked!", ephemeral=True)
            return

        seeker = interaction.guild.get_member(int(seeker_id))
        accepter_member = interaction.guild.get_member(int(uid))
        host = random.choice([seeker, accepter_member])

        del active_matchmaking[msg_id]
        embed = discord.Embed(title="✅ Match Found!", color=0x00ff88)
        embed.description = (
            f"**{seeker.display_name if seeker else seeker_id}** vs **{accepter_member.display_name if accepter_member else uid}**\n\n"
            f"🏠 **Host:** {host.display_name}\n\n"
            f"Use `/rankedscore` when the match is done!"
        )
        await interaction.response.edit_message(embed=embed, view=None)


    # ---- MATCHMAKING CANCEL ----
    elif custom_id == "ranked_cancel":
        if msg_id not in active_matchmaking:
            await interaction.response.send_message("❌ This session has expired.", ephemeral=True)
            return
        if uid != active_matchmaking[msg_id]:
            await interaction.response.send_message("❌ Only the person who opened matchmaking can cancel it.", ephemeral=True)
            return
        del active_matchmaking[msg_id]
        await interaction.response.edit_message(content="❌ Matchmaking cancelled.", embed=None, view=None)

    # ---- SCORE CONFIRM ----
    elif custom_id == "ranked_confirm":
        if msg_id not in pending_ranked_scores:
            await interaction.response.send_message("❌ This score submission has expired.", ephemeral=True)
            return
        data = pending_ranked_scores[msg_id]
        if str(uid) == str(data["submitter"]):
            await interaction.response.send_message("❌ You can't confirm your own score submission!", ephemeral=True)
            return
        if str(uid) != str(data["player2"]):
            await interaction.response.send_message("❌ Only the opponent can confirm this score.", ephemeral=True)
            return

        p1_id = data["player1"]
        p2_id = data["player2"]
        s1 = data["score1"]
        s2 = data["score2"]
        winner_id = p1_id if s1 > s2 else p2_id
        loser_id = p2_id if s1 > s2 else p1_id

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM ranked_players WHERE name = %s", (winner_id,))
        winner_data = dict(c.fetchone())
        c.execute("SELECT * FROM ranked_players WHERE name = %s", (loser_id,))
        loser_data = dict(c.fetchone())

        new_winner_elo, new_loser_elo, gain, loss = calc_elo(winner_data["elo"], loser_data["elo"])

        c.execute("UPDATE ranked_players SET elo = %s, wins = wins + 1 WHERE name = %s", (new_winner_elo, winner_id))
        c.execute("UPDATE ranked_players SET elo = %s, losses = losses + 1 WHERE name = %s", (new_loser_elo, loser_id))
        c.execute("""
            INSERT INTO ranked_matches (player1, player2, score1, score2, elo_change, date)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (p1_id, p2_id, s1, s2, gain, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        del pending_ranked_scores[msg_id]

        winner_member = interaction.guild.get_member(int(winner_id))
        loser_member = interaction.guild.get_member(int(loser_id))
        winner_name = winner_member.display_name if winner_member else winner_id
        loser_name = loser_member.display_name if loser_member else loser_id

        winner_rank = get_ranked_rank(new_winner_elo)
        loser_rank = get_ranked_rank(new_loser_elo)

        embed = discord.Embed(title="✅ Ranked Score Confirmed!", color=0x00ff88)
        embed.description = (
            f"🏆 **{winner_name}** wins!\n\n"
            f"**{winner_name}** — {new_winner_elo} pts ({winner_rank}) `+{gain}`\n"
            f"**{loser_name}** — {new_loser_elo} pts ({loser_rank}) `-{loss}`"
        )
        await interaction.response.edit_message(embed=embed, view=None)

    # ---- SCORE DENY ----
    elif custom_id == "ranked_deny":
        if msg_id not in pending_ranked_scores:
            await interaction.response.send_message("❌ This score submission has expired.", ephemeral=True)
            return
        data = pending_ranked_scores[msg_id]
        if str(uid) != str(data["player2"]):
            await interaction.response.send_message("❌ Only the opponent can deny this score.", ephemeral=True)
            return
        del pending_ranked_scores[msg_id]
        await interaction.response.edit_message(content="❌ Score denied by opponent.", embed=None, view=None)


@tree.command(name="rankedsetstats", description="Manually update a player's ranked stats (admin only)")
@is_admin()
@app_commands.describe(
    player="Select a player",
    elo="New Elo points",
    wins="New win count",
    losses="New loss count"
)
async def rankedsetstats(interaction: discord.Interaction, player: discord.Member, elo: int = None, wins: int = None, losses: int = None):
    uid = str(player.id)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ranked_players WHERE name = %s", (uid,))
    p = c.fetchone()
    if not p:
        conn.close()
        await interaction.response.send_message(f"❌ **{player.display_name}** is not registered for Ranked!", ephemeral=True)
        return

    updates = []
    values = []
    changed = []

    if elo is not None:
        updates.append("elo = %s")
        values.append(max(0, elo))
        changed.append(f"Elo: {max(0, elo)} ({get_ranked_rank(max(0, elo))})")
    if wins is not None:
        updates.append("wins = %s")
        values.append(wins)
        changed.append(f"Wins: {wins}")
    if losses is not None:
        updates.append("losses = %s")
        values.append(losses)
        changed.append(f"Losses: {losses}")

    if not updates:
        conn.close()
        await interaction.response.send_message("❌ You didn't change anything!", ephemeral=True)
        return

    values.append(uid)
    c.execute(f"UPDATE ranked_players SET {', '.join(updates)} WHERE name = %s", values)
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Updated **{player.display_name}**: {' | '.join(changed)}")


@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_web).start()
bot.run(BOT_TOKEN)
