import os
import re
import time
import uuid
import smtplib
from email.mime.text import MIMEText

from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from db import query
from feeder_trace import trace_feeders, trace_feeder_reach, find_parallel_feed_conflicts
from auth_functions import hash_password, is_logged_in, login_required, control_required

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-in-production")

# Same admin-approval email pattern as the Erattayar app. Set SMTP_HOST etc.
# in the environment / .env to actually send mail - if unset, registration
# still creates the 'pending' account, it just can't email the admin a link.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "aswathss466@gmail.com")


def send_mail(to_addr, subject, html_body):
    """Best-effort mail send. Raises if SMTP isn't configured or fails."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP not configured (set SMTP_HOST etc. in .env)")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", ADMIN_EMAIL)

    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())

# In-memory "who's currently on the monitoring screen" tracker - same
# pattern as Erattayar's ACTIVE_VIEWERS. Not persisted; resets on restart,
# and doesn't need to be shared across processes for a single small app.
ACTIVE_VIEWERS = {}
VIEWER_TIMEOUT_SECONDS = 90


def mark_viewer_seen():
    if session.get("username"):
        ACTIVE_VIEWERS[session["username"]] = time.time()


def get_active_viewers():
    cutoff = time.time() - VIEWER_TIMEOUT_SECONDS
    return sorted([u for u, t in ACTIVE_VIEWERS.items() if t >= cutoff])


@app.context_processor
def inject_auth_helpers():
    """Lets templates call is_logged_in() the same way base.html does."""
    return {"is_logged_in": is_logged_in}

# Per-node label nudging without touching the DB (same pattern as Erattayar)
TRANSFORMER_LABEL_OFFSETS = {
    # node_id: (dx, dy)
    # e.g. 7: (10, -5),
}

SWITCH_LABEL_OFFSETS = {
    # node_id: (dx, dy)
    # e.g. 13: (14, -8),
}

# Multiplies every node's x/y coordinate before drawing, spreading the whole
# layout apart so nodes/labels stop overlapping in dense areas. Bump this up
# if it's still congested, or down if there's now too much empty space /
# too much scrolling required. viewBox (image_width/image_height below) is
# scaled by the same factor so the canvas grows to match.
SPACING_SCALE = 1.8


def _attach_display_fields(nodes, edges, node_colors, edge_colors):
    for n in nodes:
        if n["type"] == "switch":
            dx, dy = SWITCH_LABEL_OFFSETS.get(n["id"], (0, 0))
        else:
            dx, dy = TRANSFORMER_LABEL_OFFSETS.get(n["id"], (0, 0))
        n["label_dx"] = (n.get("label_offset_x") or 0) + dx
        n["label_dy"] = (n.get("label_offset_y") or 0) + dy
        n["color"] = node_colors.get(n["id"], "#555555")
        # diagram_svg.html reads n.pos_x/n.pos_y and n.node_type - Thookkupalam's
        # nodes table stores them as x/y/type, so alias here rather than touch the schema.
        # Scaled by SPACING_SCALE to spread nodes apart in congested areas.
        n["pos_x"] = n["x"] * SPACING_SCALE
        n["pos_y"] = n["y"] * SPACING_SCALE
        n["node_type"] = n["type"]

    for e in edges:
        e["color"] = edge_colors.get(e["id"], "#555555")


def _switch_node_state(nodes, edges):
    """Each AB switch is a NODE (type='switch') touched by two edges
    (start->switch, switch->end), both carrying is_switch=1 and their own
    switch_state. A node reads as 'closed' only if every adjacent switch
    edge is closed - if either leg was opened, the switch is open."""
    switch_ids = {n["id"] for n in nodes if n["type"] == "switch"}
    state = {sid: "closed" for sid in switch_ids}
    for e in edges:
        if not e["is_switch"]:
            continue
        for nid in (e["node_a_id"], e["node_b_id"]):
            if nid in switch_ids and e["switch_state"] != "closed":
                state[nid] = "open"
    return state


def _legend_sections(nodes, feeders, node_colors):
    """Groups transformer nodes by which feeder currently energises them
    (based on live trace colors), for the sidebar legend."""
    feeder_by_id = {f["id"]: f for f in feeders}
    grouped = {}
    for n in nodes:
        if n["type"] != "transformer":
            continue
        fid = node_colors.get(n["id"])
        grouped.setdefault(fid, []).append(n)

    sections = []
    for fid, rows in grouped.items():
        feeder = feeder_by_id.get(fid)
        sections.append({
            "feeder_name": feeder["name"] if feeder else "Unassigned / De-energised",
            "color_hex": feeder["color_hex"] if feeder else "#999999",
            "rows": sorted(rows, key=lambda r: (r.get("transformer_no") is None, r.get("transformer_no"), r["name"])),
        })
    # Feeders with power first, unassigned last
    sections.sort(key=lambda s: (s["feeder_name"] == "Unassigned / De-energised", s["feeder_name"]))
    return sections


def _ledger_sections(feeders):
    """Groups the ledger (actual surveyed capacities) by feeder."""
    rows = query("""
        SELECT l.id, l.capacity_kva, l.remarks, l.feeder_id,
               n.name AS location_name
        FROM ledger l
        JOIN nodes n ON n.id = l.transformer_node_id
        ORDER BY l.feeder_id, n.name
    """)
    feeder_by_id = {f["id"]: f for f in feeders}
    grouped = {}
    for r in rows:
        grouped.setdefault(r["feeder_id"], []).append(r)

    sections = []
    for i, (fid, group_rows) in enumerate(grouped.items(), start=1):
        feeder = feeder_by_id.get(fid)
        for j, r in enumerate(group_rows, start=1):
            r["sl_no"] = j
        sections.append({
            "feeder_name": feeder["name"] if feeder else "Unassigned",
            "color_hex": feeder["color_hex"] if feeder else "#999999",
            "rows": group_rows,
        })
    return sections


@app.route("/")
@login_required
def monitor():
    """Read-only live SVG view."""
    mark_viewer_seen()
    nodes = query("SELECT * FROM nodes")
    edges = query("SELECT * FROM edges")
    feeders = query("SELECT * FROM feeders ORDER BY id")
    node_colors, edge_colors = trace_feeders()

    _attach_display_fields(nodes, edges, node_colors, edge_colors)
    nodes_by_id = {n["id"]: n for n in nodes}

    return render_template(
        "monitor.html",
        nodes=nodes,
        edges=edges,
        feeders=feeders,
        node_by_id=nodes_by_id,
        colors={"node_color": node_colors, "edge_color": edge_colors},
        feeder_color_by_id={f["id"]: f["color_hex"] for f in feeders},
        label_offsets={n["id"]: (n["label_dx"], n["label_dy"]) for n in nodes},
        switch_node_state=_switch_node_state(nodes, edges),
        zone_color={},
        legend_sections=_legend_sections(nodes, feeders, node_colors),
        ledger_sections=_ledger_sections(feeders),
        image_width=int(1650 * SPACING_SCALE),
        image_height=int(1400 * SPACING_SCALE),
        mode_label="Monitor",
        active_viewers=get_active_viewers(),
        err=request.args.get("err"),
    )


@app.route("/control")
@control_required
def control():
    """Operator page: same SVG, but switches are clickable to toggle state.
    Requires the 'controller' role - see control_required."""
    mark_viewer_seen()
    nodes = query("SELECT * FROM nodes")
    edges = query("SELECT * FROM edges")
    feeders = query("SELECT * FROM feeders ORDER BY id")
    node_colors, edge_colors = trace_feeders()

    _attach_display_fields(nodes, edges, node_colors, edge_colors)
    nodes_by_id = {n["id"]: n for n in nodes}
    switch_nodes = [n for n in nodes if n["type"] == "switch"]
    switch_state = _switch_node_state(nodes, edges)
    for n in switch_nodes:
        n["state"] = switch_state.get(n["id"], "closed")
    switch_nodes.sort(key=lambda n: n["name"])

    return render_template(
        "control.html",
        nodes=nodes,
        edges=edges,
        feeders=feeders,
        node_by_id=nodes_by_id,
        colors={"node_color": node_colors, "edge_color": edge_colors},
        feeder_color_by_id={f["id"]: f["color_hex"] for f in feeders},
        label_offsets={n["id"]: (n["label_dx"], n["label_dy"]) for n in nodes},
        switch_node_state=switch_state,
        zone_color={},
        switch_nodes=switch_nodes,
        legend_sections=_legend_sections(nodes, feeders, node_colors),
        image_width=int(1650 * SPACING_SCALE),
        image_height=int(1400 * SPACING_SCALE),
        mode_label="Control",
        active_viewers=get_active_viewers(),
        err=request.args.get("err"),
    )


@app.route("/diagram_fragment")
@login_required
def diagram_fragment():
    """Returns just the inside-of-<svg> markup, for the 5s poll refresh."""
    mark_viewer_seen()
    nodes = query("SELECT * FROM nodes")
    edges = query("SELECT * FROM edges")
    feeders = query("SELECT * FROM feeders ORDER BY id")
    node_colors, edge_colors = trace_feeders()
    _attach_display_fields(nodes, edges, node_colors, edge_colors)
    node_by_id = {n["id"]: n for n in nodes}
    feeder_color_by_id = {f["id"]: f["color_hex"] for f in feeders}

    colors = {
        "node_color": node_colors,
        "edge_color": edge_colors,
    }

    return render_template(
        "diagram_svg.html",
        nodes=nodes,
        edges=edges,
        colors=colors,
        feeder_color_by_id=feeder_color_by_id,
        node_by_id=node_by_id,
        label_offsets={n["id"]: (n["label_dx"], n["label_dy"]) for n in nodes},
        switch_node_state=_switch_node_state(nodes, edges),
        zone_color={},
    )


@app.route("/api/toggle_switch/<int:node_id>", methods=["POST"])
@control_required
def toggle_switch(node_id):
    """Toggles an AB switch, identified by its NODE id. Flips switch_state
    on BOTH edges touching that switch node together, so the switch as a
    whole - not just one leg of it - opens/closes.

    Safety interlock: only checked when CLOSING a switch. Opening a
    switch can only ever disconnect things, so it's never blocked - same
    rule as the Erattayar app's /toggle_switch."""
    reason = (request.form.get("reason") or "").strip()
    operator = session.get("display_name")

    switch_nodes = query("SELECT * FROM nodes WHERE id = %s", (node_id,))
    if not switch_nodes or switch_nodes[0]["type"] != "switch":
        return jsonify({"error": "not a switch node"}), 400

    switch_edges = query(
        "SELECT * FROM edges WHERE is_switch = 1 AND (node_a_id = %s OR node_b_id = %s)",
        (node_id, node_id),
    )
    if not switch_edges:
        return jsonify({"error": "switch node has no switch edges"}), 400

    currently_closed = all(e["switch_state"] == "closed" for e in switch_edges)
    new_state = "open" if currently_closed else "closed"

    if new_state == "closed":
        nodes = query("SELECT * FROM nodes")
        edges = query("SELECT * FROM edges")
        feeders = query("SELECT * FROM feeders")

        overrides = {e["id"]: "closed" for e in switch_edges}
        node_feeders = trace_feeder_reach(nodes, edges, state_overrides=overrides)
        conflicts = find_parallel_feed_conflicts(nodes, feeders, node_feeders)
        transformer_conflicts = [c for c in conflicts if c["type"] == "transformer"]

        if transformer_conflicts:
            names = [f"{c['name']} (fed by {' & '.join(c['feeders'])})" for c in transformer_conflicts]
            switch_name = switch_nodes[0]["name"]
            block_msg = (
                f"Blocked: closing {switch_name} would feed "
                f"{'; '.join(names)} from two feeders at once."
            )
            return jsonify({"error": block_msg}), 409

    for e in switch_edges:
        query(
            "UPDATE edges SET switch_state = %s WHERE id = %s",
            (new_state, e["id"]),
            fetch=False,
        )

    query(
        "INSERT INTO switch_log (switch_node_id, new_state, operator, reason) VALUES (%s, %s, %s, %s)",
        (node_id, new_state, operator, reason or None),
        fetch=False,
    )

    return jsonify({"node_id": node_id, "switch_state": new_state})


