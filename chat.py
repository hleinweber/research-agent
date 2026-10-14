"""Step 2: resend the full conversation on every turn."""
from api import complete, initial_messages

def main():
    messages = initial_messages()
    print("Research agent conversation. Type /quit to exit.")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text == "/quit":
            break
        if not text:
            continue
        messages.append({"role": "user", "content": text})
        try:
            reply = complete(messages)
        except (RuntimeError, OSError, ValueError) as error:
            messages.pop()
            print(f"Request failed: {error}")
            continue
        messages.append(reply)
        print("Assistant:", reply.get("content") or "")

if __name__ == "__main__":
    main()
