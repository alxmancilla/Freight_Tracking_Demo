"""Small helper to format presenter-friendly section banners and pauses."""
import os
import sys


def banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {title}\n{line}")


def note(text: str) -> None:
    print(f"\n[NOTES]\n{text}\n")


def pause(prompt: str = "Press ENTER to continue...") -> None:
    if os.getenv("DEMO_NO_PAUSE"):
        return
    try:
        input(f"\n>>> {prompt}")
    except EOFError:
        sys.exit(0)
