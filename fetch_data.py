"""
Fetches FIFA World Cup 2026 goal data from football-data.org (free tier) and writes data.json.

Free tier approach:
  - /v4/competitions/WC/scorers  -> regular goals per player + player.currentTeam (their club)
  - /v4/competitions/WC/matches  -> OG events; scorer ID looked up in club map built from scorers
No /teams/{id} calls needed (those require a paid tier).
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
CLUB_IDS = {v["id"]: k for k, v in CLUBS.items()}

def fetch(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"X-Auth-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}\nResponse: {body}") from e

# WC scorers: regular goals + currentTeam
scorers_raw = fetch("/competitions/WC/scorers?season=2026&limit=200")

player_club  = {}
player_info  = {}
scorer_goals = {}

for entry in scorers_raw.get("scorers", []):
    p       = entry.get("player", {})
    pid     = p.get("id")
    club_id = (p.get("currentTeam") or {}).get("id")
    if not pid:
        continue
    player_info[pid] = {"name": p.get("name", ""), "nationality": p.get("nationality", "")}
    scorer_goals[pid] = entry.get("goals", 0)
    if club_id in CLUB_IDS:
        player_club[pid] = CLUB_IDS[club_id]

print(f"  WC scorers: {len(scorer_goals)} total, {len(player_club)} from our 3 clubs")

# OG events from finished matches
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

# Build per-club output
output = {"updated": datetime.now(timezone.utc).isoformat(), "clubs": {}}

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers = []
    club_pids = {pid for pid, ck in player_club.items() if ck == key}

    for pid in club_pids:
        g  = scorer_goals.get(pid, 0)
        og = og_map.get(pid, 0)
        total_goals += g
        total_ogs   += og
        info = player_info.get(pid, {})
        scorers.append({"name": info.get("name", f"Player {pid}"),
                        "nationality": info.get("nationality", ""),
                        "goals": g, "ownGoals": og, "net": g - og})

    for pid, og_count in og_map.items():
        if pid in club_pids:
            continue
        print(f"  WARNING: OG scorer {player_info.get(pid,{}).get('name', pid)} club unknown")

    scorers.sort(key=lambda x: (-x["net"], -x["goals"]))

    output["clubs"][key] = {
        "name": club["name"], "flag": club["flag"],
        "goals": total_goals, "ownGoals": total_ogs,
        "net": total_goals - total_ogs,
        "scorers": scorers, "squad": scorers,
    }
    print(f"  {club['name']}: {total_goals}G - {total_ogs}OG = {total_goals - total_ogs}")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print("data.json written.")
