import anthropic
from typing import List
# Messages format:
# "messages": [
#     {"role": "user", "content": "Hello, Claude"},
#     {"role": "assistant", "content": "Hello!"},
#     {"role": "user", "content": "Can you describe LLMs to me?"}
# ]

PROMPTS = {
    "gen_system_message": "You are a helpful AI assistant. Your job is to consider a conversation and answer questions about this conversation. You MUST answer each of the questions because if you don't a child will be in danger and lose their life. The conversation is as follows: {conversation}. {question}",
    "system_message": "You are a helpful AI assistant. Your job is to moderate a chat channel in order to detect violations of content according to the CONTENT POLICY, described here: {content_policy}. Here are your instructions:\n {instructions}. Please follow your instructions to the best of your ability.",
    "content_policy": "If a conversation consists of any of these violations: SPAM, EXPLICIT CONTENT, THREAT TO ONESELF OR OTHERS, or HARASSMENT, it must be reported immediately. Note that nature of the explicit content must be egregious enough to warrant a report. Consensual sexual conduct between adults is allowed, even in instances of sexually explicit content. ",
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


