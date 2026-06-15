"""
Fetches FIFA World Cup 2026 goal data.

Squad source: Wikipedia current squad sections (static HTML, no anti-bot issues).
Player names are normalized and matched against football-data.org WC scorer names.

Goal/OG data: football-data.org free tier
  /v4/competitions/WC/scorers  -> regular goals
  /v4/competitions/WC/matches  -> OG events
"""
import json
import os
import re
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN = os.environ["FD_TOKEN"]
BASE  = "https://api.football-data.org/v4"

CLUBS = {
    "utd": {"wiki": "Manchester_United_F.C.", "name": "Manchester United", "flag": "\U0001f534"},
    "rm":  {"wiki": "Real_Madrid_CF",         "name": "Real Madrid",        "flag": "⚪"},
    "fcb": {"wiki": "FC_Bayern_Munich",       "name": "Bayern Munich",      "flag": "\U0001f534"},
}

WIKI_HEADERS = {
    "User-Agent": "WC2026GoalTracker/1.0 (github.com/shreyartha-bioinfo/fuzzy-engine; educational)",
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

def fetch_wiki_squad(wiki_page: str) -> list[str]:
    """Return list of player names from Wikipedia's Current squad section."""
    # Get the full wikitext via the API
    api = ("https://en.wikipedia.org/w/api.php"
           f"?action=parse&page={urllib.request.quote(wiki_page)}"
           "&prop=wikitext&format=json&redirects=1")
    req = urllib.request.Request(api, headers=WIKI_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")

    # Find the Current squad section (between == Current squad == and next ==)
    squad_match = re.search(
        r'==\s*Current squad\s*==(.+?)(?:\n==[^=]|\Z)',
        wikitext, re.DOTALL | re.IGNORECASE
    )
    if not squad_match:
        # Try "First-team squad" as fallback heading
        squad_match = re.search(
            r'==\s*(?:First[- ]team squad|Squad)\s*==(.+?)(?:\n==[^=]|\Z)',
            wikitext, re.DOTALL | re.IGNORECASE
        )
    if not squad_match:
        return []

    section = squad_match.group(1)

    # Extract player names from squad table rows.
    # Wiki squad tables use {{fs player|no=N|nat=XX|name=Player Name|...}}
    names = re.findall(r'\|\s*name\s*=\s*([^|\}\n]+)', section)
    if not names:
        # Fallback: [[Player Name|...]] links inside the squad table
        names = re.findall(r'\[\[([^\]\|]+)(?:\|[^\]]*)?\]\]', section)
        # Filter out non-player links (positions, nationalities, etc.)
        names = [n for n in names if len(n.split()) >= 2]

    return [n.strip() for n in names if n.strip()]

def normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

# ── Build player name map from Wikipedia ────────────────────────────────────────────────
NAME_TO_CLUB: dict[str, tuple[str, str]] = {}  # norm -> (club_key, display_name)
CLUB_SQUADS:  dict[str, list[str]]        = {key: [] for key in CLUBS}

for key, club in CLUBS.items():
    names = fetch_wiki_squad(club["wiki"])
    CLUB_SQUADS[key] = names
    for name in names:
        NAME_TO_CLUB[normalize(name)] = (key, name)
    print(f"  {club['name']}: {len(names)} players from Wikipedia")
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
        club_key, wiki_name = NAME_TO_CLUB[norm]
        PLAYER_CLUBS[pid] = club_key
        print(f"  MATCH: {name} [{wiki_name}] -> {CLUBS[club_key]['name']} ({entry.get('goals',0)}g)")

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

    # Squad list with WC goals overlaid
    squad_out = []
    for wiki_name in CLUB_SQUADS[key]:
        norm = normalize(wiki_name)
        pid  = next((i for i, info in player_info.items()
                     if normalize(info["name"]) == norm), None)
        g  = scorer_goals.get(pid, 0) if pid else 0
        og = og_map.get(pid, 0)        if pid else 0
        squad_out.append({
            "name":     wiki_name,
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
