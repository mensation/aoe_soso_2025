import json
import os
import random
from collections import defaultdict
from datetime import datetime, date, time
from pathlib import Path
from typing import Optional

import requests

import pandas as pd
import streamlit as st

# -------------------------
# League Configuration
# -------------------------

PLAYERS = ["Dahn", "Manu", "Homi", "Tobi", "Till"]

# Matches (after swapping rounds 2 and 4)
# A = higher seed, B = lower seed
MATCHES = [
    {"id": 1, "round": 1, "A": "Dahn", "B": "Homi"},
    {"id": 2, "round": 1, "A": "Tobi", "B": "Manu"},
    {"id": 3, "round": 2, "A": "Dahn", "B": "Manu"},
    {"id": 4, "round": 2, "A": "Tobi", "B": "Till"},
    {"id": 5, "round": 3, "A": "Manu", "B": "Till"},
    {"id": 6, "round": 3, "A": "Homi", "B": "Tobi"},
    {"id": 7, "round": 4, "A": "Dahn", "B": "Tobi"},
    {"id": 8, "round": 4, "A": "Till", "B": "Homi"},
    {"id": 9, "round": 5, "A": "Dahn", "B": "Till"},
    {"id": 10, "round": 5, "A": "Manu", "B": "Homi"},
]

DEADLINES = {
    1: "December 7 - 23:59",
    2: "December 14 - 23:59",
    3: "December 21 - 23:59",
    4: "December 28 - 23:59",
    5: "January 4 - 23:59",
}

BASE_DIR = Path(__file__).resolve().parent
RESULTS_FILE = BASE_DIR / "results.json"

GIST_FILENAME = "results.json"
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", None)
GIST_ID = st.secrets.get("GIST_ID", None)

MAP_IMAGES = {
    "Arabia": BASE_DIR / "arabia.png",
    "Arena": BASE_DIR / "arena.png",
    "Nomad": BASE_DIR / "nomad.png",
    # Additional map art available if needed elsewhere:
    "Fish 'n' Fish": BASE_DIR / "fishnfish.png",
    "HyperRandom": BASE_DIR / "hyper random.png",
    "Land Madness": BASE_DIR / "land_madness.png",
    "Socotra": BASE_DIR / "socotra.png",
}


# -------------------------
# Rules Markdown
# -------------------------

RULES_MD = """
# AOE2 Standing Ovations League 2025

## Participants
1. **Dahn**  
2. **Manu**  
3. **Homi**  
4. **Tobi**  
5. **Till**

---

## Schedule & Deadlines

- **Round 1:** December 7 - *23:59*  
- **Round 2:** December 14 - *23:59*  
- **Round 3:** December 21 - *23:59*  
- **Round 4:** December 28 - *23:59*  
- **Round 5:** January 4 - *23:59*

If players cannot agree on a time, the default time is **Tuesday 21:00** of that round week.

---

## Match Format

Each match consists of **three games**, and **all three games are always played**.

**Game 1**  
- Players attempt to agree on any map from the pool.  
- If no agreement is reached within ~5 minutes:  
  -> Randomly select one of: **Arabia**, **Arena**, **Nomad**.

**Map Bans (before home maps)**  
1. Higher seed bans one map from the full map pool.  
2. Lower seed bans one map from the remaining pool.  
These bans apply to **Game 2 and Game 3 only**.

**Game 2** - Home map of the higher seed (Player A).  
**Game 3** - Home map of the lower seed (Player B).  

---

## Map Pool

The official map pool for the league is:

- **Arabia**  
- **Arena**  
- **Nomad**  
- **Fish 'n' Fish**  
- **Enclosed**  
- **HyperRandom**  
- **Land Madness**  
- **Socotra**  

Each player has selected one personal map from this set to include in the pool.

---

## Patch & Civilization Rules

- Tournament is played on the **latest Age of Empires II: Definitive Edition patch**.  
- All civilizations allowed in ranked matchmaking are permitted.

---

## Civilization Draft (Per Match)

1. Each player selects **two hidden civilizations** upfront.  
2. Civilization pick order (snake draft): **B -> A -> A -> B -> B -> A**  
   - **A** = higher seed  
   - **B** = lower seed  
3. After picks are revealed, each player **bans one civilization** from the opponent's pool.  
   The remaining civilizations are available to that player for the match.

---

_For tiebreakers and current standings, see the **Standings** panel._ dummy test
"""


