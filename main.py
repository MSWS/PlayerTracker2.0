# Imports
import os
import shutil
import math
import time
import datetime
from dateutil import tz

import asyncio
import discord
import yaml

import ServerPinger as sp
import discordUtils as dUtils
import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt  # pip install matplotlib

from discord.ext import commands  # pip install discord
from slugify import slugify  # pip install python-slugify
from enum import Enum

# Global Variables

dir = os.path.dirname(os.path.realpath(__file__))
conDir = dir + "/config.yml"

separator = "|+|"

players = []
servers = {}

default = {
    "Token": "https://discordapp.com/developers/applications/",
    "Servers": {
        "TTT": "66.85.80.171:27015",
        "JB": "66.85.80.170:27015",
        "MG": "66.85.80.174:27015"
    },
    "ChannelName": "player-logs"
}

client = commands.Bot(".")
config = {}
startTime = time.time()

zone = tz.gettz("US/Pacific")


# Main
async def main():
    global players, servers
    servers = {}
    players = loadPlayers()

    for server in config["Servers"]:
        address = config["Servers"][server].split(":")[0]
        port = int(config["Servers"][server].split(":")[1])
        servers[server] = Server(server, address, port)

    client.loop.create_task(updatePlayers())

    for guild in client.guilds:
        await getChannel(guild, config["ChannelName"]).purge(limit=100)

    while True:
        for server in servers.values():
            server.refresh()
        await sendPlaytimes(servers.values())
        await asyncio.sleep(20)


@client.event
async def on_ready():
    dUtils.init(client)
    client.remove_command("help")
    dUtils.registerComand(PlaytimeCommand("Playtime", "List player's playtimes", aliases=["pt"]))
    dUtils.registerComand(RefreshCommand("Refresh", "Refreshses all playtimes", aliases=["ref", "update", "u"]))
    dUtils.registerComand(
        DeletePlaytimeCommand("DeletePlaytime", "Delete's a player's playtime", aliases=["dp"],
                              permission="administrator"))
    dUtils.registerComand(PlayerInfoCommand("PlayerInfo", "Get's playtime information", "playerinfo [player]", ["pi"]))
    dUtils.registerComand(SaveCommand("Save", "Save player data"))
    dUtils.registerComand(
        GetNewPlayersCommand("GetNewPlayers", "Lookup who has recently just joined the server",
                             "getnewplayers <timespan>",
                             ["gnp", "fnp", "np", "new"]))
    dUtils.registerComand(
        GraphCommand("Graph", "Generate graph of player's playtime", "graph [timespan] <period>",
                     aliases=["g", "gg", "cg"]))
    dUtils.registerComand(
        StatisticsCommand("Statistics", "View bot/player statistics", "statistics <server>", ["stats", "uptime"]))
    dUtils.registerComand(HelpCommand("Help", "Gets help"))
    act = discord.Activity(type=discord.ActivityType.watching, name="DEFY Servers")
    await client.change_presence(activity=act)
    client.loop.create_task(main())


