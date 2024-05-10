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
    MODERATE_COMPLETE = auto()


class ModerateReport:
    START_KEYWORD = "moderate"
    CANCEL_KEYWORD = "cancel"
    HELP_KEYWORD = "help"  # TODO: Impleement help message

    def __init__(self, client, report):
        self.state = State.MODERATE_START
        self.client = client
        self.report = report

    async def handle_message(self, message):
        '''
        This function makes up the meat of the moderator-side reporting flow. It defines how we transition between states and what 
        prompts to offer at each of those states.
        '''

        # TODO: Handle the cancel keyword
        # if message.content == self.CANCEL_KEYWORD:
        #     self.state = State.REPORT_COMPLETE
        #     return ["Report cancelled."]

        if self.state == State.MODERATE_START:
            reply = "Thank you for starting the moderating process. \n"
            reply += f"Please review the following report filed by {self.report.author.name}:\n\n\n"
            reply += f"{self.report.compile_report_to_moderate()}"
            # TODO: Maybe change this to a view
            reply += f"Does this seem like a genuine report that you'd like to proceed with? (Yes/no)"
            self.state = State.IMMINENT_DANGER
            return [reply]

        # TODO: Implement the rest of the flow

        if self.state == State.IMMINENT_DANGER:
            if 'y' in message.content.lower():
                self.state = State.NOTIFY_AUHTORITIES
                return ["Do you think there is imminent danger? (Yes/no)\n"]

        if self.state == State.NOTIFY_AUHTORITIES:
            if 'y' in message.content.lower():
                self.state = State.NOTIFY_AUHTORITIES_COMPLETE
                return ["Please include a short description to send to the authorities along with the rest of the report.\n"]

        if self.state == State.NOTIFY_AUHTORITIES_COMPLETE:
            self.state = State.AWAITING_ACTIONS
            response = "A report will be compiled and forwarded to the authorities. \n\n"
            return [{"text": response, "view": self.generate_moderator_action_menu()}]
        
        
        if self.state == State.AWAITING_ACTION_REASON:
            self.moderation_reasons = message.content
            self.state = State.MODERATE_COMPLETE
            response = "Thank you for your response. All necessary actions will be taken.\n"
            
            if 'ban' in self.selected_actions:
                await self.send_DM(self.report.reported_message.author.id, "You have been temporarily banned from the platform.")
                
            if 'block' in self.selected_actions:
                await self.send_DM(self.report.author.id, f"{self.report.reported_message.author.name} has been blocked.")
                
            if 'warn' in self.selected_actions:
                await self.send_DM(self.report.author.id, f"This is a warning")
            
            response += "The moderation is compelete!\n"
            return [response]
        
        # Please include a message to explain the actions you've taken? 
        return []

    def generate_moderator_action_menu(self):
        async def callback(interaction):
            self.selected_actions = select_menu.values

            self.state = State.AWAITING_ACTION_REASON  # Adjust the state as needed
            response = "Please include your reasons for taking these actions: \n"
            await interaction.response.send_message(response)

        choices = [
            SelectOption(
                label='Temporarily ban the User',
                description="Permanently remove the user from the platform.",
                value='ban',
                emoji="🚫"
            ),
            SelectOption(
                label='Block the User',
                description="Prevent the user from interacting with the victim.",
                value='block',
                emoji="🚷"
            ),
            SelectOption(
                label='Warn the User',
                description="Issue a formal warning to the user.",
                value='warn',
                emoji="⚠️"
            ),
        ]

        select_menu = Select(
            min_values=0,
            max_values=3,
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
