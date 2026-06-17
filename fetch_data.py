"""Fetches FIFA World Cup 2026 goal data from football-data.org (free tier)
and transfer rumors from Google News RSS.
"""
import json
import os
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

TOKEN = os.environ["FD_TOKEN"]
BASE  = "https://api.football-data.org/v4"

CLUBS = {
    "utd": {"id": 66,  "league": "PL",  "name": "Manchester United", "flag": "\U0001f534",
            "news_q": "Manchester+United+transfer"},
    "rm":  {"id": 86,  "league": "PD",  "name": "Real Madrid",        "flag": "⚪",
            "news_q": "Real+Madrid+transfer"},
    "fcb": {"id": 5,   "league": "BL1", "name": "Bayern Munich",      "flag": "\U0001f534",
            "news_q": "Bayern+Munich+transfer"},
}

OVERRIDES = {
    "utd": {
        "remove": set(),
        "add":    [{"name": "Marcus Rashford", "position": "Offence", "nationality": "England"}],
    },
    "rm": {
        "remove": {"David Alaba", "Dávid Alaba", "Daniel Carvajal", "D. Carvajal"},
        "add":    [{"name": "Marc Cucurella", "position": "Defence", "nationality": "Spain"},
                   {"name": "Bernardo Silva", "position": "Midfield", "nationality": "Portugal"}],
    },
    "fcb": {
        "remove": {"Nicolas Jackson", "Raphaël Guerreiro"},
        "add":    [],
    },
}

# join_date (YYYY-MM-DD) per player name for mid-tournament transfers.
# Goals scored before this date won't count for that club.
# Example: {"Bernardo Silva": "2026-06-15"}
TRANSFER_DATES: dict[str, str] = {}

COUNTRY_FLAGS = {
    "Spain": "🇪🇸", "Cabo Verde": "🇨🇻", "Cape Verde": "🇨🇻", "Belgium": "🇧🇪", "Egypt": "🇪🇬",
    "Saudi Arabia": "🇸🇦", "Uruguay": "🇺🇾", "Iran": "🇮🇷", "New Zealand": "🇳🇿",
    "France": "🇫🇷", "Senegal": "🇸🇳", "Iraq": "🇮🇶", "Norway": "🇳🇴",
    "Argentina": "🇦🇷", "Algeria": "🇩🇿", "Brazil": "🇧🇷", "Morocco": "🇲🇦",
    "Germany": "🇩🇪", "Japan": "🇯🇵", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "USA": "🇺🇸",
    "Mexico": "🇲🇽", "Portugal": "🇵🇹", "Netherlands": "🇳🇱", "Croatia": "🇭🇷",
    "Denmark": "🇩🇰", "Switzerland": "🇨🇭", "Austria": "🇦🇹", "Turkey": "🇹🇷",
    "Colombia": "🇨🇴", "Ecuador": "🇪🇨", "Chile": "🇨🇱", "Peru": "🇵🇪",
    "Australia": "🇦🇺", "South Korea": "🇰🇷", "Serbia": "🇷🇸", "Poland": "🇵🇱",
    "Czechia": "🇨🇿", "South Africa": "🇿🇦", "Ghana": "🇬🇭",
    "Tunisia": "🇹🇳", "Cameroon": "🇨🇲", "Nigeria": "🇳🇬", "Paraguay": "🇵🇾",
    "Costa Rica": "🇨🇷", "Honduras": "🇭🇳", "Panama": "🇵🇦", "Canada": "🇨🇦",
    "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Ukraine": "🇺🇦",
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

def fetch_rumors(query: str, limit: int = 5) -> list[dict]:
    url = (f"https://news.google.com/rss/search"
           f"?q={query}&hl=en-US&gl=US&ceid=US:en")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            xml_data = r.read()
    except Exception as e:
        print(f"  News fetch failed: {e}")
        return []
    items = []
    try:
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:limit]:
            title  = item.findtext("title", "").strip()
            link   = item.findtext("link", "").strip()
            pub    = item.findtext("pubDate", "").strip()
            source = item.findtext("source", "").strip()
            title = re.sub(r'\s+-\s+[^-]+$', '', title).strip()
            if title:
                items.append({"title": title, "url": link,
                              "source": source, "published": pub})
    except ET.ParseError as e:
        print(f"  RSS parse error: {e}")
    return items

# ── Build player->club map + squad lists ──────────────────────────────────────
PLAYER_CLUBS: dict[int, str] = {}
CLUB_SQUADS:  dict[str, list] = {key: [] for key in CLUBS}
EXTRA_NAMES:  dict[str, str]  = {}

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
            if name.lower() in removes:
                print(f"  OVERRIDE REMOVE: {name} from {club['name']}")
                continue
            pos = player.get("position", "")
            nat = player.get("nationality", "")
            if pid:
                PLAYER_CLUBS[pid] = key
                CLUB_SQUADS[key].append({"id": pid, "name": name, "position": pos, "nationality": nat})
        for extra in adds:
            CLUB_SQUADS[key].append({"id": None, **extra})
            EXTRA_NAMES[extra["name"].lower()] = key
            print(f"  OVERRIDE ADD: {extra['name']} to {club['name']}")
        CLUB_SQUADS[key].sort(key=lambda p: (pos_order.get(p.get("position", ""), 9), p["name"]))
        print(f"  {club['name']}: {len(CLUB_SQUADS[key])} squad members")
        break
    else:
        print(f"  WARNING: {club['name']} not found in {club['league']} teams")