# Classes
class Timespan(Enum):
    SECONDS = 1
    MINUTES = SECONDS * 60
    HOURS = MINUTES * 60
    DAYS = HOURS * 24
    WEEKS = DAYS * 7
    MONTHS = WEEKS * 4
    YEARS = MONTHS * 12


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
        info = sp.getInfo(self.address, self.port)
        self.maxPlayers = info["max_players"] if info else 32
        self.disconnected = []
        self.joined = []
        self.map = None
        self.maps = {}
        self.pings = {}

    def refresh(self):
        global startTime
        pingIndex = int((time.time() - startTime) * 1000)
        if not sp.isServerUp(self.address, self.port):
            self.players = {}
            self.online = False
            self.pings[pingIndex] = 0
            return
        self.online = True
        info = sp.getInfo(self.address, self.port)
        self.pings[pingIndex] = sp.ping(self.address, self.port)

        newMap = info["map"] if info else None

        if newMap:
            if newMap != self.map:
                self.maps[newMap] = 1 if map not in self.maps else self.maps[newMap] + 1
            self.map = newMap

        online = sp.getPlayers(self.address, self.port)
        self.playerNames = []
        if online:
            self.playerNames = sp.getPlayerNames(online)

        self.lastOnline = time.time()

        if self.oldPlayers == self.playerNames:
            return

        self.joined = getNewPlayers(self.oldPlayers, self.playerNames)
        self.disconnected = getMissingPlayers(self.oldPlayers, self.playerNames)

        for player in self.joined:
            p = Player().createNew(player)
            p.logon(self)
            self.players[player] = p

        for player in self.disconnected:
            if player not in self.players:
                continue
            p: Player = self.players[player]
            p.logoff()
            del self.players[player]

        self.oldPlayers = self.playerNames

        for player in self.players.values():
            player.save()

    def generatePlayerPlotValues(self, timespan=Timespan.MONTHS.value, sep=Timespan.HOURS.value,
                                 onlineFor=Timespan.MINUTES.value * 10):
        global players
        results = []
        minimum = time.time() - timespan
        separations = math.ceil(timespan / sep)
        index = 0

        while minimum < time.time():
            total = 0
            online = []
            for player in players:
                if player.wasOn(minimum - onlineFor, minimum) == self.name:
                    total += 1
                    online.append(player.name)
            if total or len(results):
                results.insert(separations - index, total)
            index += 1
            minimum += sep
        return results

    def generatePlayerPlot(self, timespan=Timespan.MONTHS.value, sep=Timespan.HOURS.value,
                           onlineFor=Timespan.MINUTES.value * 10):
        return generatePlot(self.generatePlayerPlotValues(timespan, sep, onlineFor),
                            self.name + "'s Player Count",
                            formatTime(sep), "Players")

    def generateLatencyPlot(self):
        values = []

        for t, value in sorted(list(self.pings.items()), key=lambda x: x[0], reverse=False):
            if t > 60 * 1000 * 20:
                print(t)
                break
            values.insert(int(t / 1000 / 60), value)
        return generatePlot(values, "{} Latency".format(self.name), "Minutes", "Ping")

    def __str__(self):
        return "[{}|{}|{}|{}|{}|{}]".replace("|", separator).format(self.name, self.address, self.port, self.lastOnline,
                                                                    self.online,
                                                                    self.playerNames)


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

    def wasOn(self, small, large):
        for sess in self.sessions[::-1]:
            if sess.timeOff < small:
                break
            if sess.timeOn > large:
                continue
            return sess.server

    def generatePlotValues(self, timespan=Timespan.MONTHS.value, sep=Timespan.DAYS.value):
        results = []
        small = time.time()
        separations = math.ceil(timespan / sep)
        index = 0

        used = []

        while small > time.time() - timespan:
            total = 0

            for sess in self.sessions[::-1]:
                sess: Session
                if sess.timeOn < small:
                    break
                if sess in used:
                    continue
                used.append(sess)
                total += sess.getTime()
            results.insert(separations - index, total / 60 / 60)

            index += 1
            small -= sep
        return results

    def generatePlot(self, timespan=Timespan.MONTHS.value, sep=Timespan.DAYS.value):
        plot = generatePlot(self.generatePlotValues(timespan, sep),
                            "{}'s Playtime ({})".format(self.name, formatTime(timespan)),
                            formatTime(int(sep)), "Hours")
        return plot

    def __str__(self):
        return "[{}\n{}]".format(self.name, "\n".join(self.sessions))

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, Player):
            return False
        return self.name == other.name

    def __lt__(self, other):
        return self.getFirstSeen() > other.getFirstSeen()


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

    def logoff(self):  # 9
        self.timeOff = time.time()

    def logon(self):
        self.timeOn = time.time()

    def __str__(self):
        return "[{}|{}|{}]".replace("|", separator).format(self.server, self.timeOn,
                                                           time.time() if self.timeOff == -1 else self.timeOff)


