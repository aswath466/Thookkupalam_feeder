# Thookkupalam Section — 11kV Feeder Monitor / Control app

## Update: brought up to feature parity with Erattayar (interlock + login + logs)

This pass ports four things over from the Erattayar app (`git-feeder-monitor`),
adapted to Thookkupalam's schema (feeder_sources multi-root, switch-as-node,
lowercase open/closed states):

1. **Safety interlock.** `POST /api/toggle_switch/<node_id>` now blocks
   *closing* a switch if doing so would let a transformer be reachable from
   two feeders at once (a real parallel-feed hazard) — same rule Erattayar
   uses, ported as `trace_feeder_reach()` / `find_parallel_feed_conflicts()`
   in `feeder_trace.py`. Opening a switch is never blocked (it can only
   disconnect things). The Control page now shows the real block reason
   instead of a generic error.
2. **Login + roles.** `/login`, `/logout`, `/create_operator`. Two roles:
   `viewer` (read-only Monitor + Ledger + history) and `controller` (also
   gets the Control page and can operate switches). `/`, `/control`,
   `/diagram_fragment`, `/ledger`, `/api/state` all require login now;
   `/control` and the toggle endpoint require the `controller` role.
   `/create_operator` stays open with no login while the `operators` table
   is empty (first-run bootstrap), then requires being logged in.
3. **Switch history.** Every successful toggle is written to `switch_log`
   (switch name, new state, operator, optional reason) and shown at the
   public `/history` page — same as Erattayar's `/history`.
4. **Login history.** `/login_history` (requires login) shows recent logins
   and who's currently on the Monitor/Control screens.

Run `sql/05_auth_tables.sql` after the other four to add the `operators`,
`login_log`, and `switch_log` tables, then visit `/create_operator` once to
create your first account.

**Left out on purpose:** Erattayar's public `/register` + email-approval
flow (`/approve`) isn't included — this build only has the simpler
admin-style `/create_operator`. Happy to add register/approve too if you
want self-serve signups here; it just needs SMTP credentials the way
Erattayar's `.env` has them.


Same architecture as your Erattayar app (Flask + templated SVG single-line
diagram + 5s poll refresh), wired to your exact hand-verified node/edge
data — ids, x/y positions and edge pairs are used exactly as given, never
recomputed or renumbered.

## What I fixed to make it actually run

Comparing `app.py` / `feeder_trace.py` / `diagram_svg.html` against the
`schema.sql` and `index.html` you had, a few things didn't line up yet —
this pass fixes all of them:

1. **`schema.sql` column names didn't match the app code.**
   The app reads `edge.node_a_id` / `edge.node_b_id` and
   `feeder.color_hex`, but the old schema had `from_node_id`/`to_node_id`
   and `color`. `sql/01_schema.sql` now matches what the code actually
   queries.
2. **Switches are modelled as diagram *nodes* here, not edges** (per your
   own note in the original README), but `diagram_svg.html` was still
   drawing the switch glyph at the edge **midpoint** and checking
   `switch_state == "CLOSED"` (uppercase) against a DB that stores
   lowercase `'closed'` — so every switch would have rendered open, in
   the wrong spot. Rewritten to draw each switch at its own node's x/y
   and use the lowercase state, matching `_switch_node_state()` in
   `app.py`.
3. **The ring feeder (id 2, sources at nodes 108 and 388)** — your old
   README flagged this and left `source_node_id` NULL pending a decision.
   I went with "support multiple roots per feeder": `feeder_trace.py` now
   BFS-traces from every row in `feeder_sources` for a feeder
   simultaneously, so feeder 2 is correctly fed from both ends.
4. **`index.html` referenced `legend_sections` / `ledger_sections` /
   `active_viewers`** that `app.py`'s `/` route never actually passed in.
   `app.py` now builds both: `legend_sections` groups transformers by
   which feeder is *currently* live-tracing them; `ledger_sections`
   groups the `ledger` table (still an empty scaffold — see below) by
   feeder. Split into `templates/monitor.html` (extends `base.html`,
   which I added) rather than a standalone `index.html`.
5. Added `templates/control.html` (operator page — click a switch dot on
   the diagram or its row in the table to toggle it) and
   `templates/ledger.html`, neither of which existed yet.

Nothing about your `raw_nodes.txt` / `raw_edges.txt` data itself was
altered — only schema field names, the Jinja templates, and `app.py`.

## 1. Database setup — run in this order

```
mysql -u root -p < sql/01_schema.sql
mysql -u root -p < sql/02_nodes_data.sql
mysql -u root -p < sql/03_edges_data.sql
mysql -u root -p < sql/04_feeders_data.sql
```

- `01_schema.sql` — creates the database and tables (corrected column
  names, see above).
- `02_nodes_data.sql` — inserts all 365 nodes, ids/x/y/type exactly as
  given.
- `03_edges_data.sql` — inserts all 364 edges (ids preserved, including
  the gaps — 117, 189, 207, 326, 367–399 don't exist in your source list
  and are intentionally not filled in), `switch_state` defaulted to
  `'closed'` for every edge.
- `04_feeders_data.sql` — creates the 4 feeders and populates
  `feeder_sources` (feeder 2 gets both node 108 and 388).

All four already ran clean in a syntax check; every edge's node
references resolve, and there are no duplicate node or edge ids.

## 2. Feeders

| id | name | source node(s) |
|----|------|-----------------|
| 2 | Pambadumpara Feeder | 108 **and** 388 (ring — both are now live BFS roots) |
| 3 | Amayar Feeder (Vandanmedu SS) | 244 |
| 4 | Kattapana Feeder | 346 |
| 5 | Town Feeder | 1 |

No feeder id `1` exists in your source-node data, so none was created —
same as before. Colors in `04_feeders_data.sql` are placeholders, edit
freely.

## 3. Switch states — please review before going live

Every switch defaults to `closed`. From the diagram photo, a couple of
points looked like normally-open ties between sections — if so, open
those switch nodes via the Control page once the app is running:
- the dashed "Dead Line" near Serblchanmettu / Soolappara Kanam Estate
- the red "INTERLINK" dashed tie near Asanpady Shapp AB / Border AB

## 4. Before running

```
pip install -r requirements.txt
```

Edit `db.py`: set the real MySQL host/user/password/database via
environment variables (`DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`) —
don't leave real credentials hardcoded in the file for anything beyond
local dev.

```
python app.py
```

Runs on port 5001, so it can run alongside Erattayar on 5000.

- `/` — read-only Monitor view (auto-refreshes every 5s)
- `/control` — Operator view, click any switch dot or table row to
  toggle it
- `/ledger` — capacity ledger table

## 5. Not included (data not available yet)

- `ledger` table is an empty scaffold — no KVA/remarks data was in what
  you sent. Once you have field-survey data, the same pattern as
  Erattayar's `apply_feeder_excel.py` (load from Excel, match by
  transformer name) would work well here too — happy to build that next.
- `transformer_no` / `kva` on `nodes` are NULL for all rows for now.
- Label-offset dictionaries (`TRANSFORMER_LABEL_OFFSETS`,
  `SWITCH_LABEL_OFFSETS` in `app.py`) are empty — same drag-and-drop
  label positioning tool you used for Erattayar would work unchanged
  here once you want to tidy up label overlap on the 62 transformers.
