"""CAO invokes this as codex; enforce the agreed login and permission boundary."""
import os
from pathlib import Path
import sys
from bridge import auth, clean_env, job_dir, write

args = sys.argv[1:]
if "--yolo" in args or "--dangerously-bypass-approvals-and-sandbox" in args:
    sys.exit("AIFlow refuses unrestricted CAO launch.")
if args[:2] != ["--profile", "aiflow_script"]:
    sys.exit("AIFlow requires its dedicated CAO profile.")
args = args[2:]  # Marker selects this launcher; no global Codex profile modification.
config = auth()
job = job_dir(os.environ.get("AIFLOW_CODEX_JOB", ""))
if Path.cwd().resolve() != (job / "work").resolve():
    sys.exit("Wrong task working directory.")
write(job / "chatgpt-launch.json", {"auth": "chatgpt", "codex_version": config["version"]})
args += ["-c", 'forced_login_method="chatgpt"', "-c", 'model_provider="openai"',
         "--sandbox", "workspace-write", "--ask-for-approval", "never",
         "-c", "sandbox_workspace_write.network_access=false", "-c", 'web_search="disabled"']
env = clean_env()
env.pop("CAO_AUTH_LOCAL_TOKEN", None)
os.execve(config["codex"], [config["codex"], *args], env)