# Commands

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

        server = args[0] if args[0] in config["Servers"] else None

        for t in [Timespan.DAYS, Timespan.WEEKS, Timespan.MONTHS]:
            desc += "{}: {}\n".format("1 " + t.name.title()[:-1],
                                      formatTime(player.getTimeSince(t.value, server)))
        embed = createEmbed(player.name + "'s Information", "Online time since:\n" + desc, discord.Color.orange())

        embed.add_field(name="First Seen",
                        value=datetime.datetime.fromtimestamp(player.getFirstSeen(), tz=zone).strftime(
                            "%I:%M:%S %p %m/%d/%Y"))
        embed.add_field(name="Last Seen",
                        value=datetime.datetime.fromtimestamp(player.getLastSeen(), tz=zone).strftime(
                            "%I:%M:%S %p %m/%d/%Y"))

        serverRank = {}
        for sess in player.sessions:
            sess: Session
            serverRank[sess.server] = serverRank[
                                          sess.server] + sess.getTime() if sess.server in serverRank else sess.getTime()

        serverRank = dict(sorted(serverRank.items(), key=lambda kv: (kv[0], kv[1]), reverse=True))

        activeServers = ""

        for server, t in serverRank.items():
            activeServers += "{}: {}\n".format(server, formatTime(t))

        embed.add_field(name="All Time", value=activeServers, inline=False)

        return [await dUtils.sendMessage(msg.channel, embed),
                await msg.channel.send(file=player.generatePlot())]


class HelpCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        desc = ["Format: .[command] <args>", ""]

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


class GetNewPlayersCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        global players
        span = Timespan.DAYS.value
        if len(args) > 0:
            span = strToSeconds(" ".join(args))
        newPlayers = []
        minJoinTime = time.time() - span
        for player in players:
            if player.getFirstSeen() >= minJoinTime:
                newPlayers.append(player)

        result = []

        newPlayers = sorted(newPlayers)

        for player in newPlayers:
            result.append("{} joined {} ago".format(player.name, formatTime(time.time() - player.getFirstSeen())))

        pageable = dUtils.Pageable(result, "Players after {}".format(formatToDate(minJoinTime)), msg.author,
                                   msg.channel)
        pageable.color = discord.Color.dark_blue()
        return await pageable.send()


class DeletePlaytimeCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        if len(args) == 0:
            return [await dUtils.sendMessage(msg.channel, "Please specify a username or all")]

        p = getPlayer(" ".join(args))
        name = p.name if p else " ".join(args)

        if not os.path.exists(dir + "/players/" + slugify(name) + ".txt") and args[0] != "all":
            return await dUtils.sendMessage(msg.channel, "**{}** was not found.".format(dUtils.raw(name)))
        return await ConfirmDelete("Do you really want to delete **{}** player data?".format(dUtils.raw(name)),
                                   msg.author, slugify(name)).send(msg.channel)


class ConfirmDelete(dUtils.ConfirmMessage):
    def __init__(self, message, author, target):
        super().__init__(message, author)
        self.target = target

    async def confirm(self):
        global players
        if self.target == "all":
            shutil.rmtree(dir + "/players")
            players = []
            await updatePlayers()
            return await dUtils.sendMessage(self.sent.channel, "Successfully deleted all player data.")
        else:
            players = loadPlayers()
            await self.sent.channel.send("Successfully deleted player data of {}.".format(self.target),
                                         file=discord.File(dir + "/players/" + self.target + ".txt"))
            os.remove(dir + "/players/" + self.target + ".txt")


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
                leaderboard[p] = p.getTimeSince(span if span else -1)

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
            target = getPlayer(args[0])
            if target:
                span = strToSeconds(args[1])
                for p in players:
                    if span:
                        leaderboard[p] = p.getTimeSince(span)
                    elif args[1] in config["Servers"]:
                        leaderboard[p] = p.getTimeSince(-1, args[1])
                    else:
                        return await dUtils.sendMessage(msg.channel, "Unknown server/timespan.")
                result = generateLeaderboard(leaderboard)
                page = 0
                embed = dUtils.Pageable(result,
                                        "Leaderboard (" + (formatTime(span) if span else args[1]) + ")", msg.author,
                                        msg.channel,
                                        color=discord.Color.green())
                for index, line in enumerate(result):
                    if target.name in line:
                        page = math.ceil(index / embed.size) - 1
                        break
                embed.page = page

                return await embed.send()

            if args[0] in config["Servers"]:
                span = strToSeconds(args[1])

                for p in players:
                    leaderboard[p] = p.getTimeSince(span, args[0])
                result = generateLeaderboard(leaderboard)
                embed = dUtils.Pageable(result,
                                        "Leaderboard (" + args[0] + " | " + formatTime(span) + ")", msg.author,
                                        msg.channel,
                                        color=discord.Color.green())
                return await embed.send()
            return await dUtils.sendMessage(msg.channel, "Unknown arguments.")


class GraphCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        period = Timespan.DAYS.value

        if len(args) == 1 and args[0] in servers:
            server = servers[args[0]]
            return await msg.channel.send(file=server.generatePlayerPlot())

        if len(args) < 2:
            return await dUtils.sendMessage(msg.channel, "Please specify a player and timeframe.")

        pLength = 0

        for index, s in enumerate(args):
            if strToSeconds(s):
                pLength = index
                break
        player = getPlayer(" ".join(args[:pLength]))

        span = strToSeconds(args[pLength])
        if len(args) > pLength + 1:
            period = strToSeconds(args[-1])

        if args[0] in servers:
            server = servers[args[0]]
            return await msg.channel.send(server.generatePlayerPlot(span, period))

        if not player:
            return await dUtils.sendMessage(msg.channel, "No playtime data for {}.".format(" ".join(args[:pLength])))

        graph = player.generatePlot(span, period)
        return await msg.channel.send(file=graph)


class RefreshCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        global players
        players = loadPlayers()
        return await dUtils.sendMessage(msg.channel, "Successfully updated playtimes manually.")


class StatisticsCommand(dUtils.Command):
    async def exec(self, msg: discord.Message, args):
        global players, startTime, servers
        if len(args) == 0:
            embed = createEmbed("Player Statistics", "", discord.Color.green())
            embed.add_field(name="Total Players", value=str(len(players)))
            embed.add_field(name="Uptime", value=formatTime(time.time() - startTime))
            embed.add_field(name="Ping", value="{}".format(int(client.latency * 1000)))
            embed.add_field(name="Servers", value=", ".join(config["Servers"]))
            return await dUtils.sendMessage(msg.channel, embed)
        if args[0] not in config["Servers"]:
            return await dUtils.sendMessage(msg.channel, "Unknown server.")

        server = servers[args[0]]
        desc = ""
        maps = dict(sorted(server.maps.items(), key=lambda kv: (kv[0], kv[1])))

        knownPlayers = {}

        for player in players:
            for span in [Timespan.DAYS, Timespan.WEEKS, Timespan.MONTHS, Timespan.YEARS, -1]:
                index = -1 if span == -1 else span.value
                if player.getTimeSince(index, server.name):
                    knownPlayers[index] = knownPlayers[index] + 1 if index in knownPlayers else 1

        desc += "Total Players in:\n"

        for frame, amo in knownPlayers.items():
            desc += "{}: {:d}\n".format("All Time" if frame == -1 else formatTime(frame), amo)

        desc += "\nMaps\n"

        for m, value in maps.items():
            desc += "{}: {}\n".format(m, value)
            if desc.count("\n") > 5:
                break

        embed = createEmbed("Server Statistics {}".format(args[0]), desc, discord.Color.blue())

        down = 0
        for t in server.pings.values():
            if t == 0:
                down += 1

        embed.add_field(name="Uptime",
                        value="{}%".format(round(((len(server.pings) - down) / (len(server.pings)) * 100), 2)))

        await dUtils.sendMessage(msg.channel, embed)

        return await msg.channel.send(file=server.generateLatencyPlot())