@app.route("/api/state")
@login_required
def api_state():
    """Poll endpoint for live refresh without full page reload."""
    node_colors, edge_colors = trace_feeders()
    return jsonify({
        "node_colors": node_colors,
        "edge_colors": edge_colors,
    })


@app.route("/ledger")
@login_required
def ledger():
    rows = query("""
        SELECT l.id, n.name AS transformer_name, f.name AS feeder_name,
               l.capacity_kva, l.remarks
        FROM ledger l
        JOIN nodes n ON n.id = l.transformer_node_id
        LEFT JOIN feeders f ON f.id = l.feeder_id
        ORDER BY f.name, n.name
    """)
    return render_template("ledger.html", rows=rows)


# ---------- auth ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    login_error = ""
    if request.method == "POST":
        submitted_user = request.form.get("username", "").strip()
        submitted_pass = request.form.get("password", "")

        rows = query("SELECT * FROM operators WHERE username = %s", (submitted_user,))
        op = rows[0] if rows else None

        if op and hash_password(submitted_pass, op["password_salt"]) == op["password_hash"]:
            if op["status"] != "active":
                login_error = "This account is not active yet - contact an admin."
            else:
                session["logged_in"] = True
                session["username"] = op["username"]
                session["display_name"] = op["display_name"] or op["username"]
                session["role"] = op["role"] or "viewer"

                query(
                    "INSERT INTO login_log (username, display_name, ip_address, login_at) "
                    "VALUES (%s, %s, %s, NOW())",
                    (op["username"], op["display_name"] or op["username"], request.remote_addr),
                    fetch=False,
                )

                default_target = url_for("control") if session["role"] == "controller" else url_for("monitor")
                target = request.args.get("redirect") or default_target
                return redirect(target)
        else:
            login_error = "Invalid username or password."

    return render_template(
        "login.html", error=login_error,
        redirect_to=request.args.get("redirect", ""),
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/create_operator", methods=["GET", "POST"])
def create_operator():
    """Bootstraps the first operator account, or - once at least one
    exists - creates further accounts for anyone already logged in. Same
    open-only-while-empty gate as the Erattayar app's create_operator."""
    count_rows = query("SELECT COUNT(*) AS n FROM operators")
    count = count_rows[0]["n"] if count_rows else 0

    if count > 0 and not is_logged_in():
        return redirect(url_for("login", redirect=request.path))

    create_error = ""
    create_success = ""

    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        new_display = request.form.get("display_name", "").strip()
        new_pass = request.form.get("password", "")
        new_role = request.form.get("role", "viewer")
        if new_role not in ("viewer", "controller"):
            new_role = "viewer"

        if not new_username or not new_pass:
            create_error = "Username and password are required."
        elif len(new_pass) < 6:
            create_error = "Password must be at least 6 characters."
        else:
            existing = query("SELECT id FROM operators WHERE username = %s", (new_username,))
            if existing:
                create_error = "That username already exists."
            else:
                new_salt = str(uuid.uuid4())
                new_hash = hash_password(new_pass, new_salt)
                query(
                    "INSERT INTO operators (username, password_hash, password_salt, display_name, status, role) "
                    "VALUES (%s, %s, %s, %s, 'active', %s)",
                    (new_username, new_hash, new_salt, new_display or None, new_role),
                    fetch=False,
                )
                create_success = f"Operator '{new_username}' created with '{new_role}' access."

    return render_template("create_operator.html", error=create_error, success=create_success)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Public self-service signup. New accounts land as 'pending' and
    can't log in until an admin approves them via the emailed link -
    same flow as the Erattayar app's register/approve pair."""
    register_error = ""
    register_success = ""

    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        new_display = request.form.get("display_name", "").strip()
        new_email = request.form.get("email", "").strip()
        new_pass = request.form.get("password", "")
        confirm_pass = request.form.get("confirm_password", "")

        if not new_username or not new_email or not new_pass:
            register_error = "Username, email, and password are required."
        elif new_pass != confirm_pass:
            register_error = "Passwords don't match."
        elif len(new_pass) < 6:
            register_error = "Password must be at least 6 characters."
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
            register_error = "That doesn't look like a valid email address."
        else:
            existing = query("SELECT id FROM operators WHERE username = %s", (new_username,))
            if existing:
                register_error = "That username already exists."
            else:
                new_salt = str(uuid.uuid4())
                new_hash = hash_password(new_pass, new_salt)
                approval_token = uuid.uuid4().hex + uuid.uuid4().hex

                query(
                    "INSERT INTO operators "
                    "(username, password_hash, password_salt, display_name, email, status, approval_token, role) "
                    "VALUES (%s, %s, %s, %s, %s, 'pending', %s, 'viewer')",
                    (new_username, new_hash, new_salt, new_display or None, new_email, approval_token),
                    fetch=False,
                )
                new_id_rows = query("SELECT id FROM operators WHERE username = %s", (new_username,))
                new_id = new_id_rows[0]["id"] if new_id_rows else None

                approve_url = url_for("approve", id=new_id, token=approval_token, _external=True)
                try:
                    send_mail(
                        ADMIN_EMAIL,
                        f"Thookkupalam Feeder Monitor: approve new operator '{new_username}'",
                        f"""<p>A new operator account was requested on the Thookkupalam 11kV Feeder Network Monitor:</p>
                        <ul>
                            <li><strong>Username:</strong> {new_username}</li>
                            <li><strong>Display name:</strong> {new_display or '(none given)'}</li>
                            <li><strong>Email:</strong> {new_email}</li>
                        </ul>
                        <p><a href="{approve_url}">Click here to approve this account</a></p>
                        <p>If you don't recognize this request, just ignore this email.</p>""",
                    )
                    register_success = (
                        "Account created. It'll be active once the admin approves it by "
                        "email - you'll be able to log in after that."
                    )
                except Exception as mail_err:
                    register_success = (
                        f"Account created, but the approval email could not be sent "
                        f"({mail_err}). Contact the admin directly to get approved."
                    )

    return render_template("register.html", error=register_error, success=register_success)


@app.route("/approve")
def approve():
    op_id = request.args.get("id", type=int)
    token = request.args.get("token", "")
    result_message = ""
    result_ok = False

    if op_id is None or not token:
        result_message = "Invalid approval link."
    else:
        rows = query(
            "SELECT id, username, status, approval_token FROM operators WHERE id = %s",
            (op_id,),
        )
        op = rows[0] if rows else None

        if not op:
            result_message = "No such account."
        elif op["status"] == "active":
            result_message = f"'{op['username']}' is already active."
            result_ok = True
        elif op["approval_token"] != token:
            result_message = "Invalid or expired approval link."
        else:
            query(
                "UPDATE operators SET status = 'active', approval_token = NULL WHERE id = %s",
                (op_id,),
                fetch=False,
            )
            result_message = f"'{op['username']}' has been approved and can now log in."
            result_ok = True

    return render_template("approve.html", message=result_message, ok=result_ok)


@app.route("/login_history")
@login_required
def login_history():
    rows = query(
        "SELECT id, username, display_name, ip_address, login_at "
        "FROM login_log ORDER BY login_at DESC LIMIT 200"
    )
    return render_template("login_history.html", rows=rows, active_viewers=get_active_viewers())


# ---------- switch history (public, matches Erattayar's /history) ----------

@app.route("/history")
def history():
    rows = query("""
        SELECT sl.id, n.name AS switch_label, sl.new_state, sl.operator,
               sl.reason, sl.switched_at
        FROM switch_log sl
        JOIN nodes n ON n.id = sl.switch_node_id
        ORDER BY sl.switched_at DESC
        LIMIT 500
    """)
    return render_template("history.html", rows=rows)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
