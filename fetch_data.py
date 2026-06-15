"""
Fetches FIFA World Cup 2026 goal data from football-data.org (free tier).

Squad source: domestic league team endpoints (PL, PD, BL1) — free tier, returns
full squad with player IDs. Manual overrides applied after fetch for known
transfers not yet reflected in the API.

Goal/OG data:
  /v4/competitions/WC/scorers  -> regular goals
  /v4/competitions/WC/matches  -> OG events
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN = os.environ["FD_TOKEN"]
BASE  = "https://api.football-data.org/v4"

CLUBS = {
    "utd": {"id": 66,  "league": "PL",  "name": "Manchester United", "flag": "\U0001f534"},
    "rm":  {"id": 86,  "league": "PD",  "name": "Real Madrid",        "flag": "⚪"},
    "fcb": {"id": 5,   "league": "BL1", "name": "Bayern Munich",      "flag": "\U0001f534"},
}

# Manual corrections for transfers not yet in football-data.org season data.
# REMOVE: player names to drop from a club's squad.
# ADD: extra players to add (name + nationality). These are matched by name
#      against WC scorer names for goal attribution.
OVERRIDES = {
    "rm": {
        "remove": {"David Alaba", "Dávid Alaba", "Daniel Carvajal", "D. Carvajal"},
        "add":    [{"name": "Marc Cucurella", "position": "Defence", "nationality": "Spain"}],
    },
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

# ── Build player->club map + full squad lists from domestic league rosters ────────
PLAYER_CLUBS: dict[int, str] = {}
CLUB_SQUADS:  dict[str, list] = {key: [] for key in CLUBS}
# Extra name->club mapping for manually added players
EXTRA_NAMES:  dict[str, str]  = {}  # lower name -> club_key

for key, club in CLUBS.items():
    ovr     = OVERRIDES.get(key, {})
    removes = {n.lower() for n in ovr.get("remove", set())}
    adds    = ovr.get("add", [])

    league_data = fetch(f"/competitions/{club['league']}/teams?season=2025")
    for team in league_data.get("teams", []):
        if team.get("id") != club["id"]:
            continue
        squad = team.get("squad", [])
        pos_order = {"Goalkeeper": 0, "Defence": 1, "Midfield": 2, "Offence": 3}
        for player in squad:
            pid  = player.get("id")
            name = player.get("name", "")
            if name.lower() in removes or name in ovr.get("remove", set()):
                print(f"  OVERRIDE REMOVE: {name} from {club['name']}")
                continue
            pos = player.get("position", "")
            nat = player.get("nationality", "")
            if pid:
                PLAYER_CLUBS[pid] = key
                CLUB_SQUADS[key].append({"id": pid, "name": name, "position": pos, "nationality": nat})

        # Apply additions
        for extra in adds:
            CLUB_SQUADS[key].append({"id": None, **extra})
            EXTRA_NAMES[extra["name"].lower()] = key
            print(f"  OVERRIDE ADD: {extra['name']} to {club['name']}")

        CLUB_SQUADS[key].sort(key=lambda p: (pos_order.get(p.get("position", ""), 9), p["name"]))
        print(f"  {club['name']}: {len(CLUB_SQUADS[key])} squad members (after overrides)")
        break
    else:
        print(f"  WARNING: {club['name']} not found in {club['league']} teams")

print(f"  Total tracked players: {len(PLAYER_CLUBS)} by ID + {len(EXTRA_NAMES)} by name")

# ── WC scorers ────────────────────────────────────────────────────────────────────
scorers_raw  = fetch("/competitions/WC/scorers?season=2026&limit=200")
player_info  = {}
scorer_goals = {}

for entry in scorers_raw.get("scorers", []):
    p   = entry.get("player", {})
    pid = p.get("id")
    if not pid:
        continue
    name = p.get("name", "")
    player_info[pid]  = {"name": name, "nationality": p.get("nationality", "")}
    scorer_goals[pid] = entry.get("goals", 0)
    # Match by player ID first
    if pid in PLAYER_CLUBS:
        club_name = CLUBS[PLAYER_CLUBS[pid]]["name"]
        print(f"  MATCH (id): {name} -> {club_name} ({entry.get('goals',0)}g)")
    # Match manually added players by name
    elif name.lower() in EXTRA_NAMES:
        club_key = EXTRA_NAMES[name.lower()]
        PLAYER_CLUBS[pid] = club_key
        print(f"  MATCH (name override): {name} -> {CLUBS[club_key]['name']} ({entry.get('goals',0)}g)")

print(f"  WC scorers: {len(scorer_goals)} total, "
      f"{sum(1 for p in scorer_goals if p in PLAYER_CLUBS)} from our 3 clubs")

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
        if pid not in PLAYER_CLUBS and scorer.get("name", "").lower() in EXTRA_NAMES:
            PLAYER_CLUBS[pid] = EXTRA_NAMES[scorer["name"].lower()]
        og_map[pid] = og_map.get(pid, 0) + 1
print(f"  Own goals: {sum(og_map.values())} across {len(og_map)} players")

# ── Build output ──────────────────────────────────────────────────────────────────────────
output = {"updated": datetime.now(timezone.utc).isoformat(), "clubs": {}}

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers = []
    club_pids = {p["id"] for p in CLUB_SQUADS[key] if p["id"] is not None}
    club_pids |= {pid for pid, ck in PLAYER_CLUBS.items() if ck == key}

    for pid in club_pids:
        g  = scorer_goals.get(pid, 0)
        og = og_map.get(pid, 0)
        if g == 0 and og == 0:
            continue
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

    goals_by_pid = {pid: scorer_goals.get(pid, 0) for pid in club_pids}
    ogs_by_pid   = {pid: og_map.get(pid, 0)        for pid in club_pids}
    squad_out = []
    for p in CLUB_SQUADS[key]:
        pid = p["id"]
        # For manually added players, look up by name
        if pid is None:
            pid = next((i for i, info in player_info.items()
                        if info["name"].lower() == p["name"].lower()), None)
        g  = scorer_goals.get(pid, 0) if pid else 0
        og = og_map.get(pid, 0)        if pid else 0
        squad_out.append({
            "name":        p["name"],
            "position":    p.get("position", ""),
            "nationality": p.get("nationality", ""),
            "goals":       g,
            "ownGoals":    og,
            "net":         g - og,
        })

    output["clubs"][key] = {
        "name":     club["name"],
        "flag":     club["flag"],
        "goals":    total_goals,
        "ownGoals": total_ogs,
        "net":      total_goals - total_ogs,
        "scorers":  scorers,
        "squad":    squad_out,
    }
    print(f"  {club['name']}: {total_goals}G − {total_ogs}OG = {total_goals - total_ogs}")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print("data.json written.")
