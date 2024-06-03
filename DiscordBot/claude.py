import anthropic
from typing import List
# Messages format:
# "messages": [
#     {"role": "user", "content": "Hello, Claude"},
#     {"role": "assistant", "content": "Hello!"},
#     {"role": "user", "content": "Can you describe LLMs to me?"}
# ]

PROMPTS = {
    "gen_system_message": "You are a helpful AI assistant. Your job is to consider a conversation and answer questions about this conversation. The conversation is as follows: {conversation}. {question}",
    "system_message": "You are a helpful AI assistant. Your job is to moderate a chat channel in order to detect violations of content according to the CONTENT POLICY, described here: {content_policy}. Here are your instructions:\n {instructions}. Please follow your instructions to the best of your ability.",
    "content_policy": "If a conversation consists of any of these violations: SPAM, EXPLICIT CONTENT, THREAT TO ONESELF OR OTHERS, or HARASSMENT, it must be reported immediately",
    "instructions": "Please consider the following conversation between users:\n {conversation}. If the conversation violates the CONTENT POLICY, please say this: REPORT. If it does not, please say this and only this: NO_VIOLATION."

}

# Parse the messages
def query(conversation, assistant_completion=""):

    input = [{"role": "user", "content": conversation}]
             
    if assistant_completion:
        input.append({"role": "assistant", "content": assistant_completion})

    message = anthropic.Anthropic().messages.create(
        model="claude-3-opus-20240229",
        max_tokens=1024,
        messages=input
    )
    return message.content[0].text


