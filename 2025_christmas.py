import json
import os
from collections import defaultdict

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

RESULTS_FILE = "results.json"


# -------------------------
# Rules Markdown
# -------------------------

RULES_MD = """
# AOE2 Standing Ovations League 2025

## Participants & Seeding
1. **Dahn**  
2. **Manu**  
3. **Homi**  
4. **Tobi**  
5. **Till**

Seeding affects:
- Higher/lower seed in each match  
- Map ban order  
- Home map pick order  
- Civilization pick order  

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

_For tiebreakers and current standings, see the **Standings** panel._
"""


# -------------------------
# Persistence Helpers
# -------------------------

def load_results():
    """Load results from JSON file, or initialize empty structure."""
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for m in MATCHES:
                mid = str(m["id"])
                if mid not in data:
                    data[mid] = {"g1": "", "g2": "", "g3": ""}
            return data
        except Exception:
            pass

    results = {}
    for m in MATCHES:
        mid = str(m["id"])
        results[mid] = {"g1": "", "g2": "", "g3": ""}
    return results


def save_results(results):
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


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
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] {
        padding-top: 7px;
        padding-bottom: 7px;
        border-radius: 12px;
        background-color: #111827;
        color: var(--text);
        font-weight: 600;
        border: 1px solid #1f2937;
    }
    .stTabs [data-baseweb="tab"]:hover { background-color: #1f2937; }
    .stTabs [aria-selected="true"] {
        background-color: var(--gold) !important;
        color: #0b1120 !important;
        border-color: #f59e0b !important;
    }
    .round-header {
        color: var(--muted);
        font-weight: 600;
        margin-top: 0.35rem;
        margin-bottom: 0.15rem;
    }
    .round-divider {
        border-bottom: 1px solid #1f2a40;
        margin: 0.35rem 0 0.6rem 0;
    }
    .pairing-line {
        font-weight: 700;
        color: var(--text);
        font-size: 1rem;
        margin-bottom: 0.1rem;
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
    input[type=number] {
        text-align: center;
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

tabs = st.tabs(["Dashboard", "Rules"])


# ---------- Dashboard ----------
with tabs[0]:
    st.markdown("Enter map wins (best-of-three). Totals per match must be **<= 3**.")
    left_col, right_col = st.columns([1.8, 1.2], gap="medium")

    defaults_stats = compute_match_stats(results)
    invalid_matches = []

    with left_col:
        st.markdown("#### Matches")
        for rnd in rounds:
            deadline = DEADLINES.get(rnd, "No deadline set")
            st.markdown(
                f"<div class='round-header'>Round {rnd} - Deadline: {deadline}</div>",
                unsafe_allow_html=True,
            )

            round_matches = [m for m in MATCHES if m["round"] == rnd]
            for m in round_matches:
                mid = str(m["id"])
                A = m["A"]
                B = m["B"]
                a_key = f"match_{mid}_score_a"
                b_key = f"match_{mid}_score_b"
                default_a = defaults_stats.get(mid, {}).get("A_maps", 0)
                default_b = defaults_stats.get(mid, {}).get("B_maps", 0)
                st.session_state.setdefault(a_key, default_a)
                st.session_state.setdefault(b_key, default_b)

                row = st.columns([1.7, 0.8, 0.8, 0.8])
                with row[0]:
                    st.markdown(
                        f"<div class='pairing-line'><span class='seed-pill'>A</span>{A} "
                        f"<span class='muted'>vs</span> <span class='seed-pill seed-b'>B</span>{B}</div>",
                        unsafe_allow_html=True,
                    )
                    st.caption(f"Match {mid} - Round {rnd}")
                with row[1]:
                    st.caption(f"{A} maps")
                    a_score = st.number_input(
                        f"{A} maps",
                        min_value=0,
                        max_value=3,
                        step=1,
                        key=a_key,
                        label_visibility="collapsed",
                    )
                with row[2]:
                    st.caption(f"{B} maps")
                    b_score = st.number_input(
                        f"{B} maps",
                        min_value=0,
                        max_value=3,
                        step=1,
                        key=b_key,
                        label_visibility="collapsed",
                    )
                with row[3]:
                    st.caption("Total")
                    st.markdown(f"**{a_score + b_score}/3**")

                total_maps = a_score + b_score
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
            save_results(st.session_state["results"])
            st.success(f"Results saved to `{RESULTS_FILE}`.")

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
with tabs[1]:
    st.markdown(RULES_MD)
