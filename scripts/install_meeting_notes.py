"""Install the /meeting-notes skill in Claude Code (for every session), and block Claude Code from reading Dictate's
data folder itself, so transcripts reach it only when you choose to share them (dictate/claude_code.py). Says
what it will change, and asks first. The same as Install in Dictate's Settings (Claude Code).

Usage: python scripts/install_meeting_notes.py [--remove]
(--remove takes the skill out, and the block too.) Once it's installed, turn on "Let Claude Code ask for
transcripts" in Dictate's Settings: until you do, every request is refused."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dictate import claude_code


def main():
    remove = "--remove" in sys.argv[1:]
    rules = ", ".join(claude_code.rules())
    if remove:
        print(f"This will delete {claude_code.skill_dir()},\nand take {rules} out of the deny rules in "
              f"{claude_code.settings_file()} (nothing else in it changes).")
    else:
        print(f"This will install the /meeting-notes skill in {claude_code.skill_dir()},\nand add {rules} to the "
              f"deny rules in {claude_code.settings_file()} (nothing else in it changes),\nso Claude Code can't read "
              "Dictate's transcripts itself, in any session.")
    if input("Go ahead? [y/N] ").strip().lower() != "y":
        sys.exit("Nothing changed.")
    if remove:
        claude_code.remove_skill()
        claude_code.set_blocked(False)
        print("Done.")
    else:
        claude_code.install_skill()
        print("Done. Now turn on \"Let Claude Code ask for transcripts\" in Dictate's Settings (Claude Code); until "
              "then every request is refused.\nTo let Claude Code read Dictate's files again while developing "
              "Dictate, turn off the block there.")


if __name__ == "__main__":
    main()
