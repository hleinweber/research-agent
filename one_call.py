"""Step 1: one user message, one API call."""
import sys
from api import complete, initial_messages
messages = initial_messages()
messages.append({"role": "user", "content": " ".join(sys.argv[1:]) or "Say hello in one sentence."})
print(complete(messages).get("content") or "")
