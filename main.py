import asyncio
import os
import time
import datetime
import math
from enum import Enum

import discord
import yaml
from discord.ext import commands
from slugify import slugify
import shutil

import ServerPinger as sp
import discordUtils as dUtils

dir = os.path.dirname(os.path.realpath(__file__))
conDir = dir + "/config.yml"

separator = "|+|"

players = []

default = {
    "Servers": {
        "TTT": "66.85.80.171:27015",
        "JB": "66.85.80.170:27015",
        "MG": "66.85.80.174:27015"
    },
    "ChannelName": "player-logs"
}

client = commands.Bot(".")
config = {}


def prepareConfig():
    global config
    if not os.path.exists(conDir):
        with open(conDir, "w+", encoding="utf-8") as config:
            yaml.dump(default, config, sort_keys=False)
    with open(conDir, encoding="utf-8") as cFile:
        config = yaml.full_load(cFile)


async def main():
    global players
    global config
    prepareConfig()
    servers = []
    players = loadPlayers()

    for server in config["Servers"]:
        address = config["Servers"][server].split(":")[0]
        port = int(config["Servers"][server].split(":")[1])
        servers.append(Server(server, address, port))

    client.loop.create_task(updatePlayers())

    for guild in client.guilds:
        await getChannel(guild, config["ChannelName"]).purge(limit=100)

    while True:
        for server in servers:
            server.refresh()
            for player in server.players.values():
                player.save()
        await sendPlaytimes(servers)
        await asyncio.sleep(5)


guildmessages = {}


async def sendPlaytimes(servers):
    global guildmessages
    for server in servers:
        for guild in client.guilds:
            if guild.id not in guildmessages.keys():
                guildmessages[guild.id] = {}
            if server.name not in guildmessages[guild.id].keys():
                guildmessages[guild.id][server.name] = None

            newMessage = createEmbed(server.name + " Player List",
                                     "\n".join(cleanList(server.playerNames)) if server.playerNames else "No Players",
                                     color=discord.Color.blue())

            footer = ""

            if server.joined:
                footer += "[+] " + ", ".join(server.joined)
                if server.disconnected:
                    footer += "\n"
            if server.disconnected:
                footer += "[-] " + ", ".join(server.disconnected)

            footer += "\nLast Updated at " + datetime.datetime.now().strftime("%I:%M %p")

            newMessage.set_footer(text=footer)
            newMessage.add_field(name="Map", value=server.map)
            newMessage.add_field(name="Players", value=str(
                len(server.players)) + "/" + str(server.maxPlayers))

            message: discord.Message = guildmessages[guild.id][server.name]

            channel: discord.TextChannel = getChannel(guild, config["ChannelName"])
            guild: discord.Guild

            if message is None:
                message = await channel.send(
                    embed=createEmbed(server.name + " Player List", "No Players", color=discord.Color.red()))

            guildmessages[guild.id][server.name] = message
            await message.edit(embed=newMessage)


def createEmbed(title, desc, color=discord.Colour.default(), url=None):
    return discord.Embed(title=title, description=desc, color=color, url=url)


def getChannel(guild, name):
    for channel in guild.text_channels:
        if channel.name == name:
            return channel


class Server(object):
    def __init__(self, name, address, port):
        self.name = name
        self.address = address
        self.port = port if isinstance(port, int) else int(port)
        self.lastOnline = time.time()
        self.online = sp.isServerUp(self.address, self.port)
        self.playerNames = []
        self.players = {}
        self.oldPlayers = []
        self.maxPlayers = sp.getInfo(self.address, self.port)["max_players"]
        self.disconnected = []
        self.joined = []
        self.map = None

    def refresh(self):
        if not sp.isServerUp(self.address, self.port):
            self.players = {}
            self.online = False
            print(self.name, "is not online")
            return
        info = sp.getInfo(self.address, self.port)
        self.map = info["map"] if info else self.map
        players = sp.getPlayers(self.address, self.port)
        self.playerNames = []
        if players:
            self.playerNames = sp.getPlayerNames(players)

        self.lastOnline = time.time()

        if self.oldPlayers == self.playerNames:
            return

        self.joined = newPlayers = getNewPlayers(self.oldPlayers, self.playerNames)
        self.disconnected = missingPlayers = getMissingPlayers(self.oldPlayers, self.playerNames)

        for player in newPlayers:
            p = Player().createNew(player)
            p.logon(self)
            self.players[player] = p

        for player in missingPlayers:
            if player not in self.players:
                continue
            p: Player = self.players[player]
            p.logoff()

        self.oldPlayers = self.playerNames

    def __str__(self):
        return "[{}|{}|{}|{}|{}|{}]".replace("|", separator).format(self.name, self.address, self.port, self.lastOnline,
                                                                    self.online,
                                                                    self.playerNames)


