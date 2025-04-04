from interactions.ext.paginators import Paginator
from funcs import match_score, intable
import interactions as discord
import hashlib
import aiohttp
import asyncio
import certifi
import json
import time
import ssl
import re

def sanitize_username(name: str) -> str:    
    return re.sub(r"^\[[A-Za-z0-9]{3}\]", "", name.replace("\u00a0", " ")).strip()

class Giftcode(discord.Extension):
    def __init__(self, bot: discord.Client):
        self.apiLimits = {"inUse": False, "lastUse": 0}
        self.bot = bot
        
    async def login_user(self, session: aiohttp.ClientSession, player: dict) -> tuple[bool, str, str, dict]: # exit, counter, message, player
        timens = time.time_ns()
        
        login_resp = await session.post(
            url="https://wos-giftcode-api.centurygame.com/api/player",
            data={
                "fid": player["id"],
                "time": timens,
                "sign": hashlib.md5(f"fid={player['id']}&time={timens}tB87#kPtkxqOS2".encode("utf-8")).hexdigest()
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=30
        )
        
        try:
            login_result = await login_resp.json()
        except Exception as _:
            return False, "error", "login error", None
        
        if "msg" in login_result:
            if login_result["msg"] != "success":
                return False, "error", "login error", None
            else:
                return False, "success", "success", login_result
        else:
            return False, "error", "rate limited", None
    
    async def redeem_code(self, session: aiohttp.ClientSession, code: str, player: dict) -> tuple[bool, str, str]:
        exit, counter, message, _ = await self.login_user(session, player)
        
        if exit:
            return exit, counter, message
        
        timens = time.time_ns()
        
        redeem_resp = await session.post(
            url="https://wos-giftcode-api.centurygame.com/api/gift_code",
            data={
                "cdk": code,
                "fid": player["id"],
                "time": timens,
                "sign": hashlib.md5(f"cdk={code}&fid={player['id']}&time={timens}tB87#kPtkxqOS2".encode("utf-8")).hexdigest()
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=30
        )
        
        try:
            redeem_result = await redeem_resp.json()
        except Exception as _:
            return False, "error", "unknown error"
        
        if redeem_result["err_code"] == 40014:
            return True, None, "gift code does not exist"
        elif redeem_result["err_code"] == 40007:
            return True, None, "gift code has expired"
        elif redeem_result["err_code"] == 40005:
            return True, None, "gift code has been fully claimed"
        elif redeem_result["err_code"] == 40008:
            return False, "already_claimed", "already claimed"
        elif redeem_result["err_code"] == 20000:
            return False, "successfully_claimed", "successfully claimed"
        else:
            return False, "error", "unknown error"
    
    async def recursive_redeem(self, message: discord.Message, session: aiohttp.ClientSession, code: str, players: list, counters: dict | None = None, recursive_depth: int = 0): # success, counters, result            
        if counters is None:
            counters = {"already_claimed": 0, "successfully_claimed": 0, "error": 0}
        
        results = {}
        
        for i in range(0, len(players), 20):
            batch = players[i:i + 20]
            
            msg = "redeeming gift code" if recursive_depth == 0 else f"redeeming gift code (retry {recursive_depth})"
            
            await message.edit(content=f"{msg}... ({min(i, len(players))}/{len(players)}) | next update <t:{1 + int(time.time()) + (len(batch) * 3)}:R>")
            
            for player in batch:
                start = time.time()
                
                exit, counter, result = await self.redeem_code(session, code, player)
                
                if exit:
                    await message.edit(content=f"error: {result}")
                    await session.close()      
                     
                    return
                else:
                    counters[counter] += 1
                    results[player["name"]] = result
                    
                await asyncio.sleep(max(0, 3 - (time.time() - start)))
                    
        remaining_players = [player for player in players if "error" in results[player["name"]]]
        
        if len(remaining_players) == 0:
            msg = (
                f"report: gift code `{code}`\n"
                f"successful: {counters['successfully_claimed']} | "
                f"already claimed: {counters['already_claimed']} | "
                f"retries: {recursive_depth}\n\n"
                f"made with ❤️ by zenpai :D"
            )
            
            await message.edit(content=msg)
            
            await session.close()
            return
                    
        await self.recursive_redeem(
            message=message,
            session=session,
            code=code,
            players=remaining_players,
            counters=counters,
            recursive_depth=recursive_depth + 1,
        )
        
    async def recursive_rename(self, message: discord.Message, session: aiohttp.ClientSession, players: list, counters: dict = {"no_action": 0, "renamed": 0, "error": 0}, recursive_depth: int = 0):
        results = {}
        
        for i in range(0, len(players), 20):
            batch = players[i:i + 20]
            
            msg = "renaming players" if recursive_depth == 0 else f"renaming players (retry {recursive_depth})"
            
            await message.edit(content=f"{msg}... ({min(i, len(players))}/{len(players)}) | next update <t:{1 + int(time.time()) + (len(batch) * 3)}:R>")
            
            for player in batch:
                start = time.time()
                
                exit, _, result, data = await self.login_user(session, player)
                
                if exit:
                    await message.edit(content=f"error: {result}")
                    return
                else:
                    results[player["name"]] = result
                    
                    if result == "success":
                        if sanitize_username(data["data"]["nickname"]) != player["name"]:
                            with open(self.bot.config.PLAYERS_FILE, "r") as f:
                                playersObj = json.load(f)
                            
                            playersObj[player["id"]]["name"] = sanitize_username(data["data"]["nickname"])
                            
                            with open(self.bot.config.PLAYERS_FILE, "w") as f:
                                json.dump(playersObj, f, indent=4)
                            
                            counters["renamed"] += 1
                        else:
                            counters["no_action"] += 1
                    
                await asyncio.sleep(max(0, 3 - (time.time() - start)))
                    
        remaining_players = [player for player in players if "error" in results[player["name"]]]
        
        if len(remaining_players) == 0:         
            msg = f"successfully renamed {counters['renamed']} user{'' if counters['renamed'] == 1 else ''}" if counters["renamed"] > 0 else "no players were renamed"
               
            await message.edit(content=msg)
            
            await session.close()
            return
        
        await self.recursive_rename(
            message=message,
            session=session,
            players=remaining_players,
            counters=counters,
            recursive_depth=recursive_depth + 1
        )
        
    @discord.slash_command(
        name="giftcode",
        description="giftcode-related commands",
        sub_cmd_name="autorename",
        sub_cmd_description="perform auto renaming of users"
    )
    async def autorename(self, ctx: discord.SlashContext):
        if self.apiLimits["inUse"]:
            await ctx.send("error: there can only be one instance of this command running at once")
            return
        
        if self.apiLimits["lastUse"] + 60 > time.time():
            await ctx.send("error: this command has a limit of 1 use every 1 minute to comply with WOS's rate limits")
            return
        
        with open(self.bot.config.PLAYERS_FILE, "r") as f:
            playersObj = json.load(f)
            
        players = [{"id": key, "name": playersObj[key]["name"]} for key in playersObj]
        
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())))
        
        message = await ctx.send("waiting...")
        
        await self.recursive_rename(message, session, players)
        
        self.apiLimits["inUse"] = False
        self.apiLimits["lastUse"] = time.time()
    
    @discord.slash_command(
        name="giftcode",
        description="giftcode-related commands",
        sub_cmd_name="redeem",
        sub_cmd_description="redeem a gift code",
        options=[
            discord.SlashCommandOption(
                name="code",
                description="the code to redeem",
                required=True,
                type=discord.OptionType.STRING
            )
        ]
    )
    async def redeem(self, ctx: discord.SlashContext, code: str):
        if self.apiLimits["inUse"]:
            await ctx.send("error: there can only be one instance of this command running at once")
            return
        
        if self.apiLimits["lastUse"] + 60 > time.time():
            await ctx.send("error: this command has a limit of 1 use every 1 minute to comply with WOS's rate limits")
            return
        
        with open(self.bot.config.PLAYERS_FILE, "r") as f:
            playersObj = json.load(f)
            
        players = [{"id": key, "name": playersObj[key]["name"]} for key in playersObj]
        
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())))
        
        message = await ctx.send("waiting...")
        
        await self.recursive_redeem(message, session, code, players)
        
        self.apiLimits["inUse"] = False
        self.apiLimits["lastUse"] = time.time()
    
    @discord.slash_command(
        name="giftcode",
        description="giftcode-related commands",
        group_name="users",
        group_description="user-related commands",
        sub_cmd_name="list",
        sub_cmd_description="list all users in the database"
    )
    async def list_users(self, ctx: discord.SlashContext):
        with open(self.bot.config.PLAYERS_FILE, "r") as f:
            players = json.load(f)
        
        rank_lists = {1: [], 2: [], 3: [], 4: [], 5: []}
        
        if any([x["rank"] == 0 for x in players.values()]):
            await ctx.send("error: some users have not been assigned a rank (post migration)", ephemeral=True)
            return

        for details in players.values():
            rank_lists[details["rank"]].append(details["name"])
        
        sorted_ranks = [rank_lists[rank] for rank in range(5, 0, -1)]
        ranks = range(1, 6)
        
        rank_lines = [[] for _ in range(5)]
        
        embeds_content = []
        
        for index, rank in enumerate(sorted_ranks):
            rank_lines[index].append(f"**R{ranks[-(index + 1)]}**")
            rank_lines[index].append("")
            
            for player in rank:
                rank_lines[index].append(f"**{player}**")
                
            rank_lines[index].extend(["" for _ in range(10 - (len(rank_lines[index]) % 10))])

        lines = sum(rank_lines, [])
        
        embeds_content = ["\n".join(lines[i:i + 10]) for i in range(0, len(lines), 10)]
        
        embeds = [
            discord.Embed(
                title="players list",
                description=f"**total players:** {len(players.items())}\n\n{content}\n\nmade with ❤️ by zenpai :D",
                color=0x5865f2
            ) for content in embeds_content
        ]
        
        paginator = Paginator.create_from_embeds(self.bot, *embeds, timeout=300)
        
        paginator.wrong_user_message = "error: you are not the author of this command"
        paginator.show_select_menu = False
        paginator.show_callback_button = False
        
        await paginator.send(ctx)
        
    @discord.slash_command(
        name="giftcode",
        description="giftcode-related commands",
        group_name="users",
        group_description="user-related commands",
        sub_cmd_name="add",
        sub_cmd_description="add a user to the database",
        options=[
            discord.SlashCommandOption(
                name="id",
                description="the user's id",
                required=True,
                type=discord.OptionType.STRING
            ),
            discord.SlashCommandOption(
                name="rank",
                description="the user's rank",
                required=True,
                type=discord.OptionType.INTEGER,
                choices=[
                    discord.SlashCommandChoice(
                        name=f"R{x + 1}",
                        value=x + 1
                    ) for x in range(5)
                ]
            )
        ]
    )
    async def add(self, ctx: discord.SlashContext, id: str, rank: int):
        if intable(id):    
            with open(self.bot.config.PLAYERS_FILE, "r") as f:
                players = json.load(f)
                
            if id in players:
                await ctx.send("error: user id already exists in the database", ephemeral=True)
                return
            
            await ctx.defer(ephemeral=True)
            
            session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())))
            
            err, _, _, user_data = await self.login_user(session, {"id": id})
            
            if not err:
                name = sanitize_username(user_data["data"]["nickname"])
                
                players[id] = {
                    "name": name,
                    "rank": rank
                }
                
                with open(self.bot.config.PLAYERS_FILE, "w") as f:
                    json.dump(players, f, indent=4)
                    
                await ctx.send(f"added user {name} to the database", ephemeral=True)
            else:
                await ctx.send("error: api returned bad data", ephemeral=True)
        else:
            await ctx.send("error: invalid user id", ephemeral=True)
            
    @discord.slash_command(
        name="giftcode",
        description="giftcode-related commands",
        group_name="users",
        group_description="user-related commands",
        sub_cmd_name="remove",
        sub_cmd_description="remove a user from the database",
        options=[
            discord.SlashCommandOption(
                name="name",
                description="the user's name",
                required=True,
                type=discord.OptionType.STRING,
                autocomplete=True,
                argument_name="id"
            )
        ]
    )
    async def remove(self, ctx: discord.SlashContext, id: str):
        with open(self.bot.config.PLAYERS_FILE, "r") as f:
            players = json.load(f)
            
        name = players[id]["name"]
        
        del players[id]
                
        with open(self.bot.config.PLAYERS_FILE, "w") as f:
            json.dump(players, f, indent=4)
            
        await ctx.send(f"removed user {name} from the database", ephemeral=True)
    
    @discord.slash_command(
        name="giftcode",
        description="giftcode-related commands",
        group_name="users",
        group_description="user-related commands",
        sub_cmd_name="rename",
        sub_cmd_description="rename a user in the database",
        options=[
            discord.SlashCommandOption(
                name="name",
                description="the user's name",
                required=True,
                type=discord.OptionType.STRING,
                argument_name="id",
                autocomplete=True
            ),
            discord.SlashCommandOption(
                name="new_name",
                description="the user's new username",
                required=True,
                type=discord.OptionType.STRING
            )
        ]
    )
    async def rename(self, ctx: discord.SlashContext, id: str, new_name: str):
        with open(self.bot.config.PLAYERS_FILE, "r") as f:
            players = json.load(f)
            
        new_name = sanitize_username(new_name)
            
        old_name = players[id]["name"]
        
        players[id]["name"] = new_name
                
        with open(self.bot.config.PLAYERS_FILE, "w") as f:
            json.dump(players, f, indent=4)
            
        await ctx.send(f"changed {old_name}'s name to {new_name}", ephemeral=True)
        
    @discord.slash_command(
        name="giftcode",
        description="giftcode-related commands",
        group_name="users",
        group_description="user-related commands",
        sub_cmd_name="set_rank",
        sub_cmd_description="set a user's rank in the database",
        options=[
            discord.SlashCommandOption(
                name="name",
                description="the user's name",
                required=True,
                type=discord.OptionType.STRING,
                argument_name="id",
                autocomplete=True
            ),
            discord.SlashCommandOption(
                name="rank",
                description="the user's rank",
                required=True,
                type=discord.OptionType.INTEGER,
                choices=[
                    discord.SlashCommandChoice(
                        name=f"R{x + 1}",
                        value=x + 1
                    ) for x in range(5)
                ]
            )
        ]
    )
    async def set_rank(self, ctx: discord.SlashContext, id: str, rank: int):
        with open(self.bot.config.PLAYERS_FILE, "r") as f:
            players = json.load(f)
        
        players[id]["rank"] = rank
                
        with open(self.bot.config.PLAYERS_FILE, "w") as f:
            json.dump(players, f, indent=4)
            
        await ctx.send(f"successfully set {players[id]['name']}'s rank to R{rank}", ephemeral=True)
    
    @set_rank.autocomplete("name")
    @rename.autocomplete("name")
    @remove.autocomplete("name")
    async def user_autocomplete(self, ctx: discord.AutocompleteContext):
        name = ctx.input_text
        
        with open(self.bot.config.PLAYERS_FILE, "r") as f:
            players = json.load(f)
            
        name = sanitize_username(name)
            
        results = [(player_id, player_data["name"], match_score(name, player_data["name"])) for player_id, player_data in players.items()]
            
        results.sort(reverse=True, key=lambda x: x[2])
        
        if not len(results):
            await ctx.send(choices=[])
            return
        
        max_score = max(results[:25], key=lambda x: x[2])[2]
        
        best_matches = [match for match in results if match[2] >= max_score * (1 - 0.3)]
        
        await ctx.send(choices=[{"name": player_name, "value": player_id} for player_id, player_name, _ in (best_matches[:25] if len(best_matches) else results[:25])])