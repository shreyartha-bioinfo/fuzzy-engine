"""
Fetches FIFA World Cup 2026 goal data from football-data.org (free tier).
Rate limit: 10 req/min. We sleep 7s between /persons lookups to stay safe.
"""
import json, os, time, urllib.request, urllib.error
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

# 1. WC scorers -> player IDs + goal counts
scorers_raw  = fetch("/competitions/WC/scorers?season=2026&limit=200")
scorer_goals = {}  # pid -> goals
player_info  = {}  # pid -> {name, nationality}

for entry in scorers_raw.get("scorers", []):
    p   = entry.get("player", {})
    pid = p.get("id")
    if not pid:
        continue
    scorer_goals[pid] = entry.get("goals", 0)
    player_info[pid]  = {"name": p.get("name", ""), "nationality": p.get("nationality", "")}

print(f"  WC scorers: {len(scorer_goals)}")

# 2. OG events from finished matches
matches_raw = fetch("/competitions/WC/matches?season=2026&status=FINISHED")
og_map = {}  # pid -> own_goal count
for match in matches_raw.get("matches", []):
    for goal in match.get("goals", []):
        if goal.get("type") != "OWN_GOAL":
            continue
        pid = (goal.get("scorer") or {}).get("id")
        if pid:
            og_map[pid] = og_map.get(pid, 0) + 1
            if pid not in player_info:
                player_info[pid] = {"name": (goal.get("scorer") or {}).get("name", ""), "nationality": ""}

print(f"  OG scorers: {len(og_map)}")

# 3. Look up currentTeam (club) for each relevant player via /persons/{id}
#    Rate limit: 10 req/min -> sleep 7s between calls
all_pids   = set(scorer_goals) | set(og_map)
player_club = {}  # pid -> club_key

for i, pid in enumerate(all_pids):
    if i > 0:
        time.sleep(7)
    person  = fetch(f"/persons/{pid}")
    club_id = (person.get("currentTeam") or {}).get("id")
    name    = person.get("name", player_info.get(pid, {}).get("name", ""))
    nat     = person.get("nationality", player_info.get(pid, {}).get("nationality", ""))
    player_info[pid] = {"name": name, "nationality": nat}
    if club_id in CLUB_IDS:
        player_club[pid] = CLUB_IDS[club_id]
        print(f"  MATCH: {name} -> {CLUBS[CLUB_IDS[club_id]]['name']}")

print(f"  Players matched to our clubs: {len(player_club)}")

# 4. Build per-club output
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
        scorers.append({"name": info.get("name", ""), "nationality": info.get("nationality", ""),
                        "goals": g, "ownGoals": og, "net": g - og})

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
