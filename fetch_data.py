"""
Fetches FIFA World Cup 2026 goal data from football-data.org (free tier).

Club affiliation strategy:
  /v4/competitions/PL/teams   -> Man Utd squad (Premier League, free tier)
  /v4/competitions/PD/teams   -> Real Madrid squad (La Liga, free tier)
  /v4/competitions/BL1/teams  -> Bayern Munich squad (Bundesliga, free tier)

No season filter: fetches the most recently completed season's squad,
which reflects transfers up to the end of the 2025-26 season.
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

def fetch(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"X-Auth-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}\nResponse: {body}") from e

# ── Build player->club map + full squad lists ────────────────────────────────────
PLAYER_CLUBS: dict[int, str] = {}
CLUB_SQUADS:  dict[str, list] = {key: [] for key in CLUBS}

for key, club in CLUBS.items():
    # No season param -> API returns current/most-recent season with latest transfers
    league_data = fetch(f"/competitions/{club['league']}/teams")
    season_label = league_data.get("season", {}).get("startDate", "unknown")
    for team in league_data.get("teams", []):
        if team.get("id") != club["id"]:
            continue
        squad = team.get("squad", [])
        for player in squad:
            pid  = player.get("id")
            name = player.get("name", "")
            pos  = player.get("position", "")
            nat  = player.get("nationality", "")
            if pid:
                PLAYER_CLUBS[pid] = key
                CLUB_SQUADS[key].append({"id": pid, "name": name, "position": pos, "nationality": nat})
        pos_order = {"Goalkeeper": 0, "Defence": 1, "Midfield": 2, "Offence": 3}
        CLUB_SQUADS[key].sort(key=lambda p: (pos_order.get(p["position"], 9), p["name"]))
        print(f"  {club['name']}: {len(squad)} squad members (season data from {season_label})")
        break
    else:
        print(f"  WARNING: {club['name']} not found in {club['league']} teams")

print(f"  Total tracked players: {len(PLAYER_CLUBS)}")

# ── WC scorers ────────────────────────────────────────────────────────────────────
scorers_raw  = fetch("/competitions/WC/scorers?season=2026&limit=200")
player_info  = {}
scorer_goals = {}

for entry in scorers_raw.get("scorers", []):
    p   = entry.get("player", {})
    pid = p.get("id")
    if not pid:
        continue
    player_info[pid]  = {"name": p.get("name", ""), "nationality": p.get("nationality", "")}
    scorer_goals[pid] = entry.get("goals", 0)
    if pid in PLAYER_CLUBS:
        club_name = CLUBS[PLAYER_CLUBS[pid]]["name"]
        print(f"  MATCH: {p.get('name')} -> {club_name} ({entry.get('goals',0)}g)")

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
        og_map[pid] = og_map.get(pid, 0) + 1
print(f"  Own goals: {sum(og_map.values())} across {len(og_map)} players")

# ── Build output ──────────────────────────────────────────────────────────────────────────
output = {"updated": datetime.now(timezone.utc).isoformat(), "clubs": {}}

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers = []
    club_pids = {p["id"] for p in CLUB_SQUADS[key]}

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
        g   = goals_by_pid.get(pid, 0)
        og  = ogs_by_pid.get(pid, 0)
        squad_out.append({
            "name":        p["name"],
            "position":    p["position"],
            "nationality": p["nationality"],
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
