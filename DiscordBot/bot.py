# bot.py
import collections
import discord
from discord.ext import commands
import os
import json
import logging
import re
from queue import PriorityQueue
from report import Report
from moderate_report import ModerateReport

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(
    filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter(
    '%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# There should be a file called 'tokens.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']


class ModBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {}  # Map from guild to the mod channel id for that guild
        self.reports = {}  # Map from user IDs to the state of their report

        self.pending_moderation = PriorityQueue()
        self.moderations = {}

        # Maps from user ID to the number of offenses they have committed
        self.num_offenses = collections.defaultdict(int)

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        # Parse the group number out of the bot's name
        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception(
                "Group number not found in bot's name. Name format should be \"Group # Bot\".")

        # Find the mod channel in each guild that this bot should report to
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel

    async def on_message(self, message):
        '''
        This function is called whenever a message is sent in a channel that the bot can see (including DMs). 
        Currently the bot is configured to only handle messages that are sent over DMs or in your group's "group-#" channel. 
        '''
        # Ignore messages from the bot
        if message.author.id == self.user.id:
            return

        # Check if this message was sent in a server ("guild") or if it's a DM
        if message.guild:
            await self.handle_channel_message(message)
        else:
            await self.handle_dm(message)

    async def handle_dm(self, message):
        # Handle a help message
        if message.content == Report.HELP_KEYWORD:
            reply = "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return

        author_id = message.author.id
        responses = []

        # Only respond to messages if they're part of a reporting flow
        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        # If we don't currently have an active report for this user, add one
        if author_id not in self.reports:
            # TODO: CHeck if this is how you get the author's name
            self.reports[author_id] = Report(self, message.author)

        report = self.reports[author_id]

        # Let the report class handle this message; forward all the messages it returns to uss
        responses = await report.handle_message(message)
        for r in responses:
            if isinstance(r, str):
                await message.channel.send(r)
            elif r.get("view", None):
                await message.channel.send(r.get("text"), view=r.get("view"))
            else:
                await message.channel.send(r.get("text"))

        # If the report is complete or cancelled, remove it from our map
        if report.report_complete():

            # If it wasn't canceled then the report need to be moderated
            if not report.report_canceled():

                self.pending_moderation.put(
                    (report.calculate_report_severity() * - 1, report))

                message = f"There's a new report from {message.author.name}!\n"
                message += f"There are now {self.pending_moderation.qsize()} report(s) in the queue.\n\n\n"

                await self.mod_channels[report.get_guild_id()].send(message)

                self.num_offenses[report.reported_message.author.id] += 1

            self.reports.pop(author_id)

    async def handle_channel_message(self, message):

        if message.channel.name == f'group-{self.group_num}-mod':
            author_id = message.author.id

            if self.pending_moderation.empty() and author_id not in self.moderations:
                await message.channel.send("No reports to moderate! Rest easy :)")
                return

            if author_id not in self.moderations and not message.content.startswith(ModerateReport.START_KEYWORD):
                return

            if author_id not in self.moderations:
                # Pop a report from the queue
                report = self.pending_moderation.get()[1]

                # Assign the moderator
                self.moderations[author_id] = ModerateReport(self, report)

            responses = await self.moderations[author_id].handle_message(message)
            for r in responses:
                if isinstance(r, str):
                    await message.channel.send(r)
                elif r.get("view", None):
                    await message.channel.send(r.get("text"), view=r.get("view"))
                else:
                    await message.channel.send(r.get("text"))

            if self.moderations[author_id].moderate_complete():
                await message.channel.send(f"There are {self.pending_moderation.qsize()} report(s) remaining.")
                self.moderations.pop(author_id)

            return

        # Only handle messages sent in the "group-#" channel
        if not message.channel.name == f'group-{self.group_num}':
            return

        # Forward the message to the mod channel
        mod_channel = self.mod_channels[message.guild.id]
        await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')
        scores = self.eval_text(message.content)
        await mod_channel.send(self.code_format(scores))

    def eval_text(self, message):
        ''''
        TODO: Once you know how you want to evaluate messages in your channel, 
        insert your code here! This will primarily be used in Milestone 3. 
        '''
        return message

    def code_format(self, text):
        ''''
        TODO: Once you know how you want to show that a message has been 
        evaluated, insert your code here for formatting the string to be 
        shown in the mod channel. 
        '''
        return "Evaluated: '" + text + "'"


client = ModBot()
client.run(discord_token)
