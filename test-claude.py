
from anthropic import Anthropic
from decouple import config

client = Anthropic(
    # This is the default and can be omitted
    api_key=config("ANTHROPIC_API_KEY"),
)

message = client.messages.create(
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": "What are the official languages of Ethiopia?",
        }
    ],

    model=config("ANTHROPIC_MODEL"),
)

print(message.content)