def getNewPlayers(oldList, newList):
    result = newList.copy()
    for player in oldList:
        if player in result:
            result.remove(player)
    return cleanList(result)


def getMissingPlayers(oldList, newList):
    result = []
    for name in oldList:
        if name not in newList:
            result.append(name)
    return cleanList(result)


def cleanList(list):
    while "" in list:
        list.remove("")
    return list


def loadPlayers():
    if not os.path.exists(dir + "/players"):
        return
    players = []
    for file in os.listdir(dir + "/players"):
        with open(dir + "/players/" + file, encoding="utf-8") as f:
            text = f.read()
            if not text:
                continue
            player = Player().construct(text)
            players.append(player)
    return players


class Player(object):

    def __init__(self):
        self.name = None
        self.file = dir + "/players/default.txt"
        self.online = False
        self.server = None
        self.session = None
        self.sessions = []

    def createNew(self, name):
        self.name = name
        self.file = dir + "/players/" + slugify(self.name) + ".txt"
        if os.path.exists(self.file):
            with open(self.file, encoding="utf-8") as f:
                text = f.read()
                self.construct(text)
        return self

    def construct(self, string: str):
        args = string.splitlines()
        self.name = args[0]
        for sess in args[1:]:
            self.sessions.append(Session().fromString(sess))
        if not os.path.exists(self.file):
            with open(self.file, "w+", encoding="utf-8") as f:
                f.write(self.name + separator)
        return self

    def save(self):
        if not os.path.exists(dir + "/players"):
            os.mkdir(dir + "/players")
        with open(self.file, "w+", encoding="utf-8") as f:
            f.write(self.name + "\n")
            for sess in self.sessions:
                f.write(str(sess) + "\n")
            if self.session:
                f.write(str(self.session) + "\n")

    def getTimeSince(self, timespan, server=None):
        result = 0
        for session in self.getTimeSessionsSince(timespan, server):
            result += session.getTime()
        return result

    def getTimeSessionsSince(self, timespan, server=None):
        result = []
        minTime = time.time() - timespan
        for session in self.sessions:
            if session.timeOn < minTime and timespan != -1:
                continue
            if server and session.server != server:
                continue
            result.append(session)
        return result

    def logoff(self):
        self.session.logoff()
        self.sessions.append(self.session)
        self.save()
        self.session = None
        self.online = False

    def logon(self, server):
        self.session = Session().createNew(server.name)
        self.online = True

    def getFirstSeen(self):
        if not self.sessions:
            return -1
        return self.sessions[0].timeOn

    def getLastSeen(self):
        if not self.sessions:
            return -1
        if self.online:
            return time.time()
        return self.sessions[-1].timeOff

    def __str__(self):
        return "[{}\n{}]".format(self.name, "\n".join(self.sessions))

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, Player):
            return False
        return self.name == other.name


class Session(object):
    def __init__(self):
        self.server = None
        self.timeOn = time.time()
        self.timeOff = -1

    def fromString(self, string: str):
        args = string[1:-1].split(separator)
        self.server = args[0]
        self.timeOn = float(args[1])
        self.timeOff = float(args[2])
        return self

    def createNew(self, server):
        self.server = server
        self.timeOn = time.time()
        self.timeOff = -1
        return self

    def getTime(self):
        return time.time() - self.timeOn if self.timeOff == -1 else self.timeOff - self.timeOn

    def logoff(self):
        self.timeOff = time.time()

    def logon(self):
        self.timeOn = time.time()

    def __str__(self):
        return "[{}|{}|{}]".replace("|", separator).format(self.server, self.timeOn,
                                                           time.time() if self.timeOff == -1 else self.timeOff)


class PlayerInfoCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        if len(args) == 0:
            return await dUtils.sendMessage(msg.channel, "Please specify a player to lookup.")
        name = " ".join(args)
        player = getPlayer(name)
        if not player:
            return await dUtils.sendMessage(msg.channel,
                                            "Unable to find player by the name of {}.".format(dUtils.raw(name)))
        desc = ""
        for time in [Timespan.DAYS, Timespan.WEEKS, Timespan.MONTHS]:
            desc += "{}: {}\n".format("1 " + time.name.title()[:-1], formatTime(player.getTimeSince(time.value)))
        embed = createEmbed(player.name + "'s Information", "Online time since:\n" + desc)

        embed.add_field(name="First Seen",
                        value=datetime.datetime.fromtimestamp(player.getFirstSeen()).strftime("%I:%M:%S %p %m/%d/%Y"))
        embed.add_field(name="Last Seen",
                        value=datetime.datetime.fromtimestamp(player.getLastSeen()).strftime("%I:%M:%S %p %m/%d/%Y"))

        return await dUtils.sendMessage(msg.channel, embed)


def getPlayer(name):
    global players
    for player in players:
        if player.name == name or slugify(player.name) == slugify(name):
            return player

    for player in players:
        if slugify(name) in slugify(player.name):
            return player


class HelpCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        desc = ["Format: >[command] <args>", ""]

        for cmd in dUtils.registeredCommands.values():
            cmd: dUtils.Command
            if not cmd.hasPerm(msg.author):
                continue
            desc.append("**{}** _{}_".format(cmd.name.title(), discord.utils.escape_markdown(cmd.usage)))
            desc.append("{}".format(cmd.description))
            if cmd.permission:
                desc.append("(**{}**)".format(cmd.permission.title()))
            desc.append("")

        return [await dUtils.Pageable(desc, "Help", msg.author, msg.channel, color=discord.Color.purple()).send()]


class SaveCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        for player in players:
            player.save()
        return await dUtils.sendMessage(msg.channel, "Successfully saved player data.")


def playerSort(a: Player, b: Player):
    return -1 if a.getTimeSince(-1) > b.getTimeSince(-1) else 1


def formatTime(seconds: int):
    result: Timespan = Timespan.SECONDS
    for t in Timespan:
        t: Timespan
        if seconds >= t.value:
            result = t
    return "{:0.2f} {}".format(seconds / result.value, result.name.title())


class DeletePlaytimeCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        if len(args) == 0:
            return [await dUtils.sendMessage(msg.channel, "Please specify a username or all")]
        if not os.path.exists(dir + "/players/" + args[0] + ".txt") and args[0] != "all":
            return await dUtils.sendMessage(msg.channel, "**{}** was not found.".format(dUtils.raw(args[0])))
        return await ConfirmDelete("Do you really want to delete **{}** player data?".format(dUtils.raw(args[0])),
                                   msg.author, args[0]).send(msg.channel)


class ConfirmDelete(dUtils.ConfirmMessage):
    def __init__(self, message, author, target):
        super().__init__(message, author)
        self.target = target
        self.func = None

    async def confirm(self):
        global players
        if self.target == "all":
            shutil.rmtree(dir + "/players")
            players = []
            await updatePlayers()
            return await dUtils.sendMessage(self.sent.channel, "Successfully deleted all player data.")
        else:
            os.remove(dir + "/players/" + self.target + ".txt")
            await updatePlayers()
            return await dUtils.sendMessage(self.sent.channel,
                                            "Successfully deleted player data of {}.".format(self.target))


class NewPlayersCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        pass


class PlaytimeCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        global players
        leaderboard = {}
        if len(args) == 0:
            if not players:
                return await dUtils.sendMessage(msg.channel, "No playtimes")
            for p in players:
                p: Player
                leaderboard[p] = p.getTimeSince(-1)
            result = generateLeaderboard(leaderboard)
            embed = await dUtils.Pageable(result, "Leaderboard", msg.author, msg.channel,
                                          color=discord.Color.green()).send()
            return embed
        if len(args) == 1:
            name: str = args[0]
            if name in config["Servers"]:
                for p in players:
                    p: Player
                    leaderboard[p] = p.getTimeSince(-1, name)
                result = generateLeaderboard(leaderboard)
                embed = await dUtils.Pageable(result, "Leaderboard (" + name + ")", msg.author, msg.channel,
                                              color=discord.Color.green()).send()
                return embed
            span = strToSeconds(name)
            if span:
                for p in players:
                    p: Player
                    leaderboard[p] = p.getTimeSince(span)
                result = generateLeaderboard(leaderboard)
                page = await dUtils.Pageable(result,
                                             "Leaderboard (" + formatTime(span) + ")", msg.author, msg.channel,
                                             color=discord.Color.green()).send()
                return page

            for p in players:
                p: Player
                leaderboard[p] = p.getTimeSince(span)

            page = 0

            result = generateLeaderboard(leaderboard)

            player = getPlayer(name)

            if not player:
                return dUtils.sendMessage(msg.channel, "Unknown player.")

            for index, line in enumerate(result):
                if player.name in line:
                    page = index
            embed = dUtils.Pageable(result, "Leaderboard (" + player.name + ")", msg.author, msg.channel,
                                    color=discord.Color.green())
            page = math.ceil(page / embed.size) - 1
            embed.page = page

            return await embed.send()
        if len(args) == 2:
            # could be player, timeframe
            # or player, server
            # if args[1] is numerical, timeframe, otherwise server
            pass

        if len(args) == 3:
            # should be player, server, timeframe
            pass


class RefreshCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        global players
        players = loadPlayers()
        return await dUtils.sendMessage(msg.channel, "Successfully updated playtimes manually.")


def generateLeaderboard(players):
    ps = sorted(players.items(), key=lambda kv: kv[1], reverse=True)
    result = []
    for player in ps:
        player = player[0]
        result.append(player.name + ": " + formatTime(players[player]))
    return result


def strToSeconds(string: str):
    # 3 seconds, 10 minutes
    string = string.replace(" ", "").replace(",", "")
    n = ""
    t = 0
    for c in string:
        if c.isnumeric() or c == ".":
            n += c
        else:
            try:
                t += getTimespan(c).value * float(n)
            except(ValueError, AttributeError):
                pass
            n = ""
    return t


def getTimespan(c: str):
    c = c.lower()
    if c == "s": return Timespan.SECONDS
    if c == "m": return Timespan.MINUTES
    if c == "h": return Timespan.HOURS
    if c == "d": return Timespan.DAYS
    if c == "w": return Timespan.WEEKS
    if c == "mo": return Timespan.MONTHS
    if c == "y": return Timespan.YEARS


class Timespan(Enum):
    SECONDS = 1
    MINUTES = SECONDS * 60
    HOURS = MINUTES * 60
    DAYS = HOURS * 24
    WEEKS = DAYS * 7
    MONTHS = WEEKS * 4
    YEARS = MONTHS * 12


async def updatePlayers():
    global players
    while True:
        if players:
            for player in players:
                player.save()
        players = loadPlayers()
        await asyncio.sleep(60)


@client.event
async def on_ready():
    dUtils.init(client)
    client.remove_command("help")
    dUtils.registerComand(PlaytimeCommand("Playtime", "List player's playtimes", aliases=["pt"]))
    dUtils.registerComand(RefreshCommand("Refresh", "Refreshses all playtimes", aliases=["ref", "update", "u"]))
    dUtils.registerComand(
        DeletePlaytimeCommand("DeletePlaytime", "Delete's a player's playtime", aliases=["dp"],
                              permission="administrator"))
    dUtils.registerComand(PlayerInfoCommand("PlayerInfo", "Get's playtime information", aliases=["pi"]))
    dUtils.registerComand(SaveCommand("Save", "Save player data"))
    dUtils.registerComand(HelpCommand("Help", "Gets help"))
    client.loop.create_task(main())


if __name__ == "__main__":
    with open("secret.txt", encoding="utf-8") as f:
        key = f.readline()
    client.run(key)