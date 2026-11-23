"""Git askpass helper.

It answers Git's credential prompts from the environment, so the token
never has to appear in a command line or in the git config.
"""
import os
import sys

prompt = sys.argv[1] if len(sys.argv) > 1 else ""
token = os.environ.get("GITHUB_TOKEN", "")

if "Username" in prompt:
    sys.stdout.write(os.environ.get("GITHUB_USER", "tri221005"))
else:
    sys.stdout.write(token)