# -------------------------
# Persistence Helpers
# -------------------------

def load_results():
    """Load results from JSON file, or initialize empty structure."""
    data = None
    if GITHUB_TOKEN and GIST_ID:
        data = load_results_from_gist(GIST_ID, GITHUB_TOKEN)
    if data is None and RESULTS_FILE.exists():
        try:
            data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = None

    if data is None:
        data = {}
    for m in MATCHES:
        mid = str(m["id"])
        if mid not in data:
            data[mid] = {"g1": "", "g2": "", "g3": "", "scheduled": ""}
        else:
            data[mid].setdefault("g1", "")
            data[mid].setdefault("g2", "")
            data[mid].setdefault("g3", "")
            data[mid].setdefault("scheduled", "")
    return data


def save_results(results):
    """Write results atomically to disk to avoid partial writes on Streamlit Cloud."""
    payload = json.dumps(results, indent=2)
    if GITHUB_TOKEN:
        gid = st.session_state.get("GIST_ID_CACHE") or GIST_ID
        gid, err = save_results_to_gist(payload, GITHUB_TOKEN, gid)
        if gid:
            if gid != GIST_ID and not st.session_state.get("GIST_ID_CACHE"):
                st.session_state["GIST_ID_CACHE"] = gid
                st.info(f"New Gist created. Save this ID in secrets as GIST_ID: {gid}")
            return
        if err:
            st.warning(f"Gist save failed; falling back to local file. Details: {err}")

    tmp_path = RESULTS_FILE.with_suffix(".tmp")
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(RESULTS_FILE)


# -------------------------
# Standings Calculation
# -------------------------

def compute_match_stats(results):
    """
    Compute per-match map wins and match winner from raw game winner input.
    Returns dict: match_id -> {"A_maps", "B_maps", "winner"}.
    """
    stats = {}
    for m in MATCHES:
        mid = str(m["id"])
        A = m["A"]
        B = m["B"]
        entry = results.get(mid, {})
        g1 = entry.get("g1", "")
        g2 = entry.get("g2", "")
        g3 = entry.get("g3", "")

        a_maps = 0
        b_maps = 0
        for gw in (g1, g2, g3):
            if gw == A:
                a_maps += 1
            elif gw == B:
                b_maps += 1

        if a_maps > b_maps:
            winner = A
        elif b_maps > a_maps:
            winner = B
        else:
            winner = ""

        stats[mid] = {
            "A_maps": a_maps,
            "B_maps": b_maps,
            "winner": winner,
        }
    return stats


def compute_player_aggregate(match_stats):
    """
    Compute overall stats per player:
    matches played, wins, losses, map wins, map losses.
    """
    agg = {
        p: {
            "player": p,
            "matches_played": 0,
            "match_wins": 0,
            "match_losses": 0,
            "map_wins": 0,
            "map_losses": 0,
        }
        for p in PLAYERS
    }

    for m in MATCHES:
        mid = str(m["id"])
        A = m["A"]
        B = m["B"]
        ms = match_stats[mid]

        a_maps = ms["A_maps"]
        b_maps = ms["B_maps"]
        winner = ms["winner"]

        if a_maps + b_maps == 0:
            continue

        agg[A]["matches_played"] += 1
        agg[B]["matches_played"] += 1

        agg[A]["map_wins"] += a_maps
        agg[A]["map_losses"] += b_maps
        agg[B]["map_wins"] += b_maps
        agg[B]["map_losses"] += a_maps

        if winner == A:
            agg[A]["match_wins"] += 1
            agg[B]["match_losses"] += 1
        elif winner == B:
            agg[B]["match_wins"] += 1
            agg[A]["match_losses"] += 1

    return agg


