import collections
import discord
from discord.ext import commands
import os
import json
import logging
import re
import sqlite3
from types import SimpleNamespace
from collections import deque
from queue import PriorityQueue
from report import Report, SpecificAbuseType, BroadAbuseType, State
from moderate_report import ModerateReport
from claude import query, PROMPTS
from perspective import get_perspective_scores

BOT_AUTHOR_ID = 0
PERSPECTIVE_SCORE_THRESHOLD = 0.5

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
        self.context_window = CONTEXT_WINDOW_SIZE
        self.messages = deque()  # List of tuples of user ids and conversations
        self.context_window = CONTEXT_WINDOW_SIZE
        self.messages = deque() # List of tuples of user ids and conversations

        # Maps from user ID to the number of offenses they have committed
        self.num_offenses = collections.defaultdict(int)

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception(
                "Group number not found in bot's name. Name format should be \"Group # Bot\".")

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

        if message.guild:
            await self.handle_channel_message(message)
        else:
            await self.handle_dm(message)

    async def handle_dm(self, message):
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
            self.reports[author_id] = Report(self, message.author)

        report = self.reports[author_id]

        # Let the report class handle this message; forward all the messages it returns to us
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

                response = f"There's a new report from {message.author.name}!\n"
                response += f"There are {self.pending_moderation.qsize()} report(s) in the queue.\n\n"
                response += "Type \"show reports\" to see them or \"moderate\" to start moderating. \n\n\n"

                await self.mod_channels[report.get_guild_id()].send(response)

                self.num_offenses[report.reported_message.author.id] += 1

                # Save the report details to the database
                report_id = self.save_report_to_db(message.author.id, report)
                report.report_id = report_id  # Assign the generated report_id to the report

            self.reports.pop(author_id)

    async def handle_channel_message(self, message):
        if message.channel.name == f'group-{self.group_num}-mod':
            regex_command = await self.parse_for_regex_commands(message)
            if regex_command:
                return
            author_id = message.author.id

            if self.pending_moderation.empty() and author_id not in self.moderations:
                await message.channel.send("No reports to moderate! Rest easy :)")
                return

            if message.content == ModerateReport.SHOW_REPORTS_KEYWORD:
                for index, tup in enumerate(list(self.pending_moderation.queue)):
                    _, report = tup
                    await message.channel.send(f"{index + 1}. {report.compile_summary()}")
                response = f"There are {self.pending_moderation.qsize()} report(s) in the queue.\n\n"
                response += "Type \"show reports\" to see them or \"moderate\" to start moderating. \n\n\n"
                await message.channel.send(response)
                return

            if author_id not in self.moderations and not message.content.startswith(ModerateReport.START_KEYWORD):
                return

            if author_id not in self.moderations:
                # Pop a report from the queue in order of severity
                report = self.pending_moderation.get()[1]
                # Assign the moderator
                self.moderations[author_id] = ModerateReport(self, report, message.author)

            responses = await self.moderations[author_id].handle_message(message, self.num_offenses[self.moderations[author_id].report.reported_message.author.id])
            for r in responses:
                if isinstance(r, str):
                    await message.channel.send(r)
                elif r.get("view", None):
                    await message.channel.send(r.get("text"), view=r.get("view"))
                else:
                    await message.channel.send(r.get("text"))

            if self.moderations[author_id].moderate_complete():
                await message.channel.send(f"There are {self.pending_moderation.qsize()} report(s) remaining.")
                self.save_moderation_to_db(self.moderations[author_id])
                self.moderations.pop(author_id)
            return

        if not message.channel.name == f'group-{self.group_num}':
            return

        if len(self.messages) == CONTEXT_WINDOW_SIZE:
            self.messages.popleft()
        self.messages.append((message.author.id, message.content, message))

        guild_id = message.guild.id
        c.execute('SELECT pattern FROM regex_rules WHERE guild_id = ?', (guild_id,))
        rules = c.fetchall()
        for rule in rules:
            pattern = rule[0]
            if re.search(pattern, message.content):
                await message.delete()
                mod_channel = self.mod_channels[message.guild.id]
                await mod_channel.send(f'Message from {message.author.name} deleted: "{message.content}" matched rule "{pattern}"')
                return

        mod_channel = self.mod_channels[message.guild.id]
        scores = self.eval_text(self.messages)

        if scores == "NO VIOLATION":
            perspective_scores = get_perspective_scores(message.content)
            perspective_violation = True in [
                ele > PERSPECTIVE_SCORE_THRESHOLD for ele in list(perspective_scores.values())]
            if perspective_scores is not None and perspective_violation:
                await message.delete()
                mod_channel = self.mod_channels[message.guild.id]
                formatted_scores = "\n".join(
                    [f"{attribute}: {score:.2f}" for attribute, score in perspective_scores.items()])
                await mod_channel.send(
                    f'Message from:\n'
                    f'{message.author.name}: "{message.content}"\n\n'
                    f'Perspective scores:\n'
                    f'{formatted_scores}\n\n'
                    f'This message has been deleted and the user should be reviewed.'
                )
                return
            return

        await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')
        scores = self.eval_text(self.messages)
        await mod_channel.send(self.code_format(scores))

    async def parse_for_regex_commands(self, message):
        if message.content.startswith("add_regex "):
            pattern = message.content[len("add_regex "):].strip()
            c.execute('''
            INSERT INTO regex_rules (guild_id, pattern)
            VALUES (?, ?)
            ''', (message.guild.id, pattern))
            conn.commit()
            await message.channel.send(f'Regex rule "{pattern}" added successfully.')
            return True

        elif message.content.startswith("remove_regex "):
            pattern = message.content[len("remove_regex "):].strip()
            c.execute('''
            DELETE FROM regex_rules
            WHERE guild_id = ? AND pattern = ?
            ''', (message.guild.id, pattern))
            conn.commit()
            await message.channel.send(f'Regex rule "{pattern}" removed successfully.')
            return True
        return False

    def eval_text(self, messages):
        conversation = ""
        for message in messages:
            user_id, message = message[0], message[1]
            conversation += f"User #{user_id}: {message}"

        violation = query(conversation=PROMPTS["system_message"].format(content_policy=PROMPTS["content_policy"],
                                                                        instructions=PROMPTS["instructions"].format(conversation=conversation)), assistant_completion="")
        if "NO_VIOLATION" in violation:
            return "NO VIOLATION"

        author = SimpleNamespace(**{"name": "MOD_BOT", "id": BOT_AUTHOR_ID})

        # If we don't currently have an active report for this user, add one
        if BOT_AUTHOR_ID not in self.reports:
            self.reports[BOT_AUTHOR_ID] = Report(self, author)

        report = self.reports[BOT_AUTHOR_ID]

        first_question = "Which of these violations does this conversation violate: SPAM, EXPLICIT_CONTENT, THREAT, or HARASSMENT? Please say one and only one violation, and nothing more."
        first_assistant_completion = "VIOLATION TYPE:"
        first_answer = query(conversation=PROMPTS["gen_system_message"].format(conversation=conversation, question=first_question),
                             assistant_completion=first_assistant_completion)

        if "SPAM" in first_answer:
            broad_abuse = BroadAbuseType.SPAM
        elif "EXPLICIT_CONTENT" in first_answer:
            broad_abuse = BroadAbuseType.EXPLICIT_CONTENT
        elif "THREAT" in first_answer:
            broad_abuse = BroadAbuseType.THREAT
        elif "HARASSMENT" in first_answer:
            broad_abuse = BroadAbuseType.HARASSMENT

        suffix = "Please say one and only one type. You must choose a type."
        second_assistant_completion = "TYPE:("
        if "SPAM" in first_answer:
            second_question = f"Which type of spam is the conversation: SCAM, BOTMESSAGES, SOLICITING, IMPERSONATION, or MISINFORMATION? {suffix}"
        elif "EXPLICIT" in first_answer:
            second_question = f"Which type of explicit content is the conversation: SEXUAL_CONTENT, VIOLENCE, or HATE_SPEECH? {suffix}"
        elif "THREAT" in first_answer:
            second_question = f"Which type of threat is it: SELF_HARM, TERRORIST_PROPAGANDA, or DOXXING? {suffix}"
        elif "HARASSMENT" in first_answer:
            second_question = f"Which type of harassment is it: BULLYING, SEXUAL, CONTINUOUS_CONTACT, or CHILD_GROOMING? {suffix}"
        else:
            raise Exception("Failure to pick from options")

        second_answer = query(conversation=PROMPTS["gen_system_message"].format(conversation=conversation, question=second_question),
                              assistant_completion=second_assistant_completion)

        if "SCAM" in second_answer:
            abuse_type = SpecificAbuseType.SCAM
        elif "BOT" in second_answer:
            abuse_type = SpecificAbuseType.BOTMESSAGES
        elif "SOLICIT" in second_answer:
            abuse_type = SpecificAbuseType.SOLICITATION
        elif "IMPERSON" in second_answer:
            abuse_type = SpecificAbuseType.IMPERSONATION
        elif "MISINFOR" in second_answer:
            abuse_type = SpecificAbuseType.MISINFORMATION
        elif "SEXUAL_CONT" in second_answer:
            abuse_type = SpecificAbuseType.SEXUAL_CONTENT
        elif "VIOLENCE" in second_answer:
            abuse_type = SpecificAbuseType.VIOLENCE
        elif "HATE" in second_answer:
            abuse_type = SpecificAbuseType.HATE_SPEECH
        elif "SELF_HARM" in second_answer:
            abuse_type = SpecificAbuseType.SELF_HARM
        elif "TERRORIST" in second_answer:
            abuse_type = SpecificAbuseType.TERRORIST_PROPAGANDA
        elif "DOXX" in second_answer:
            abuse_type = SpecificAbuseType.DOXXING
        elif "BULLY" in second_answer:
            abuse_type = SpecificAbuseType.BULLYING
        elif "SEXUAL" in second_answer:
            abuse_type = SpecificAbuseType.SEXUAL
        elif "CONTINOUS" in second_answer:
            abuse_type = SpecificAbuseType.CONTINUOUS_CONTACT
        elif "GROOMING" in second_answer:
            abuse_type = SpecificAbuseType.GROOMING
        else:
            raise Exception("Failure to pick from options")

        third_question = f"Based on the conversation, is there an immediate and direct danger to someone's safety? Please just answer either YES or NO."
        third_answer = query(conversation=PROMPTS["gen_system_message"].format(
            conversation=conversation, question=third_question))

        signals = []
        if abuse_type == SpecificAbuseType.GROOMING:
            child_grooming_info = []
            suffix = "Please just answer either YES, NO, or UNCLEAR."
            assistant_comp = "Answer:("

            first_grooming_question = f"Considering the conversation, have pictures been exchanged in the conversation? {suffix}"
            first_grooming_answer = query(conversation=PROMPTS["gen_system_message"].format(conversation=conversation, question=first_grooming_question),
                                          assistant_completion=assistant_comp)
            child_grooming_info.append(
                (first_grooming_answer, "pictures_exchanged"))

            second_grooming_question = f"Considering the conversation, have the people in the conversation met in real life? {suffix}"
            second_grooming_answer = query(conversation=PROMPTS["gen_system_message"].format(conversation=conversation, question=second_grooming_question),
                                           assistant_completion=assistant_comp)
            child_grooming_info.append(
                (second_grooming_answer, "met_in_real_life"))

            third_grooming_question = f"Considering the conversation, has one user asked another user personal questions? {suffix}"
            third_grooming_answer = query(conversation=PROMPTS["gen_system_message"].format(conversation=conversation, question=third_grooming_question),
                                          assistant_completion=assistant_comp)
            child_grooming_info.append(
                (third_grooming_answer, "personal_questions_asked"))

            fourth_grooming_question = f"Is the conversation severe enough to the point where one user should be notified that they are being groomed? {suffix}"
            fourth_grooming_answer = query(conversation=PROMPTS["gen_system_message"].format(conversation=conversation, question=fourth_grooming_question),
                                           assistant_completion=assistant_comp)
            child_grooming_info.append(fourth_grooming_answer)

            for (answer, indicator) in child_grooming_info:
                if "Y" in answer:
                    signals.append(indicator)

        # Populate the fields of the report to send to the mod channel
        report.guild_id = messages[-1][2].guild.id

        report.reported_message = self.messages[-1][2]
        report.abuse_type = broad_abuse
        report.specific_abuse_type = abuse_type

        report.child_grooming_info = signals
        report.danger_indicated = "Y" in third_answer

        report.permission_given = False
        report.specific_abuse_type = abuse_type
        report.state = State.REPORT_COMPLETE

        self.pending_moderation.put(
            (report.calculate_report_severity() * - 1, report))

        response = f"There's a new report from the MOD_BOT!\n"
        response += f"There are {self.pending_moderation.qsize()} report(s) in the queue.\n\n"
        response += "Type \"show reports\" to see them or \"moderate\" to start moderating. \n\n\n"

        return response

    def code_format(self, text):
        return text

    def save_report_to_db(self, user_id, report):
        c.execute('''
        INSERT OR IGNORE INTO users (user_id, age, num_friends, hours_logged, new_chats_last_day, num_reports, num_violations, severity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, None, None, None, None, 0, 0, 0))

        c.execute('''
        INSERT OR IGNORE INTO users (user_id, age, num_friends, hours_logged, new_chats_last_day, num_reports, num_violations, severity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (report.reported_message.author.id, None, None, None, None, 0, 0, 0))

        c.execute('''
        UPDATE users
        SET num_reports = num_reports + 1
        WHERE user_id = ?
        ''', (user_id,))

        c.execute('''
        UPDATE users
        SET num_violations = num_violations + 1
        WHERE user_id = ?
        ''', (report.reported_message.author.id,))

        c.execute('''
        UPDATE users
        SET severity = COALESCE(severity, 0) + ?
        WHERE user_id = ?
        ''', (report.calculate_report_severity(), report.reported_message.author.id))

        c.execute('''
        INSERT INTO reports (user_id, reported_user_id, violation_type, severity, status, immediate_danger, permission_given)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, report.reported_message.author.id, report.specific_abuse_type, report.calculate_report_severity(), "OPEN", report.danger_indicated, report.permission_given))

        report_id = c.lastrowid

        conn.commit()

        return report_id

    def save_moderation_to_db(self, moderation):
        c.execute('''
        INSERT INTO moderations (report_id, moderator_id, action_taken, justification, severity)
        VALUES (?, ?, ?, ?, ?)
        ''', (moderation.report.report_id, moderation.moderator.id, ' '.join(moderation.selected_actions), moderation.moderation_reasons, moderation.report.calculate_report_severity()))

        c.execute('''
        UPDATE reports
        SET status = 'CLOSED'
        WHERE report_id = ?
        ''', (moderation.report.report_id,))

        conn.commit()


client = ModBot()
client.run(discord_token)
