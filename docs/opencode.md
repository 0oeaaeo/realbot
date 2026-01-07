# OpenCode Discord Client

A simple, conversational interface for AI-powered coding assistance.

## Quick Start

```
!code Help me write a Python web scraper
```

That's it! A thread is created where you can chat naturally with OpenCode.

---

## How It Works

1. **Start a session** with `!code` (or `!opencode`, `!oc`)
2. **A thread is created** for your conversation
3. **Just type** your questions - no commands needed
4. **Get streaming responses** that update in real-time

---

## Examples

```
!code

!code Debug this function that's returning None

!code Explain how async/await works in Python

!code Write unit tests for my API endpoints
```

---

## In-Thread Controls

While chatting, you have simple button controls:

| Button | Action |
|--------|--------|
| ⏹️ Stop | Abort current generation |
| 🔗 Share | Get shareable session URL |
| 🗑️ End Session | Close the session |

### Text Commands

You can also end a session by typing any of these in the thread:
`exit`, `quit`, `stop`, `end session`, `bye`

---

## Tips

- **Be specific** - "Fix the bug on line 42" works better than "fix it"
- **Include context** - Share relevant code or error messages
- **Ask follow-ups** - The AI remembers your conversation
- **Use naturally** - Just chat like you would with a colleague
