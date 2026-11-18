import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = "package.yml"


def command(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=ROOT, check=True, text=True,
                            encoding="utf-8",
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def main() -> None:
    if not shutil.which("gh"):
        raise SystemExit("Install GitHub CLI and run 'gh auth login', or use build.cmd --windows-only.")
    if command("git", "--no-pager", "status", "--porcelain", capture=True):
        raise SystemExit("Commit and push the source and packaging files before building both platforms.")
    branch = command("git", "--no-pager", "branch", "--show-current", capture=True)
    if not branch:
        raise SystemExit("Check out a branch before building both platforms.")
    commit = command("git", "--no-pager", "rev-parse", "HEAD", capture=True)
    repo = command("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner", capture=True)
    remote = command("gh", "api", f"repos/{repo}/git/ref/heads/{quote(branch, safe='')}",
                     "--jq", ".object.sha", capture=True)
    if remote != commit:
        raise SystemExit("Push this branch to GitHub before building both platforms.")

    dispatched = json.loads(command(
        "gh", "api", "--method", "POST", "-H", "X-GitHub-Api-Version: 2026-03-10",
        f"repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
        "-f", f"ref={branch}", "-f", f"inputs[commit]={commit}", capture=True,
    ))
    run_id = str(dispatched["workflow_run_id"])
    print(f"Building {commit[:12]}: {dispatched['html_url']}", flush=True)
    command("gh", "run", "watch", run_id, "--repo", repo, "--exit-status", "--interval", "10")
    destination = ROOT / "packing" / "dist" / run_id
    command("gh", "run", "download", run_id, "--repo", repo, "--dir", str(destination))
    print(f"Packages downloaded to {destination}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Build command failed ({exc.returncode}): {' '.join(exc.cmd)}") from exc
