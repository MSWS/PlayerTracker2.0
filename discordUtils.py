from abc import abstractmethod
from discord.ext import commands

import discord
import math
import traceback

client: commands.Bot
registeredCommands = {}


def init(_client: commands.Bot):
    global client
    if not _client.is_ready():
        raise ValueError("Client must be ready")
    client = _client

    @client.listen()
    async def on_message(msg: discord.Message):
        if not msg.content.startswith(client.command_prefix):
            return
        cmdName = raw(msg.content.split(" ")[0][1:])
        cmd: Command = getCommand(cmdName)
        args = msg.content.split(" ")[1:]
        if cmd is None:
            await msg.channel.send("Unknown Command: **{}**.".format(cmdName))
            return

        if not cmd.hasPerm(msg.author):
            msg: discord.Message = (await sendMessage(msg.channel,
                                                      "You need the `{}` permission to execute this command.".format(
                                                          cmd.permission)))[0]
            # await msg.delete(5)
            await msg.delete(delay=5)
            # await (await msg.channel.send(
            #     "You need the `{}` permission to execute this command.".format(cmd.permission))).delete(5)
            return

        async with msg.channel.typing():
            try:
                lines = await cmd.exec(msg, args)
                if lines is None:
                    await msg.channel.send("```Warning!\n {} returned None instead of []```".format(cmd.name))

                if cmd.autoDelete:
                    await msg.delete(delay=cmd.autoDelete)
                    if lines is not None and len(lines) > 0:
                        for line in lines:
                            await line.delete(delay=cmd.autoDelete)
            except Exception:
                error = raw(traceback.format_exc())
                await msg.channel.send(
                    "An error occured trying to execute {}\n```{}```".format(cmd.name, error))


def raw(s):
    return discord.utils.escape_mentions(discord.utils.escape_mentions(s))


def getTextChannel(guild: discord.Guild, target):
    for channel in guild.text_channels:
        if channel.name == target:
            return channel


async def sendMessage(target, message):
    if isinstance(target, discord.TextChannel):
        target: discord.TextChannel
        if isinstance(message, discord.Embed):
            return [await target.send(embed=message)]
        else:
            return [await target.send(message)]
    else:
        result = []
        for guild in client.guilds:
            guild: discord.Guild
            channel = getTextChannel(guild, target)
            if channel is None:
                channel = await guild.create_text_channel(target)
            if isinstance(message, discord.Embed):
                result.append(await channel.send(embed=message))
            else:
                result.append(await channel.send(message))

        return result


class Command(object):
    def __init__(self, name, description, usage="", aliases=None, autoDelete=0, permission=None):
        if aliases is None:
            aliases = []
        self.name = name
        self.aliases = aliases
        self.description = description
        self.autoDelete = autoDelete
        self.permission = permission
        self.usage = client.command_prefix + name if usage == "" else client.command_prefix + usage

    @abstractmethod
    async def exec(self, msg: discord.Message, args):
        """This should return a list of messages to delete if autoDelete is true"""
        return []

    def hasPerm(self, member: discord.Member):
        if not self.permission:
            return True
        return getattr(member.guild_permissions, self.permission, False)


class PageableEmbeds(object):
    def __init__(self, embeds, author, channel):
        self.embeds = embeds
        self.author = author
        self.channel = channel
        self.page = 0
        self.message = None
        self.waitForNumber = None

        @client.listen()
        async def on_reaction_add(reaction: discord.Reaction, user: discord.Member):
            if reaction.message.id != self.message.id:
                return
            if user != self.author:
                return

            emoji = reaction.emoji
            oldPage = self.page
            if emoji == "⏮" and self.page > 0:
                self.page = 0
            if emoji == "⬅" and self.page > 0:
                self.page -= 1
            if emoji == "❌":
                await reaction.message.delete()
                return
            if emoji == "➡" and self.page < len(self.embeds):
                self.page += 1
            if emoji == "⏭":
                self.page = len(self.embeds) - 1
            if emoji == "🔢":
                self.waitForNumber = (await sendMessage(reaction.message.channel, "Page?"))[0]
            await reaction.message.remove_reaction(reaction.emoji, user)
            if oldPage == self.page:
                return
            await self.send()

        @client.listen()
        async def on_message(msg: discord.Message):
            if msg.author != self.author:
                return
            if not self.waitForNumber:
                return
            if not msg.clean_content.isnumeric():
                return
            await msg.delete()
            p = int(msg.clean_content) - 1
            if p < 0 or p >= len(self.embeds):
                toDelete = (await sendMessage(msg.channel, "Invalid page."))[0]
                await toDelete.delete(delay=5)
                return
            self.page = p
            await self.waitForNumber.delete()
            await self.send()

    async def send(self):
        if self.message is not None:
            return await self.message.edit(embed=self.embeds[self.page])
        self.message = (await sendMessage(self.channel, self.embeds[self.page]))[0]
        if len(self.embeds) == 1:
            return self.message
        toAdd = ["⏮", "⬅", "❌", "➡", "⏭", "🔢"]
        for emoji in toAdd:
            await self.message.add_reaction(emoji)
        return self.message


