"""
Fetches FIFA World Cup 2026 goal data.

Squad source: ESPN public API (no auth required, no anti-bot, returns current rosters).
  https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/teams/{id}/roster

Goal/OG data: football-data.org free tier
  /v4/competitions/WC/scorers  -> regular goals
  /v4/competitions/WC/matches  -> OG events
"""
import json
import os
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN = os.environ["FD_TOKEN"]
BASE  = "https://api.football-data.org/v4"

CLUBS = {
    "utd": {"espn_league": "eng.1", "espn_name": "Manchester United", "name": "Manchester United", "flag": "\U0001f534"},
    "rm":  {"espn_league": "esp.1", "espn_name": "Real Madrid",        "name": "Real Madrid",        "flag": "⚪"},
    "fcb": {"espn_league": "ger.1", "espn_name": "Bayern Munich",      "name": "Bayern Munich",      "flag": "\U0001f534"},
}

ESPN_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

def fetch_fd(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"X-Auth-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}\nResponse: {body}") from e

def fetch_json(url):
    req = urllib.request.Request(url, headers=ESPN_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

def espn_squad(league: str, search_name: str) -> list[str]:
    """Return player name list from ESPN for a club in a given league."""
    # Step 1: find team ID by name
    teams_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/teams"
    data = fetch_json(teams_url)
    team_id = None
    for team in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = team.get("team", {})
        if normalize(t.get("displayName", "")) == normalize(search_name) or \
           normalize(t.get("name", "")) == normalize(search_name) or \
           normalize(t.get("shortDisplayName", "")) == normalize(search_name):
            team_id = t.get("id")
            print(f"    Found {t.get('displayName')} (ESPN id={team_id})")
            break
    if not team_id:
        print(f"  WARNING: {search_name} not found in ESPN {league}")
        print(f"  Available teams: {[t.get('team',{}).get('displayName') for t in data.get('sports',[{}])[0].get('leagues',[{}])[0].get('teams',[])[:8]]}")
        return []

    # Step 2: fetch roster
    roster_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/teams/{team_id}/roster"
    try:
        rdata = fetch_json(roster_url)
    except Exception as e:
        print(f"  WARNING: ESPN roster fetch failed for {search_name}: {e}")
        return []

    names = []
    for athlete in rdata.get("athletes", []):
        display = athlete.get("displayName") or athlete.get("fullName") or athlete.get("name", "")
        if display:
            names.append(display)
    return names

# ── Build player name map from ESPN ───────────────────────────────────────────────────────────
NAME_TO_CLUB: dict[str, tuple[str, str]] = {}
CLUB_SQUADS:  dict[str, list[str]]        = {key: [] for key in CLUBS}

for key, club in CLUBS.items():
    names = espn_squad(club["espn_league"], club["espn_name"])
    CLUB_SQUADS[key] = names
    for name in names:
        NAME_TO_CLUB[normalize(name)] = (key, name)
    print(f"  {club['name']}: {len(names)} players from ESPN")
    for n in names[:5]:
        print(f"    - {n}")

print(f"  Total tracked players: {len(NAME_TO_CLUB)}")

# ── WC scorers ────────────────────────────────────────────────────────────────────
scorers_raw  = fetch_fd("/competitions/WC/scorers?season=2026&limit=200")
player_info  = {}
scorer_goals = {}
PLAYER_CLUBS: dict[int, str] = {}

for entry in scorers_raw.get("scorers", []):
    p   = entry.get("player", {})
    pid = p.get("id")
    if not pid:
        continue
    name = p.get("name", "")
    player_info[pid]  = {"name": name, "nationality": p.get("nationality", "")}
    scorer_goals[pid] = entry.get("goals", 0)
    norm = normalize(name)
    if norm in NAME_TO_CLUB:
        club_key, espn_name = NAME_TO_CLUB[norm]
        PLAYER_CLUBS[pid] = club_key
        print(f"  MATCH: {name} [{espn_name}] -> {CLUBS[club_key]['name']} ({entry.get('goals',0)}g)")

print(f"  WC scorers: {len(scorer_goals)} total, "
      f"{sum(1 for p in scorer_goals if p in PLAYER_CLUBS)} from our 3 clubs")

# ── OG events ──────────────────────────────────────────────────────────────────────────
matches_raw = fetch_fd("/competitions/WC/matches?season=2026&status=FINISHED")
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
            norm = normalize(scorer.get("name", ""))
            if norm in NAME_TO_CLUB:
                PLAYER_CLUBS[pid] = NAME_TO_CLUB[norm][0]
        og_map[pid] = og_map.get(pid, 0) + 1
print(f"  Own goals: {sum(og_map.values())} across {len(og_map)} players")

# ── Build output ──────────────────────────────────────────────────────────────────────────
output = {"updated": datetime.now(timezone.utc).isoformat(), "clubs": {}}

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers = []
    club_pids = {pid for pid, ck in PLAYER_CLUBS.items() if ck == key}

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

    squad_out = []
    for espn_name in CLUB_SQUADS[key]:
        norm = normalize(espn_name)
        pid  = next((i for i, info in player_info.items()
                     if normalize(info["name"]) == norm), None)
        g  = scorer_goals.get(pid, 0) if pid else 0
        og = og_map.get(pid, 0)        if pid else 0
        squad_out.append({
            "name":     espn_name,
            "goals":    g,
            "ownGoals": og,
            "net":      g - og,
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
