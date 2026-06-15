"""
Fetches FIFA World Cup 2026 goal data.

Squad source: Transfermarkt squad pages (saison_id=2026 = 2026-27 season,
reflecting current transfers). Player names are normalized and matched
against football-data.org WC scorer names.

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
    "utd": {"tm_id": 985,  "name": "Manchester United", "flag": "\U0001f534"},
    "rm":  {"tm_id": 418,  "name": "Real Madrid",        "flag": "⚪"},
    "fcb": {"tm_id": 27,   "name": "Bayern Munich",      "flag": "\U0001f534"},
}

TM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.com/",
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

def fetch_tm(tm_id, saison_id=2026):
    url = f"https://www.transfermarkt.com/x/kader/verein/{tm_id}/saison_id/{saison_id}"
    req = urllib.request.Request(url, headers=TM_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  TM HTTP {e.code} for verein/{tm_id} — falling back to current season")
        url2 = f"https://www.transfermarkt.com/x/kader/verein/{tm_id}/saison_id/2025"
        req2 = urllib.request.Request(url2, headers=TM_HEADERS)
        with urllib.request.urlopen(req2, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")

def normalize(name: str) -> str:
    """Lowercase + strip accents for fuzzy name matching."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

# ── Scrape Transfermarkt squads ───────────────────────────────────────────────────────────────
from bs4 import BeautifulSoup

# norm_name -> (club_key, display_name)
NAME_TO_CLUB: dict[str, tuple[str, str]] = {}
CLUB_SQUADS:  dict[str, list]            = {key: [] for key in CLUBS}

for key, club in CLUBS.items():
    html  = fetch_tm(club["tm_id"])
    soup  = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "items"})
    if not table:
        print(f"  WARNING: could not parse TM squad for {club['name']}")
        continue

    players_found = []
    for row in table.find_all("tr", class_=["odd", "even"]):
        # Main name cell is the FIRST td.hauptlink in each row
        name_cell = row.find("td", class_="hauptlink")
        if not name_cell:
            continue
        link = name_cell.find("a")
        if not link:
            continue
        display_name = link.get_text(strip=True)
        if not display_name:
            continue
        # Position: try to get from preceding sibling or data attributes
        pos_cell = row.find("td", {"class": "positionMitte"}) or \
                   row.find("td", {"class": "pos"})
        pos = pos_cell.get_text(strip=True) if pos_cell else ""
        # Nationality: flag img alt text
        nat = ""
        nat_cell = row.find("td", class_="zentriert")
        if nat_cell:
            img = nat_cell.find("img")
            if img:
                nat = img.get("title", "") or img.get("alt", "")

        norm = normalize(display_name)
        NAME_TO_CLUB[norm] = (key, display_name)
        players_found.append({"name": display_name, "position": pos, "nationality": nat})

    CLUB_SQUADS[key] = players_found
    print(f"  {club['name']}: {len(players_found)} players from Transfermarkt")
    # Show first 5 for verification
    for p in players_found[:5]:
        print(f"    - {p['name']}")

print(f"  Total tracked players: {len(NAME_TO_CLUB)}")

# ── WC scorers ────────────────────────────────────────────────────────────────────
scorers_raw  = fetch_fd("/competitions/WC/scorers?season=2026&limit=200")
player_info  = {}   # fd_pid -> {name, nationality}
scorer_goals = {}   # fd_pid -> goals
PLAYER_CLUBS: dict[int, str] = {}  # fd_pid -> club_key (matched via name)

for entry in scorers_raw.get("scorers", []):
    p   = entry.get("player", {})
    pid = p.get("id")
    if not pid:
        continue
    name = p.get("name", "")
    player_info[pid]  = {"name": name, "nationality": p.get("nationality", "")}
    scorer_goals[pid] = entry.get("goals", 0)
    # Match by normalized name
    norm = normalize(name)
    if norm in NAME_TO_CLUB:
        club_key, tm_name = NAME_TO_CLUB[norm]
        PLAYER_CLUBS[pid] = club_key
        print(f"  MATCH: {name} [{tm_name}] -> {CLUBS[club_key]['name']} ({entry.get('goals',0)}g)")

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
            # Try name match for OG scorers too
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

    # Full squad with WC goals overlaid
    squad_out = []
    for p in CLUB_SQUADS[key]:
        norm = normalize(p["name"])
        pid  = next((i for i, info in player_info.items()
                     if normalize(info["name"]) == norm), None)
        g  = scorer_goals.get(pid, 0) if pid else 0
        og = og_map.get(pid, 0)        if pid else 0
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
