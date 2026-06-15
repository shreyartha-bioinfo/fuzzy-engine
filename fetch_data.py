"""
Fetches FIFA World Cup 2026 goal data from football-data.org and writes data.json.
Runs server-side via GitHub Actions — no CORS issues.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN = os.environ["FD_TOKEN"]
BASE  = "https://api.football-data.org/v4"

CLUBS = {
    "utd": {"id": 66,  "name": "Manchester United", "flag": "🔴"},
    "rm":  {"id": 86,  "name": "Real Madrid",        "flag": "⚪"},
    "fcb": {"id": 5,   "name": "Bayern Munich",      "flag": "🔴"},
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

# ── Squads (current official squad per club) ─────────────────────────────────
squads = {}
for key, club in CLUBS.items():
    data = fetch(f"/teams/{club['id']}")
    squads[key] = {
        p["id"]: {"name": p["name"], "nationality": p.get("nationality") or ""}
        for p in data.get("squad", [])
    }
    print(f"  {club['name']}: {len(squads[key])} players")

# ── WC scorers (regular goals only — own goals excluded by the API) ───────────
scorers_raw = fetch("/competitions/WC/scorers?season=2026&limit=200")
scorer_map  = {}  # player_id -> goals
for entry in scorers_raw.get("scorers", []):
    pid = entry["player"]["id"]
    scorer_map[pid] = entry.get("goals", 0)
print(f"  WC scorers fetched: {len(scorer_map)}")

# ── Own goals — parsed from finished match goal events ───────────────────────
matches_raw = fetch("/competitions/WC/matches?season=2026&status=FINISHED")
og_map = {}  # player_id -> own_goal count
for match in matches_raw.get("matches", []):
    for goal in match.get("goals", []):
        if goal.get("type") != "OWN_GOAL":
            continue
        pid = (goal.get("scorer") or {}).get("id")
        if pid:
            og_map[pid] = og_map.get(pid, 0) + 1
print(f"  Own goals found: {sum(og_map.values())}")

# ── Cross-reference and build output ─────────────────────────────────────────
output = {
    "updated": datetime.now(timezone.utc).isoformat(),
    "clubs": {},
}

for key, club in CLUBS.items():
    squad       = squads[key]
    total_goals = 0
    total_ogs   = 0
    scorers     = []

    for pid, info in squad.items():
        g  = scorer_map.get(pid, 0)
        og = og_map.get(pid, 0)
        total_goals += g
        total_ogs   += og
        if g > 0 or og > 0:
            scorers.append({
                "name":        info["name"],
                "nationality": info["nationality"],
                "goals":       g,
                "ownGoals":    og,
                "net":         g - og,
            })

    scorers.sort(key=lambda x: (-x["net"], -x["goals"]))

    full_squad = sorted(
        [{"name": info["name"], "nationality": info["nationality"],
          "goals": scorer_map.get(pid, 0), "ownGoals": og_map.get(pid, 0),
          "net": scorer_map.get(pid, 0) - og_map.get(pid, 0)}
         for pid, info in squad.items()],
        key=lambda x: (-x["net"], x["name"])
    )

    output["clubs"][key] = {
        "name":     club["name"],
        "flag":     club["flag"],
        "goals":    total_goals,
        "ownGoals": total_ogs,
        "net":      total_goals - total_ogs,
        "scorers":  scorers,
        "squad":    full_squad,
    }
    print(f"  {club['name']}: {total_goals}G − {total_ogs}OG = {total_goals - total_ogs}")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print("data.json written.")