# ── Transfer rumors ───────────────────────────────────────────────────────────
rumors = {}
for key, club in CLUBS.items():
    items = fetch_rumors(club["news_q"])
    rumors[key] = items
    print(f"  {club['name']} rumors: {len(items)} items")

# ── WC scorers (used for player name/nationality discovery only) ──────────────
scorers_raw = fetch("/competitions/WC/scorers?season=2026&limit=200")
player_info: dict[int, dict] = {}

for entry in scorers_raw.get("scorers", []):
    p   = entry.get("player", {})
    pid = p.get("id")
    if not pid:
        continue
    name = p.get("name", "")
    player_info[pid] = {"name": name, "nationality": p.get("nationality", "")}
    if name.lower() in EXTRA_NAMES:
        PLAYER_CLUBS[pid] = EXTRA_NAMES[name.lower()]

print(f"  WC scorers discovered: {len(player_info)}")

# ── Per-match goal events (regular + OG) with dates ──────────────────────────
# Structure: goal_events[pid] = [{"date": "YYYY-MM-DD", "og": bool}, ...]
goal_events: dict[int, list] = {}

matches_raw = fetch("/competitions/WC/matches?season=2026&status=FINISHED")
for match in matches_raw.get("matches", []):
    match_date = (match.get("utcDate") or "")[:10]
    for goal in match.get("goals", []):
        is_og  = goal.get("type") == "OWN_GOAL"
        scorer = goal.get("scorer") or {}
        pid    = scorer.get("id")
        if not pid:
            continue
        if pid not in player_info:
            player_info[pid] = {"name": scorer.get("name", ""), "nationality": ""}
        if pid not in PLAYER_CLUBS and scorer.get("name", "").lower() in EXTRA_NAMES:
            PLAYER_CLUBS[pid] = EXTRA_NAMES[scorer["name"].lower()]
        goal_events.setdefault(pid, []).append({"date": match_date, "og": is_og})

total_goals_found = sum(1 for evts in goal_events.values() for e in evts if not e["og"])
total_ogs_found   = sum(1 for evts in goal_events.values() for e in evts if e["og"])
print(f"  Match events: {total_goals_found} goals, {total_ogs_found} OGs across {len(goal_events)} players")

def count_goals(pid: int, join_date: str = "2000-01-01") -> tuple[int, int]:
    """Return (goals, own_goals) for pid scored on or after join_date."""
    evts = goal_events.get(pid, [])
    g  = sum(1 for e in evts if not e["og"] and e["date"] >= join_date)
    og = sum(1 for e in evts if     e["og"] and e["date"] >= join_date)
    return g, og

# ── Build per-club output ─────────────────────────────────────────────────────
output = {"updated": datetime.now(timezone.utc).isoformat(), "clubs": {}, "rumors": rumors}

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers = []
    club_pids = {p["id"] for p in CLUB_SQUADS[key] if p["id"] is not None}
    club_pids |= {pid for pid, ck in PLAYER_CLUBS.items() if ck == key}

    # Resolve join dates: look up by player name in TRANSFER_DATES
    def join_date_for(pid: int) -> str:
        name = player_info.get(pid, {}).get("name", "")
        return TRANSFER_DATES.get(name, "2000-01-01")

    for pid in club_pids:
        g, og = count_goals(pid, join_date_for(pid))
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
    for p in CLUB_SQUADS[key]:
        pid = p["id"]
        if pid is None:
            pid = next((i for i, info in player_info.items()
                        if info["name"].lower() == p["name"].lower()), None)
        jd = TRANSFER_DATES.get(p["name"], "2000-01-01")
        g, og = count_goals(pid, jd) if pid else (0, 0)
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

# ── Upcoming fixtures (next 2 scheduled WC matches + lineups) ─────────────────
upcoming = []
try:
    sched_raw = fetch("/competitions/WC/matches?season=2026&status=SCHEDULED")
    sched_matches = sched_raw.get("matches", [])
    if not sched_matches:
        live_raw = fetch("/competitions/WC/matches?season=2026&status=IN_PLAY")
        sched_matches = live_raw.get("matches", [])
    for m in sched_matches[:2]:
        home_name = m.get("homeTeam", {}).get("name", "TBD")
        away_name = m.get("awayTeam", {}).get("name", "TBD")
        fixture = {
            "id":     m.get("id"),
            "date":   m.get("utcDate"),
            "group":  m.get("group", "Group Stage"),
            "status": m.get("status"),
            "home":   {"name": home_name, "flag": COUNTRY_FLAGS.get(home_name, "🏳"), "lineup": []},
            "away":   {"name": away_name, "flag": COUNTRY_FLAGS.get(away_name, "🏳"), "lineup": []},
            "lineup_status": "Lineup TBA — check back closer to kickoff",
        }
        try:
            detail = fetch(f"/matches/{m['id']}")
            for side, key_name in [("home", "homeTeam"), ("away", "awayTeam")]:
                team_detail = detail.get(key_name, {})
                lineup_raw = team_detail.get("lineup", [])
                if lineup_raw:
                    fixture[side]["lineup"] = [
                        {"name": p.get("name",""), "position": p.get("position","")}
                        for p in lineup_raw
                    ]
                    fixture["lineup_status"] = "Lineups confirmed"
        except Exception as e:
            print(f"  Match detail fetch failed for {m.get('id')}: {e}")
        upcoming.append(fixture)
    print(f"  Upcoming: {len(upcoming)} fixtures")
except Exception as e:
    print(f"  Upcoming fixtures fetch failed: {e}")

output["upcoming"] = upcoming

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print("data.json written.")
