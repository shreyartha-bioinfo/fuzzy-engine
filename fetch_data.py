"""
Fetches FIFA World Cup 2026 goal data from football-data.org (free tier) and writes data.json.

Strategy: currentTeam is null on free tier, /persons/{id} is blocked.
We use a hardcoded PLAYER_CLUBS map (player_id -> club_key) built from the
printed scorer list. WC squads are frozen for the tournament, so this is stable.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN = os.environ["FD_TOKEN"]
BASE  = "https://api.football-data.org/v4"

CLUBS = {
    "utd": {"id": 66,  "name": "Manchester United", "flag": "\U0001f534"},
    "rm":  {"id": 86,  "name": "Real Madrid",        "flag": "⚪"},
    "fcb": {"id": 5,   "name": "Bayern Munich",      "flag": "\U0001f534"},
}

# Hardcoded player_id -> club_key mapping.
# Populate from the ALL SCORERS dump below, then remove the dump.
PLAYER_CLUBS: dict[int, str] = {
    # e.g. 12345: "utd",  67890: "rm",  11111: "fcb",
}

def fetch(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"X-Auth-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}\nResponse: {body}") from e

# ── WC scorers ────────────────────────────────────────────────────────────────────
scorers_raw = fetch("/competitions/WC/scorers?season=2026&limit=200")

player_info  = {}   # player_id -> {name, nationality}
scorer_goals = {}   # player_id -> regular goal count

print("\n=== ALL WC 2026 SCORERS (copy IDs to PLAYER_CLUBS above) ===")
for entry in scorers_raw.get("scorers", []):
    p   = entry.get("player", {})
    pid = p.get("id")
    if not pid:
        continue
    name = p.get("name", "")
    nat  = p.get("nationality", "")
    goals = entry.get("goals", 0)
    team  = entry.get("team", {}).get("name", "")
    player_info[pid] = {"name": name, "nationality": nat}
    scorer_goals[pid] = goals
    print(f"  {pid:>8}  {goals}g  {name:<30}  ({nat}, plays for {team} at WC)")
print(f"=== {len(scorer_goals)} scorers total ===\n")

# ── OG events ──────────────────────────────────────────────────────────────────────────
matches_raw = fetch("/competitions/WC/matches?season=2026&status=FINISHED")
og_map = {}
for match in matches_raw.get("matches", []):
    for goal in match.get("goals", []):
        if goal.get("type") != "OWN_GOAL":
            continue
        scorer = goal.get("scorer") or {}
        pid    = scorer.get("id")
        if not pid:
            continue
        if pid not in player_info:
            player_info[pid] = {"name": scorer.get("name", ""), "nationality": ""}
        og_map[pid] = og_map.get(pid, 0) + 1
print(f"  Own goals: {sum(og_map.values())} across {len(og_map)} players")

# ── Build output ──────────────────────────────────────────────────────────────────────────
output = {"updated": datetime.now(timezone.utc).isoformat(), "clubs": {}}

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers = []

    all_pids = set(PLAYER_CLUBS.keys()) | set(og_map.keys())
    club_pids = {pid for pid in all_pids if PLAYER_CLUBS.get(pid) == key}

    for pid in club_pids:
        g  = scorer_goals.get(pid, 0)
        og = og_map.get(pid, 0)
        total_goals += g
        total_ogs   += og
        info = player_info.get(pid, {})
        scorers.append({
            "name":        info.get("name", f"Player {pid}"),
            "nationality": info.get("nationality", ""),
            "goals":       g,
            "ownGoals":    og,
            "net":         g - og,
        })

    scorers.sort(key=lambda x: (-x["net"], -x["goals"]))
    output["clubs"][key] = {
        "name":     club["name"],
        "flag":     club["flag"],
        "goals":    total_goals,
        "ownGoals": total_ogs,
        "net":      total_goals - total_ogs,
        "scorers":  scorers,
        "squad":    scorers,
    }
    print(f"  {club['name']}: {total_goals}G − {total_ogs}OG = {total_goals - total_ogs}")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print("data.json written.")
