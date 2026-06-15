"""
Fetches FIFA World Cup 2026 goal data from football-data.org (free tier) and writes data.json.

football-data.org free tier does NOT return player.currentTeam in the WC scorers
endpoint, and /persons/{id} drops connections silently. We use a hardcoded
PLAYER_CLUBS map (player_id -> club_key) instead. WC squads are frozen for the
tournament duration, so this map is stable.

To refresh the map after new goals appear: check the scorer dump in the workflow
logs and add any newly identified club players below.
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

# football-data.org player_id -> club key
# Built from scorer dump; updated as new players score.
PLAYER_CLUBS: dict[int, str] = {
    133584: "utd",  # Amad Diallo        (Ivory Coast)
      1556: "rm",   # Vinicius Junior     (Brazil)
    144393: "fcb",  # Jamal Musiala       (Germany)
    176991: "fcb",  # Nestor Irankunda    (Australia)
    184533: "fcb",  # Nathaniel Brown     (Germany)
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

player_info  = {}
scorer_goals = {}

print("\n=== WC 2026 SCORERS (for map maintenance) ===")
for entry in scorers_raw.get("scorers", []):
    p     = entry.get("player", {})
    pid   = p.get("id")
    if not pid:
        continue
    name  = p.get("name", "")
    nat   = p.get("nationality", "")
    goals = entry.get("goals", 0)
    team  = entry.get("team", {}).get("name", "")
    player_info[pid]  = {"name": name, "nationality": nat}
    scorer_goals[pid] = goals
    club = PLAYER_CLUBS.get(pid, "-")
    print(f"  {pid:>8}  {goals}g  {'[' + club + ']' if club != '-' else '':6}  {name} ({nat} → {team})")
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

all_tracked_pids = set(PLAYER_CLUBS) | set(og_map)

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers = []
    club_pids = {pid for pid in all_tracked_pids if PLAYER_CLUBS.get(pid) == key}

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

    for pid, og_count in og_map.items():
        if PLAYER_CLUBS.get(pid) == key and pid not in club_pids:
            pass  # already handled above
        elif pid not in PLAYER_CLUBS:
            print(f"  NOTE: OG by {player_info.get(pid,{}).get('name', pid)} "
                  f"(id={pid}) — club unknown, not counted")

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