def prepareConfig():
    global config
    if not os.path.exists(conDir):
        with open(conDir, "w+", encoding="utf-8") as config:
            yaml.dump(default, config, sort_keys=False)
    with open(conDir, encoding="utf-8") as cFile:
        config = yaml.full_load(cFile)


guildmessages = {}


async def sendPlaytimes(localServers):
    global guildmessages
    for server in localServers:
        for guild in client.guilds:
            if guild.id not in guildmessages.keys():
                guildmessages[guild.id] = {}
            if server.name not in guildmessages[guild.id].keys():
                guildmessages[guild.id][server.name] = None

            msg = "No Players" if server.online else "Offline"
            if server.online and server.playerNames:
                msg = "\n".join(cleanList(server.playerNames))

            newMessage = createEmbed(server.name + " Player List", msg,
                                     color=discord.Color.blue())

            footer = ""

            if server.joined:
                footer += "[+] " + ", ".join(server.joined)
                if server.disconnected:
                    footer += "\n"
            if server.disconnected:
                footer += "[-] " + ", ".join(server.disconnected)

            footer += "\nLast Updated at " + datetime.datetime.now(tz=zone).strftime("%I:%M %p")

            newMessage.set_footer(text=footer)
            if server.online:
                newMessage.add_field(name="Map", value=server.map)
                newMessage.add_field(name="Players", value=str(
                    len(server.players)) + "/" + str(server.maxPlayers))
            else:
                newMessage.add_field(name="Last Online", value=formatTime(time.time() - server.lastOnline))
            message: discord.Message = guildmessages[guild.id][server.name]

            channel: discord.TextChannel = getChannel(guild, config["ChannelName"])
            guild: discord.Guild

            if message is None:
                message = await channel.send(
                    embed=createEmbed(server.name + " Player List", "No Players", color=discord.Color.red()))

            if message is None:
                return
            guildmessages[guild.id][server.name] = message
            try:
                await message.edit(embed=newMessage)
            except discord.NotFound:
                pass


def generatePlot(data, title="Graph", xLabel="X", yLabel="Y"):
    plt.style.use("dark_background")
    plt.clf()
    plt.title(title)
    plt.plot(data)
    plt.ylabel(yLabel)
    plt.xlabel(xLabel)
    plt.savefig("output")
    return discord.File("output.png")


def createEmbed(title, desc, color=discord.Colour.default(), url=None):
    return discord.Embed(title=title, description=desc, color=color, url=url)


def getChannel(guild, name):
    for channel in guild.text_channels:
        if channel.name == name:
            return channel


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


def cleanList(l):
    while "" in l:
        l.remove("")
    return l


def loadPlayers():
    if not os.path.exists(dir + "/players"):
        return
    plist = []
    for file in os.listdir(dir + "/players"):
        with open(dir + "/players/" + file, encoding="utf-8") as f:
            text = f.read()
            if not text:
                continue
            player = Player().construct(text)
            plist.append(player)
    return plist


def getPlayer(name):
    global players
    for player in players:
        if player.name == name or slugify(player.name) == slugify(name):
            return player

    for player in players:
        if slugify(name) in slugify(player.name):
            return player


def formatToDate(time):
    return datetime.datetime.fromtimestamp(time).strftime("%I:%M:%S %p %m/%d/%Y")


def playerSort(a: Player, b: Player):
    return -1 if a.getTimeSince(-1) > b.getTimeSince(-1) else 1


def formatTime(seconds: int):
    result: Timespan = Timespan.SECONDS
    for t in Timespan:
        t: Timespan
        if seconds >= t.value:
            result = t
    if seconds == result.value:
        return "1 " + result.name.title()[:-1]
    return "{:0.2f} {}".format(seconds / result.value, result.name.title())


def generateLeaderboard(plist):
    ps = sorted(plist.items(), key=lambda kv: kv[1], reverse=True)
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


async def updatePlayers():
    global players
    while True:
        if players:
            for player in players:
                player.save()
        players = loadPlayers()
        await asyncio.sleep(60)


if __name__ == "__main__":
    prepareConfig()
    client.run(config["Token"])
