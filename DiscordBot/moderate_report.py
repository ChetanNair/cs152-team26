from enum import Enum, auto
from discord.components import SelectOption
from discord.ui import Select, View
from report import Report


class State(Enum):
    MODERATE_START = auto()
    IMMINENT_DANGER = auto()
    NOTIFY_AUHTORITIES = auto()
    NOTIFY_AUHTORITIES_COMPLETE = auto()
    AWAITING_ACTIONS = auto()
    AWAITING_ACTION_REASON = auto()
    CHILD_GROOMING_REPORT = auto()
    LEGITIMATE_REPORT = auto()
    INCLUDE_ACTION_REASON = auto()
    MODERATE_COMPLETE = auto()


class ModerateReport:
    START_KEYWORD = "moderate"
    SHOW_REPORTS_KEYWORD = "show reports"

    def __init__(self, client, report):
        self.state = State.MODERATE_START
        self.client = client
        self.report = report
        self.selected_actions = []
        self.moderation_reasons = None
        self.num_offenses = 1

    async def handle_message(self, message, num_offenses):
        '''
        This function makes up the meat of the moderator-side reporting flow. It defines how we transition between states and what 
        prompts to offer at each of those states.
        '''

        self.num_offenses = num_offenses

        if self.state == State.MODERATE_START:
            reply = "Thank you for starting the moderating process. \n"
            reply += f"Please review the following report filed by {self.report.author.name}:\n\n\n"
            reply += f"{self.report.compile_report_to_moderate(num_offenses)}"
            reply += f"Does this seem like a legitimate report that you'd like to proceed with? (Yes/no)"
            self.state = State.LEGITIMATE_REPORT
            return [reply]

        # TODO: Implement the rest of the flow

        if self.state == State.LEGITIMATE_REPORT:
            if 'y' in message.content.lower():
                self.state = State.NOTIFY_AUHTORITIES
                return ["Based on the details from the report, do you think the user or others are in imminent danger? \n(Local authorities will be given a report if you say yes to this.) (Yes/No)\n"]

            self.state = State.MODERATE_COMPLETE
            response = f"Thank you for your input. The report will passed onto another team to investigate wrongful reporting. \n\n\n"
            response += "Moderation is complete!"
            return [response]

        if self.state == State.NOTIFY_AUHTORITIES:
            if 'y' in message.content.lower():
                self.state = State.AWAITING_ACTIONS
                return ["Please include a short description to send to the authorities along with the rest of the report.\n"]
            else:
                self.state = State.AWAITING_ACTIONS
                return [{'text': "Thank you for your input. Based on the info given please select the necessary actions. \n\n\n", 'view': self.generate_moderator_action_menu()}]

        if self.state == State.AWAITING_ACTIONS:
            return [{'text': "Thank you for your input. Based on the info given please select the necessary actions. \n\n\n", 'view': self.generate_moderator_action_menu()}]

        if self.state == State.NOTIFY_AUHTORITIES_COMPLETE:
            self.state = State.AWAITING_ACTION_REASON
            response = "A report will be compiled and forwarded to the authorities. \n\n"
            # Message to permanently ban the user
            await self.send_DM(self.report.reported_message.author.id, "You have been temporarily banned from the platform while we investigate a violation of our platform policies. \n")
            response += f"{self.report.reported_message.author.name} has been temporarily banned from the platform and has been notified. \n\n"

            response += "Please explain why you chose to report the case to the authorities so that other teams can verify the moderation!\n"
            return [response]

        if self.state == State.AWAITING_ACTION_REASON:
            self.moderation_reasons = message.content
            self.state = State.MODERATE_COMPLETE
            response = "Thank you for your response. All necessary actions will be taken.\n"

            if 'permanent_ban' in self.selected_actions:
                await self.send_DM(self.report.reported_message.author.id, "You have been permanently banned from the platform while we investigate a violation of our platform policies. \n")

            if 'block' in self.selected_actions:
                await self.send_DM(self.report.author.id, f"{self.report.reported_message.author.name} has been blocked.")

            if 'temporary_ban' in self.selected_actions:
                await self.send_DM(self.report.author.id, f"You have been temporarily banned from the platform while we investigate a violation of our platform policies. \n")
                
            if 'warn' in self.selected_actions:
                await self.send_DM(self.report.author.id, f"You are being warned for violating our platform policies. More information on this will be provided soon. \n")

            response += "The moderation is compelete!\n"
            return [response]

        return []

    def generate_moderator_action_menu(self):
        async def callback(interaction):
            self.selected_actions = select_menu.values

            self.state = State.AWAITING_ACTION_REASON
            response = "Please include your reasons for taking these actions: \n"
            await interaction.response.send_message(response)

        choices = [
            SelectOption(
                label='Permanently ban the offender',
                description="Permanently remove the user from platform.",
                value='permanent_ban',
                emoji="🚫"
            ),
            SelectOption(
                label='Temporarily ban the offender',
                description="Temporarily remove the user from platform.",
                value='temp_ban',
                emoji="🚫"
            ),
            SelectOption(
                label='Warn the offender',
                description="Issue a warning to the offender",
                value='warn',
                emoji="⚠️"
            ),
            SelectOption(
                label='Block the offender',
                description="Prevent the user from interacting with the victim.",
                value='block',
                emoji="🚷"
            ),
        ]

        select_menu = Select(
            min_values=0,
            max_values=4,
            placeholder='Please select action(s) against the reported user',
            options=choices,
            custom_id='user_action_menu',
        )

        select_menu.callback = callback
        view = View()
        view.add_item(select_menu)
        return view

    async def send_DM(self, user_id, message_content):
        user = await self.client.fetch_user(user_id)
        dm_channel = await user.create_dm()
        await dm_channel.send(message_content)

    def moderate_complete(self):
        return self.state == State.MODERATE_COMPLETE