def compute_direct_comparison_helpers(agg, match_stats):
    """
    For players with the same number of match wins, compute mini-table stats:
    - mini_match_wins
    - mini_map_wins
    """
    wins_groups = defaultdict(list)
    for p, row in agg.items():
        wins_groups[row["match_wins"]].append(p)

    mini = {p: {"mini_match_wins": 0, "mini_map_wins": 0} for p in PLAYERS}

    for match in MATCHES:
        mid = str(match["id"])
        A = match["A"]
        B = match["B"]
        ms = match_stats[mid]
        a_maps = ms["A_maps"]
        b_maps = ms["B_maps"]
        winner = ms["winner"]

        group = None
        for _, players in wins_groups.items():
            if A in players and B in players:
                group = players
                break

        if not group:
            continue

        if a_maps + b_maps == 0:
            continue

        mini[A]["mini_map_wins"] += a_maps
        mini[B]["mini_map_wins"] += b_maps

        if winner == A:
            mini[A]["mini_match_wins"] += 1
        elif winner == B:
            mini[B]["mini_match_wins"] += 1

    return mini


def compute_standings(results):
    match_stats = compute_match_stats(results)
    agg = compute_player_aggregate(match_stats)
    mini = compute_direct_comparison_helpers(agg, match_stats)

    table = []
    for p in PLAYERS:
        row = agg[p].copy()
        row["mini_match_wins"] = mini[p]["mini_match_wins"]
        row["mini_map_wins"] = mini[p]["mini_map_wins"]
        table.append(row)

    table.sort(key=lambda r: r["player"])
    table.sort(
        key=lambda r: (
            r["match_wins"],
            r["mini_match_wins"],
            r["mini_map_wins"],
            r["map_wins"],
        ),
        reverse=True,
    )

    return table


def scores_to_game_winners(a_maps, b_maps, player_a, player_b):
    """Map numeric map wins to per-game winners while keeping the existing logic."""
    winners = [player_a] * a_maps + [player_b] * b_maps
    winners += [""] * (3 - len(winners))
    return winners[:3]


def load_results_from_gist(gist_id: str, token: str) -> Optional[dict]:
    """Fetch results.json content from a GitHub Gist. Returns dict or None on failure."""
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        files = resp.json().get("files", {})
        content = files.get(GIST_FILENAME, {}).get("content")
        if not content:
            return None
        return json.loads(content)
    except Exception:
        return None


