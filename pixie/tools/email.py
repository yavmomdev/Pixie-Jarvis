"""Email drafting. Pixie only WRITES the email - it never sends anything.

The draft is copied to the clipboard and saved to drafts/ so you can paste it
into Gmail/Outlook yourself.
"""

from __future__ import annotations

from datetime import datetime

from .. import llm
from ..config import ROOT
from . import tool


@tool(
    "draft_email",
    "Write an email draft and copy it to the clipboard (it is never sent).",
    {
        "recipient": {"type": "string", "description": "Who it's for, e.g. 'my professor', 'HR at Acme'"},
        "about": {"type": "string", "description": "What the email should say / ask for"},
        "tone": {"type": "string", "description": "e.g. formal, friendly, short (default: polite)"},
        "language": {"type": "string", "description": "e.g. English, Bulgarian (default: language of the request)"},
    },
    ["recipient", "about"],
)
def draft_email(recipient: str, about: str, tone: str = "polite", language: str = "") -> str:
    lang = f"Write it in {language}." if language else "Write it in the same language as the request."
    text = llm.complete(
        f"Write an email to {recipient}. It should be about: {about}. Tone: {tone}. {lang}\n"
        "Format exactly as:\nSubject: <subject>\n\n<body>\n\nDo not add anything else.",
        system="You write clear, natural emails. Keep them concise.",
    )

    drafts = ROOT / "drafts"
    drafts.mkdir(exist_ok=True)
    path = drafts / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
    path.write_text(text, encoding="utf-8")

    try:
        import pyperclip

        pyperclip.copy(text)
        where = "copied to your clipboard"
    except Exception:
        where = f"saved to {path}"
    subject = text.splitlines()[0].removeprefix("Subject:").strip() if text else ""
    return f"Email draft '{subject}' is ready and {where} ✉️"