class Pageable(object):
    def __init__(self, lines, title, author, channel, size=10, color=discord.Color.default()):
        self.lines = lines
        self.title = title
        self.author = author
        self.size = size
        self.page = 0
        self.color = color
        self.channel = channel
        self.message = None
        self.waitForNumber = None

        @client.listen()
        async def on_reaction_add(reaction: discord.Reaction, user: discord.Member):
            if not reaction or not self.message:
                return
            if reaction.message.id != self.message.id:
                return
            if user != self.author:
                return
            lastPage = math.ceil(len(self.lines) / self.size) - 1

            emoji = reaction.emoji
            oldPage = self.page
            if emoji == "⏮" and self.page > 0:
                self.page = 0
            if emoji == "⬅" and self.page > 0:
                self.page -= 1
            if emoji == "❌":
                await reaction.message.delete()
                return
            if emoji == "➡" and self.page < lastPage:
                self.page += 1
            if emoji == "⏭":
                self.page = lastPage
            if emoji == "🔢":
                self.waitForNumber = (await sendMessage(reaction.message.channel, "Page?"))[0]
            await reaction.message.remove_reaction(reaction.emoji, user)
            if oldPage == self.page:
                return
            await self.send()

        @client.listen()
        async def on_message(msg: discord.Message):
            if msg.author != self.author:
                return
            if not self.waitForNumber:
                return
            if not msg.clean_content.isnumeric():
                return
            await msg.delete()
            p = int(msg.clean_content) - 1
            if p < 0 or p > math.ceil(len(self.lines) / self.size) - 1:
                toDelete = (await sendMessage(msg.channel, "Invalid page."))[0]
                await toDelete.delete(delay=5)
                return
            self.page = p
            await self.waitForNumber.delete()
            await self.send()

    async def send(self):
        if self.message is not None:
            return await self.message.edit(embed=self.getEmbed())
        self.message = (await sendMessage(self.channel, self.getEmbed()))[0]
        if len(self.lines) < self.size:
            return self.message
        toAdd = ["⏮", "⬅", "❌", "➡", "⏭", "🔢"]
        for emoji in toAdd:
            await self.message.add_reaction(emoji)
        return self.message

    def getEmbed(self):
        lines = self.lines[self.page * self.size:min((self.page + 1) * self.size, len(self.lines))]
        desc = ""
        for line in lines:
            desc += line + "\n"
        embed = discord.Embed(title=self.title, description=desc, color=self.color)
        embed.set_footer(text="Page {} of {}".format(self.page + 1, math.ceil(len(self.lines) / self.size)))
        return embed


class ConfirmMessage(object):
    def __init__(self, message, author):
        self.message = message
        self.sent = None
        self.author = author

    async def send(self, channel):
        self.sent = (await sendMessage(channel, self.message))[0]
        await self.sent.add_reaction("✅")
        await self.sent.add_reaction("❌")

        @client.listen()
        async def on_reaction_add(reaction: discord.Reaction, user: discord.Member):
            if reaction.message.id != self.sent.id:
                return
            if user != self.author:
                return
            await reaction.message.remove_reaction(reaction.emoji, user)
            if reaction.emoji == "✅":
                await self.confirm()
            elif reaction.emoji == "❌":
                await reaction.message.delete()

        return self.sent

    @abstractmethod
    async def confirm(self):
        pass


def registerComand(cmd):
    registeredCommands[cmd.name] = cmd


def getCommand(name):
    if name.lower() in registeredCommands.keys():
        return registeredCommands[name.lower()]

    for cmd in registeredCommands.values():
        if cmd.name.lower() == name.lower():
            return cmd
        for alias in cmd.aliases:
            if alias.lower() == name.lower():
                return cmd