def save_results_to_gist(payload: str, token: str, gist_id: Optional[str]):
    """Save results.json to an existing or new Gist. Returns (gist_id, error_msg)."""
    headers = {"Authorization": f"token {token}"}
    try:
        if gist_id:
            resp = requests.patch(
                f"https://api.github.com/gists/{gist_id}",
                headers=headers,
                json={"files": {GIST_FILENAME: {"content": payload}}},
                timeout=10,
            )
            if resp.status_code in (200, 201):
                return gist_id, None
            return None, f"Gist patch failed (status {resp.status_code})"
        else:
            resp = requests.post(
                "https://api.github.com/gists",
                headers=headers,
                json={
                    "description": "AOE2 league results storage",
                    "public": False,
                    "files": {GIST_FILENAME: {"content": payload}},
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                return resp.json().get("id"), None
            return None, f"Gist create failed (status {resp.status_code})"
    except Exception as exc:
        return None, f"Gist save error: {exc}"
    return None, "Unknown Gist save error"


def parse_scheduled_value(value):
    """Return (date, time) from stored string if possible."""
    try:
        dt = datetime.fromisoformat(value)
        return dt.date(), dt.time().replace(second=0, microsecond=0)
    except Exception:
        return None, None


# -------------------------
# Streamlit UI
# -------------------------

st.set_page_config(
    page_title="AOE2 Standing Ovations League 2025",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --bg-dark: #0b1120;
        --panel: rgba(255, 255, 255, 0.04);
        --panel-border: #1f2a40;
        --gold: #fbbf24;
        --text: #e5e7eb;
        --muted: #94a3b8;
    }
    .main {
        background: radial-gradient(circle at 12% 20%, #1e293b 0, #0b1120 35%, #020617 100%);
        color: var(--text);
    }
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1.4rem;
        max-width: 1400px;
    }
    h1, h2, h3 {
        color: var(--gold) !important;
        letter-spacing: 0.02em;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: #0f172a;
        padding: 8px 10px;
        border-radius: 14px;
        border: 1px solid #1f2a40;
        box-shadow: 0 10px 30px rgba(0,0,0,0.25);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 12px;
        background-color: #0b1222;
        color: var(--text);
        font-weight: 700;
        border: 1px solid #1f2937;
        transition: all 0.15s ease;
    }
    .stTabs [data-baseweb="tab"]:hover { background-color: #152036; }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #fbbf24, #f59e0b);
        color: #0b1120 !important;
        border-color: #fbbf24 !important;
        box-shadow: 0 4px 16px rgba(251,191,36,0.35);
    }
    .round-header {
        color: var(--muted);
        font-weight: 600;
        margin-top: 0.2rem;
        margin-bottom: 0.05rem;
    }
    .round-divider {
        border-bottom: 1px solid #1f2a40;
        margin: 0.25rem 0 0.45rem 0;
    }
    .pairing-line {
        font-weight: 700;
        color: var(--text);
        font-size: 0.95rem;
        margin-bottom: 0.05rem;
    }
    .seed-pill {
        display: inline-block;
        padding: 2px 7px;
        border-radius: 999px;
        background: #111827;
        border: 1px solid #1f2a40;
        color: var(--gold);
        font-size: 0.75rem;
        letter-spacing: 0.05em;
        margin-right: 6px;
    }
    .seed-pill.seed-b { color: #cbd5e1; }
    .muted {
        color: var(--muted);
        font-size: 0.85rem;
    }
    .muted-sm { color: var(--muted); font-size: 0.78rem; margin-bottom: -4px; }
    input[type=number] {
        text-align: center;
    }
    .card {
        background: var(--panel);
        border: 1px solid var(--panel-border);
        border-radius: 12px;
        padding: 0.75rem 0.9rem;
        margin-bottom: 0.65rem;
    }
    .card h4 { margin-bottom: 0.4rem; }
    .pill {
        display: inline-block;
        padding: 6px 10px;
        border-radius: 10px;
        background: #111827;
        border: 1px solid #1f2a40;
        color: var(--gold);
        font-weight: 700;
        margin: 0 6px 6px 0;
        font-size: 0.9rem;
    }
    .map-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 6px;
    }
    .map-chip {
        padding: 6px 8px;
        border-radius: 8px;
        background: #111827;
        border: 1px solid #1f2a40;
    }
    .stNumberInput, .stTextInput {
        margin-top: -4px;
        margin-bottom: -4px;
    }
    .stNumberInput>div>div>input {
        padding-top: 4px;
        padding-bottom: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("AOE2 Standing Ovations League 2025")
st.caption("Enter best-of-three map scores and track live standings.")

if "results" not in st.session_state:
    st.session_state["results"] = load_results()

results = st.session_state["results"]
rounds = sorted(set(m["round"] for m in MATCHES))

tabs = st.tabs(["HELPFULL", "Dashboard", "Rules"])

# ---------- Helpful ----------
with tabs[0]:
    link_col, map_col = st.columns([2, 1], gap="small")
    with link_col:
        draft_box = st.container(border=True)
        draft_box.markdown("**Civilization Draft Preset**")
        draft_box.markdown(
            "Click this button to create a civ draft for a new game. "
            "The higher-seeded player should host the draft."
        )
        draft_box.link_button(
            "Open Civ Draft (aoe2cm)",
            "https://aoe2cm.net/preset/kzbHC",
            use_container_width=True,
        )
    with map_col:
        if st.button("Random G1 Map (Arabia/Arena/Nomad)", type="primary", use_container_width=True):
            st.session_state["random_g1_map"] = random.choice(["Arabia", "Arena", "Nomad"])
        map_card = st.container(border=True)
        if st.session_state.get("random_g1_map"):
            picked = st.session_state["random_g1_map"]
            img_url = MAP_IMAGES.get(picked)
            map_card.markdown(f"**Game 1 Map:** {picked}")
            if img_url:
                map_card.image(img_url, caption=picked, width="stretch")
            else:
                map_card.caption("No preview available; showing text only.")
        else:
            map_card.caption("Roll to pick a Game 1 map.")


# ---------- Dashboard ----------
with tabs[1]:
    st.markdown(
        "Enter map wins (best-of-three). Totals per match must be **<= 3**. "
        "Optional: add a scheduled date/time note per match."
    )
    left_col, right_col = st.columns([1.8, 1.2], gap="medium")

    defaults_stats = compute_match_stats(results)
    invalid_matches = []

    with left_col:
        st.markdown("#### Matches")
        for rnd in rounds:
            deadline = DEADLINES.get(rnd, "No deadline set")

            round_matches = [m for m in MATCHES if m["round"] == rnd]
            for m in round_matches:
                mid = str(m["id"])
                A = m["A"]
                B = m["B"]
                a_key = f"match_{mid}_score_a"
                b_key = f"match_{mid}_score_b"
                schedule_key = f"match_{mid}_scheduled"
                default_a = defaults_stats.get(mid, {}).get("A_maps", 0)
                default_b = defaults_stats.get(mid, {}).get("B_maps", 0)
                st.session_state.setdefault(a_key, default_a)
                st.session_state.setdefault(b_key, default_b)
                st.session_state.setdefault(schedule_key, results[mid].get("scheduled", ""))

                row = st.columns([1.1, 0.6, 0.6, 0.45, 0.9, 0.9])
                with row[0]:
                    st.markdown(
                        f"<div class='pairing-line'>Match {mid}: {A} vs {B}</div>"
                        f"<div class='muted-sm'>R{rnd} - Deadline {deadline}</div>",
                        unsafe_allow_html=True,
                    )
                with row[1]:
                    st.markdown(f"<div class='muted-sm'>{A}</div>", unsafe_allow_html=True)
                    a_score = st.number_input(
                        f"{A} maps",
                        min_value=0,
                        max_value=3,
                        step=1,
                        key=a_key,
                        label_visibility="collapsed",
                    )
                with row[2]:
                    st.markdown(f"<div class='muted-sm'>{B}</div>", unsafe_allow_html=True)
                    b_score = st.number_input(
                        f"{B} maps",
                        min_value=0,
                        max_value=3,
                        step=1,
                        key=b_key,
                        label_visibility="collapsed",
                    )
                with row[3]:
                    st.markdown("<div class='muted-sm'>Total</div>", unsafe_allow_html=True)
                    st.markdown(f"**{a_score + b_score}/3**")
                parsed_date, parsed_time = parse_scheduled_value(st.session_state[schedule_key])
                default_date = parsed_date or date.today()
                default_time = parsed_time or time(hour=21, minute=0)
                with row[4]:
                    st.markdown("<div class='muted-sm'>Date / Time</div>", unsafe_allow_html=True)
                    sched_date = st.date_input(
                        "Date",
                        value=default_date,
                        key=f"{schedule_key}_date",
                        label_visibility="collapsed",
                    )
                with row[5]:
                    st.markdown("<div class='muted-sm' style='visibility:hidden;'>spacer</div>", unsafe_allow_html=True)
                    sched_time = st.time_input(
                        "Time",
                        value=default_time,
                        key=f"{schedule_key}_time",
                        step=900,
                        label_visibility="collapsed",
                    )
                    schedule_val = f"{sched_date} {sched_time.strftime('%H:%M')}"

                total_maps = a_score + b_score
                results[mid]["scheduled"] = schedule_val.strip()
                if total_maps > 3:
                    invalid_matches.append(mid)
                else:
                    winners = scores_to_game_winners(a_score, b_score, A, B)
                    results[mid]["g1"], results[mid]["g2"], results[mid]["g3"] = winners

            st.markdown("<div class='round-divider'></div>", unsafe_allow_html=True)

        st.session_state["results"] = results

        if invalid_matches:
            st.warning(
                "Max 3 games per match. Please adjust totals for matches: "
                + ", ".join(invalid_matches)
            )

        if st.button(
            "Save results",
            type="primary",
            use_container_width=True,
            disabled=bool(invalid_matches),
        ):
            try:
                save_results(st.session_state["results"])
                st.success("Results saved.")
            except Exception as exc:
                st.error(f"Failed to save results: {exc}")

    standings = compute_standings(st.session_state["results"])

    with right_col:
        st.markdown("#### Standings")

        if all(row["matches_played"] == 0 for row in standings):
            st.info("No games recorded yet. Enter some results to see the table.")
        else:
            rows = []
            for pos, row in enumerate(standings, start=1):
                rows.append(
                    {
                        "Pos": pos,
                        "Player": row["player"],
                        "MP": row["matches_played"],
                        "W": row["match_wins"],
                        "L": row["match_losses"],
                        "MW": row["map_wins"],
                        "ML": row["map_losses"],
                        "Mini W": row["mini_match_wins"],
                        "Mini MW": row["mini_map_wins"],
                    }
                )

            df = pd.DataFrame(rows)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                height=520,
            )

            st.caption(
                "Tiebreakers: match wins -> direct comparison (mini match wins, mini map wins) -> total map wins -> coin toss."
            )


# ---------- Rules ----------
with tabs[2]:
    st.markdown("#### Rules & Info")
    pills = " ".join([f"<span class='pill'>{p}</span>" for p in PLAYERS])
    st.markdown(
        f"""
        <div class='card'>
            <h4>Seeding (highest to lowest)</h4>
            <div class='muted-sm' style='margin-bottom:6px;'>Order of players</div>
            {pills}
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns(2, gap="medium")

    schedule_list = "".join(
        f"<li><strong>Round {rnd}:</strong> {deadline}</li>"
        for rnd, deadline in DEADLINES.items()
    )

    with col_left:
        st.markdown(
            f"""
            <div class='card'>
                <h4>Schedule</h4>
                <ul style='margin-bottom: 0;'>
                    {schedule_list}
                </ul>
                <div class='muted-sm'>Default time if needed: Tuesday 21:00.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class='card'>
                <h4>Match Format</h4>
                <ul style='margin-bottom: 0.3rem;'>
                    <li>Best-of-three; all three games are played.</li>
                    <li>Game 1: any agreed map, else random from Arabia / Arena / Nomad.</li>
                    <li>Map bans (Game 2 & 3): higher seed bans 1, lower seed bans 1.</li>
                    <li>Game 2: higher seed home map. Game 3: lower seed home map.</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    map_pool = [
        "Arabia",
        "Arena",
        "Nomad",
        "Fish 'n' Fish",
        "Enclosed",
        "HyperRandom",
        "Land Madness",
        "Socotra",
    ]

    with col_right:
        pool_html = """
            <div class='card'>
                <h4>Map Pool</h4>
                <div class='map-grid'>
        """
        for m in map_pool:
            pool_html += f"<div class='map-chip'>{m}</div>"
        pool_html += "</div></div>"
        st.markdown(pool_html, unsafe_allow_html=True)

        st.markdown(
            """
            <div class='card'>
                <h4>Civ Draft & Rules</h4>
                <ul style='margin-bottom: 0.3rem;'>
                    <li>Play on latest AOE2:DE patch; all ranked civs allowed.</li>
                    <li>Each player picks two hidden civs.</li>
                    <li>Pick order (snake): B -> A -> A -> B -> B -> A.</li>
                    <li>After picks: each player bans one of the opponent's picked civs.</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
