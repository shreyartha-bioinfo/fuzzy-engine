"""
Fetches FIFA World Cup 2026 goal data from football-data.org (free tier) and writes data.json.

Free tier approach:
  - /v4/competitions/WC/scorers  → regular goals per player + player.currentTeam (their club)
  - /v4/competitions/WC/matches  → OG events; scorer ID looked up in club map built from scorers
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
CLUB_IDS = {v["id"]: k for k, v in CLUBS.items()}   # 66 -> "utd", etc.

def fetch(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"X-Auth-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}\nResponse: {body}") from e

# ── WC scorers: regular goals + currentTeam → build player→club map ───────────
scorers_raw = fetch("/competitions/WC/scorers?season=2026&limit=200")

player_club  = {}   # player_id -> club_key  (only for our 3 clubs)
player_info  = {}   # player_id -> {name, nationality}
scorer_goals = {}   # player_id -> regular goal count

for entry in scorers_raw.get("scorers", []):
    p       = entry.get("player", {})
    pid     = p.get("id")
    club_id = (p.get("currentTeam") or {}).get("id")
    if not pid:
        continue
    player_info[pid] = {
        "name":        p.get("name", ""),
        "nationality": p.get("nationality", ""),
    }
    scorer_goals[pid] = entry.get("goals", 0)
    if club_id in CLUB_IDS:
        player_club[pid] = CLUB_IDS[club_id]

print(f"  WC scorers: {len(scorer_goals)} total, "
      f"{len(player_club)} from our 3 clubs")
# Debug: show raw structure of first 3 scorers
for entry in scorers_raw.get("scorers", [])[:3]:
    p = entry.get("player", {})
    print(f"  SAMPLE: {p.get('name')} | currentTeam={p.get('currentTeam')} | team={entry.get('team',{}).get('name')}")

# ── OG events from finished matches ──────────────────────────────────────────
matches_raw = fetch("/competitions/WC/matches?season=2026&status=FINISHED")
og_map = {}   # player_id -> own_goal count

for match in matches_raw.get("matches", []):
    for goal in match.get("goals", []):
        if goal.get("type") != "OWN_GOAL":
            continue
        scorer = goal.get("scorer") or {}
        pid    = scorer.get("id")
        if not pid:
            continue
        # record name in case they weren't in scorers list
        if pid not in player_info:
            player_info[pid] = {"name": scorer.get("name", ""), "nationality": ""}
        og_map[pid] = og_map.get(pid, 0) + 1

print(f"  Own goals: {sum(og_map.values())} across {len(og_map)} players")

# ── Build per-club output ─────────────────────────────────────────────────────
output = {"updated": datetime.now(timezone.utc).isoformat(), "clubs": {}}

for key, club in CLUBS.items():
    total_goals = total_ogs = 0
    scorers     = []

    # All players we know belong to this club
    club_pids = {pid for pid, ck in player_club.items() if ck == key}

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

    # OGs by players whose club we couldn't determine from scorers list
    # (they have 0 regular goals so didn't appear in scorers endpoint)
    for pid, og_count in og_map.items():
        if pid in club_pids:
            continue   # already counted above
        # We can't determine their club without /teams/{id}
        # Flag in output for awareness
        print(f"  WARNING: OG scorer {player_info.get(pid,{}).get('name', pid)} "
              f"club unknown (not in WC scorers list)")

    scorers.sort(key=lambda x: (-x["net"], -x["goals"]))

    output["clubs"][key] = {
        "name":     club["name"],
        "flag":     club["flag"],
        "goals":    total_goals,
        "ownGoals": total_ogs,
        "net":      total_goals - total_ogs,
        "scorers":  scorers,
        "squad":    scorers,   # on free tier, squad = only players who scored
    }
    print(f"  {club['name']}: {total_goals}G − {total_ogs}OG = {total_goals - total_ogs}")

# ── Upcoming fixtures (next 2 scheduled WC matches + lineups) ─────────────────────────
COUNTRY_FLAGS = {
    "Spain": "🇪🇸", "Cape Verde": "🇨🇻", "Belgium": "🇧🇪", "Egypt": "🇪🇬",
    "Saudi Arabia": "🇸🇦", "Uruguay": "🇺🇾", "Iran": "🇮🇷", "New Zealand": "🇳🇿",
    "France": "🇫🇷", "Senegal": "🇸🇳", "Iraq": "🇮🇶", "Norway": "🇳🇴",
    "Argentina": "🇦🇷", "Algeria": "🇩🇿", "Brazil": "🇧🇷", "Morocco": "🇲🇦",
    "Germany": "🇩🇪", "Japan": "🇯🇵", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "USA": "🇺🇸",
    "Mexico": "🇲🇽", "Portugal": "🇵🇹", "Netherlands": "🇳🇱", "Croatia": "🇭🇷",
    "Denmark": "🇩🇰", "Switzerland": "🇨🇭", "Austria": "🇦🇹", "Turkey": "🇹🇷",
    "Colombia": "🇨🇴", "Ecuador": "🇪🇨", "Chile": "🇨🇱", "Peru": "🇵🇪",
    "Australia": "🇦🇺", "South Korea": "🇰🇷", "Serbia": "🇷🇸", "Poland": "🇵🇱",
    "Czechia": "🇨🇿", "South Africa": "🇿🇦", "Ghana": "🇬🇭", "Senegal": "🇸🇳",
    "Tunisia": "🇹🇳", "Cameroon": "🇨🇲", "Nigeria": "🇳🇬", "Paraguay": "🇵🇾",
    "Costa Rica": "🇨🇷", "Honduras": "🇭🇳", "Panama": "🇵🇦", "Canada": "🇨🇦",
    "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Ukraine": "🇺🇦",
}

upcoming = []
try:
    sched_raw = fetch("/competitions/WC/matches?season=2026&status=SCHEDULED")
    sched_matches = sched_raw.get("matches", [])
    if not sched_matches:
        # also check IN_PLAY
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
            "lineup_status": "Predicted lineups from football-data.org",
        }
        # Try to get lineup from match detail
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
