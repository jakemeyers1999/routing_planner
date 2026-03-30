#!/usr/bin/env python3
"""
ctm_to_routing_planner.py

Reads a CTM account's routing configuration via GET requests and generates
a Drawflow JSON file loadable in the CTM Routing Planner visual designer.

Usage:
    python3 ctm_to_routing_planner.py [--account-id ID] [--output FILE]

The script fetches:
  • Tracking numbers (and their route_to destinations)
  • Voice bots (AI bots with transfer functions → treated as IVR-like nodes)
  • Call queues (with agents, default/after-hours actions)
  • Voice menus (traditional IVR keypresses)
  • Conditional routers (smart routing rules)
  • Receiving numbers (agent/destination phone numbers)
  • Voicemails

It then builds a directed routing graph, assigns hierarchical x/y positions,
and serialises the whole thing as a Drawflow-compatible JSON file.

Load the output in the Routing Planner with the 📂 Load button.
"""

import json
import math
import sys
import argparse
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ── Default credentials (override via CLI args) ────────────────────────────
DEFAULT_ACCOUNT_ID = "11774"
DEFAULT_AUTH_TOKEN = (
    "YTExNzc0ZDYxMDdmN2JjNjc4MzgyZTQ5MjljOTc4OWViOWNjMGI2"
    "OmI4MzgzMGNmZjkzMTZkNjI2ZDYyZWI5Mzk0OTllZWUwZWIwMA=="
)
BASE_URL = "https://api.calltrackingmetrics.com/api/v1"


# ── CTM API Client ─────────────────────────────────────────────────────────
class CTMClient:
    def __init__(self, auth_token: str, base_url: str = BASE_URL):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Basic {auth_token}",
                "Accept": "application/json",
            }
        )
        self.base_url = base_url.rstrip("/")

    def get(self, path: str, params: Optional[Dict] = None) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def paginate_keyed(
        self, path: str, key: str, per_page: int = 200, params: Optional[Dict] = None
    ) -> List[Dict]:
        results: List[Dict] = []
        page = 1
        while True:
            p = dict(params or {})
            p.update({"per_page": per_page, "page": page})
            data = self.get(path, params=p)
            batch = data.get(key, []) if isinstance(data, dict) else []
            if not batch:
                break
            results.extend(batch)
            total_pages = data.get("total_pages", 1) if isinstance(data, dict) else 1
            if page >= total_pages:
                break
            page += 1
        return results


# ── Drawflow HTML builder ──────────────────────────────────────────────────
BADGE_MAP = {
    "TrackingNumber": "Tracking Number",
    "IVR": "IVR Menu",
    "VoiceBot": "Voice Bot",
    "Queue": "Queue",
    "SmartRouter": "Smart Router",
    "ReceivingNumber": "Receiving Number",
    "Voicemail": "Voicemail",
    "NoAnswer": "No Answer Branch",
    "EndAction": "End Action",
}

# Node types that render output-label slot lists
SLOT_TYPES = {"IVR", "VoiceBot", "SmartRouter"}


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _output_slots_html(node_type: str, output_labels: List[str]) -> str:
    if node_type not in SLOT_TYPES:
        return ""
    rows = ""
    for i, lbl in enumerate(output_labels):
        ph = f"Keypress {i + 1}" if node_type == "IVR" else f"Condition {i + 1}"
        rows += (
            f'\n      <div class="output-slot-row">'
            f'\n        <input type="text" class="output-label-txt" value="{_esc(lbl)}"'
            f'\n          oninput="window.updateOutputLabel(this,{i},this.value)"'
            f'\n          placeholder="{ph}">'
            f"\n      </div>"
        )
    add_btn = ""
    if node_type == "IVR":
        add_btn = '\n      <button class="add-path-btn" onclick="event.stopPropagation();window.addIVROutput(this)">+ Add Path</button>'
    return f'\n    <div class="output-slot-list">{rows}{add_btn}\n    </div>'


def _config_summary_html(node_type: str, config: Dict) -> str:
    if not config:
        return "\n    <div class=\"node-config-summary\"></div>"
    parts = []
    if node_type == "TrackingNumber":
        if config.get("phoneNumber"):
            parts.append(config["phoneNumber"])
        if config.get("numberType"):
            parts.append(config["numberType"])
    elif node_type in ("IVR", "VoiceBot"):
        if config.get("greetingText"):
            parts.append(config["greetingText"][:40])
        elif config.get("voice"):
            parts.append(f"Voice: {config['voice'][:20]}")
    elif node_type == "Queue":
        if config.get("ringStrategy"):
            parts.append(config["ringStrategy"].replace("_", " ").title())
        if config.get("agentCount"):
            parts.append(f"{config['agentCount']} agents")
        if config.get("maxWaitSeconds"):
            parts.append(f"{config['maxWaitSeconds']}s max")
        if config.get("callbackEnabled"):
            parts.append("Callback")
    elif node_type == "SmartRouter":
        if config.get("routingStrategy"):
            parts.append(config["routingStrategy"].replace("_", " ").title())
        if config.get("conditionCount"):
            parts.append(f"{config['conditionCount']} rules")
    elif node_type == "NoAnswer":
        if config.get("noAnswerAction"):
            parts.append(f"→ {config['noAnswerAction'].replace('_', ' ').title()}")
        if config.get("missedCallAlert"):
            parts.append("Alert ✓")
    elif node_type == "Voicemail":
        if config.get("notificationEmail"):
            parts.append(f"Email: {config['notificationEmail'][:30]}")
    elif node_type == "ReceivingNumber":
        if config.get("phoneNumber"):
            parts.append(config["phoneNumber"])
        if config.get("contactName"):
            parts.append(config["contactName"][:30])

    if not parts:
        return "\n    <div class=\"node-config-summary\"></div>"
    badge_text = " · ".join(parts)
    return f'\n    <div class="node-config-summary"><span class="config-badge configured">⚙ {_esc(badge_text)}</span></div>'


def build_node_html(
    node_type: str,
    label: str,
    output_labels: List[str],
    notes_value: str = "",
    config: Optional[Dict] = None,
    end_actions: Optional[List] = None,
) -> str:
    badge = BADGE_MAP.get(node_type, node_type)
    config = config or {}
    end_actions = end_actions or []

    slots_html = _output_slots_html(node_type, output_labels)
    summary_html = _config_summary_html(node_type, config)

    # End Actions button
    type_icons = {
        "trigger": "⚡",
        "webhook": "🌐",
        "google_conversion": "📊",
        "email_notification": "📧",
    }
    if end_actions:
        count = len(end_actions)
        icons = "".join(
            dict.fromkeys(type_icons.get(a.get("type", ""), "⚡") for a in end_actions)
        )
        ea_btn = (
            f'\n    <button class="node-footer-btn end-actions-btn has-actions"'
            f"\n      onclick=\"event.stopPropagation();window.showEndActionsPanel(parseInt(this.closest('.drawflow-node').id.replace('node-','')))\">>"
            f"\n      {icons} {count} action{'s' if count != 1 else ''} ✓"
            f"\n    </button>"
        )
    else:
        ea_btn = (
            f'\n    <button class="node-footer-btn end-actions-btn"'
            f"\n      onclick=\"event.stopPropagation();window.showEndActionsPanel(parseInt(this.closest('.drawflow-node').id.replace('node-','')))\">>"
            f"\n      ⚡ End Actions"
            f"\n    </button>"
        )

    return (
        f'<div class="node-inner">\n'
        f'    <div class="node-type-badge">{badge}</div>\n'
        f'    <span class="drawflow-node-label"'
        f' onclick="event.stopPropagation();window.editLabel(this)">{_esc(label)}</span>'
        f"{summary_html}"
        f"{slots_html}\n"
        f'    <textarea class="node-notes-field" placeholder="Notes / scope details..." rows="2" title="Double-click border/corner to reset height"\n'
        f"      oninput=\"window.autosizeNotes(this);window.saveNodeNotes(this)\" ondblclick=\"window.maybeResetNotesSize(this,event)\">{_esc(notes_value)}</textarea>\n"
        f"  </div>\n"
        f'  <div class="node-footer">\n'
        f"    <button class=\"node-footer-btn\""
        f" onclick=\"event.stopPropagation();window.openNodeConfig(parseInt(this.closest('.drawflow-node').id.replace('node-','')))\""
        f">⚙ Configure</button>"
        f"{ea_btn}\n"
        f"    <button class=\"node-footer-btn copy-btn\" title=\"Duplicate this node\""
        f" onclick=\"event.stopPropagation();window.copyNode(parseInt(this.closest('.drawflow-node').id.replace('node-','')))\""
        f">⎘</button>\n"
        f"  </div>"
    )


# ── Routing Graph ──────────────────────────────────────────────────────────
class RoutingGraph:
    """Lightweight directed graph whose nodes map to Drawflow nodes."""

    def __init__(self):
        self.nodes: Dict[str, Dict] = {}  # graph_key → node metadata
        self.edges: List[Tuple[str, int, str]] = []  # (from_key, output_idx, to_key)
        self._next_id = 1

    @staticmethod
    def make_key(ntype: str, rid: str) -> str:
        return f"{ntype}:{rid}"

    def add_node(self, node_type: str, rid: str, **kwargs) -> str:
        k = self.make_key(node_type, rid)
        if k not in self.nodes:
            self.nodes[k] = {"ntype": node_type, "rid": rid, "node_id": self._next_id, **kwargs}
            self._next_id += 1
        return k

    def add_edge(self, from_key: str, output_idx: int, to_key: str):
        # Prevent duplicate edges
        if (from_key, output_idx, to_key) not in self.edges:
            self.edges.append((from_key, output_idx, to_key))


# ── Fetch helpers ──────────────────────────────────────────────────────────

def safe_get(client: CTMClient, path: str, label: str = "") -> Dict:
    try:
        return client.get(path) or {}
    except Exception as e:
        if label:
            print(f"  [warn] {label}: {e}")
        return {}


# ── Graph building ─────────────────────────────────────────────────────────
# CTM route_to type → Routing Planner node type
CTM_TYPE_MAP = {
    "receiving_number": "ReceivingNumber",
    "voice_bot": "VoiceBot",
    "call_queue": "Queue",
    "voice_menu": "IVR",
    "VoiceMenu": "IVR",
    "CallQueue": "Queue",
    "ConditionalRouter": "SmartRouter",
    "VoiceMail": "Voicemail",
    "voicemail": "Voicemail",
    "PhysicalPhoneNumber": "ReceivingNumber",
}


def build_graph(client: CTMClient, account_id: str) -> RoutingGraph:
    g = RoutingGraph()

    # ── 1. Fetch all resource lists ──────────────────────────────────────
    print(f"Fetching tracking numbers...")
    numbers = client.paginate_keyed(
        f"/accounts/{account_id}/numbers", key="numbers", per_page=200, params={"stats": 1}
    )
    print(f"  {len(numbers)} numbers")

    print("Fetching voice bots...")
    voice_bots = client.paginate_keyed(
        f"/accounts/{account_id}/voice_bots", key="voice_bots", per_page=200
    )
    print(f"  {len(voice_bots)} voice bots")

    print("Fetching voice menus...")
    voice_menus = client.paginate_keyed(
        f"/accounts/{account_id}/voice_menus", key="voice_menus", per_page=200
    )
    print(f"  {len(voice_menus)} voice menus")

    print("Fetching call queues...")
    queues = client.paginate_keyed(
        f"/accounts/{account_id}/queues", key="queues", per_page=200
    )
    print(f"  {len(queues)} queues")

    print("Fetching conditional routers...")
    routers = client.paginate_keyed(
        f"/accounts/{account_id}/conditional_routers", key="conditional_routers", per_page=200
    )
    print(f"  {len(routers)} conditional routers")

    print("Fetching receiving numbers...")
    receiving = client.paginate_keyed(
        f"/accounts/{account_id}/receiving_numbers", key="receiving_numbers", per_page=200
    )
    print(f"  {len(receiving)} receiving numbers")

    # ── 2. Build lookup maps ─────────────────────────────────────────────
    vb_by_id = {str(b.get("botid") or b.get("id") or ""): b for b in voice_bots}
    vb_by_full_id = {}
    for b in voice_bots:
        for k in ("id", "botid"):
            v = str(b.get(k) or "")
            if v:
                vb_by_full_id[v] = b

    vm_by_id = {str(m.get("id") or ""): m for m in voice_menus}
    queue_by_id = {str(q.get("id") or ""): q for q in queues}
    router_by_id = {str(r.get("id") or ""): r for r in routers}
    rn_by_id = {str(r.get("id") or ""): r for r in receiving}

    # Detail caches (lazy fetch)
    _vb_detail: Dict[str, Dict] = {}
    _vm_detail: Dict[str, Dict] = {}
    _queue_detail: Dict[str, Dict] = {}
    _router_detail: Dict[str, Dict] = {}

    def get_vb_detail(rid: str) -> Dict:
        if rid not in _vb_detail:
            print(f"    ↳ voice bot detail {rid[:30]}...")
            _vb_detail[rid] = safe_get(
                client, f"/accounts/{account_id}/voice_bots/{rid}", f"voice_bot {rid[:20]}"
            )
        return _vb_detail[rid]

    def get_vm_detail(rid: str) -> Dict:
        if rid not in _vm_detail:
            print(f"    ↳ voice menu detail {rid[:30]}...")
            _vm_detail[rid] = safe_get(
                client, f"/accounts/{account_id}/voice_menus/{rid}", f"voice_menu {rid[:20]}"
            )
        return _vm_detail[rid]

    def get_queue_detail(rid: str) -> Dict:
        if rid not in _queue_detail:
            print(f"    ↳ queue detail {rid[:30]}...")
            _queue_detail[rid] = safe_get(
                client, f"/accounts/{account_id}/queues/{rid}", f"queue {rid[:20]}"
            )
        return _queue_detail[rid]

    def get_router_detail(rid: str) -> Dict:
        if rid not in _router_detail:
            print(f"    ↳ router detail {rid[:30]}...")
            _router_detail[rid] = safe_get(
                client,
                f"/accounts/{account_id}/conditional_routers/{rid}",
                f"router {rid[:20]}",
            )
        return _router_detail[rid]

    # ── 3. Recursive node builder ────────────────────────────────────────

    def add_routing_node(ntype: str, rid: str, fallback_name: str = "") -> str:
        """
        Add ntype:rid to the graph (if new), recursively adding its children.
        Returns the graph key.
        """
        key = g.make_key(ntype, rid)
        if key in g.nodes:
            return key  # already handled — prevent loops

        if ntype == "VoiceBot":
            detail = get_vb_detail(rid)
            name = detail.get("name") or fallback_name or f"Voice Bot {rid[:12]}"
            play_msg = detail.get("play_message") or ""
            voice = detail.get("voice") or ""

            # Collect unique transfer destinations from functions
            functions = detail.get("functions") or []
            output_labels: List[str] = []
            child_routes: List[Tuple[str, str, str]] = []  # (child_ntype, child_rid, label)

            for fn in functions:
                actions = fn.get("actions") or []
                for act in actions:
                    if act.get("type") != "transfer":
                        continue
                    route_id = str(act.get("route_id") or "")
                    route_type = act.get("route_type") or ""
                    description = act.get("description") or act.get("label") or route_type
                    if not route_id:
                        continue
                    child_ntype = CTM_TYPE_MAP.get(route_type, route_type)
                    child_key = g.make_key(child_ntype, route_id)
                    if child_key not in [g.make_key(t, r) for _, t, r, *_ in [(lbl, ct, cr) for lbl, ct, cr in child_routes]]:
                        child_routes.append((description, child_ntype, route_id))
                        output_labels.append(description)

            if not output_labels:
                output_labels = [""]

            g.add_node(
                ntype,
                rid,
                ntype=ntype,
                label=name,
                output_labels=output_labels,
                config={
                    "greetingText": play_msg[:80] if play_msg else "",
                    "voice": voice,
                },
                notes=(
                    f"Voice Bot: {name}\n"
                    + (f"Greeting: {play_msg}\n" if play_msg else "")
                    + (f"Voice: {voice}\n" if voice else "")
                    + f"Transfer paths: {len(child_routes)}"
                ),
            )

            for i, (desc, ct, cr) in enumerate(child_routes):
                child_key = add_routing_node(ct, cr, desc)
                g.add_edge(key, i, child_key)

        elif ntype == "IVR":
            detail = get_vm_detail(rid)
            name = detail.get("name") or fallback_name or f"IVR Menu {rid[:12]}"

            # Items may live under various keys depending on CTM version
            items = (
                detail.get("items")
                or detail.get("key_presses")
                or detail.get("keypresses")
                or detail.get("voice_menu_items")
                or []
            )
            output_labels = []
            child_routes: List[Tuple[str, str, str]] = []

            for item in items:
                digit = str(item.get("digit") or item.get("key") or "")
                item_label = f"Keypress {digit}" if digit else (item.get("name") or "Path")
                next_rt = (
                    item.get("route_to")
                    or item.get("next_route")
                    or item.get("routing")
                    or {}
                )
                output_labels.append(item_label)
                child_routes.append((item_label, next_rt))

            if not output_labels:
                output_labels = [""]

            g.add_node(
                ntype,
                rid,
                ntype=ntype,
                label=name,
                output_labels=output_labels,
                config={"greetingType": detail.get("greeting_type") or "tts"},
                notes=f"Voice Menu ID: {rid}\nKeypresses: {len(items)}",
            )

            for i, (lbl, rt) in enumerate(child_routes):
                if rt:
                    _follow_route_to(key, rt, i)

        elif ntype == "Queue":
            detail = get_queue_detail(rid)
            name = detail.get("name") or queue_by_id.get(rid, {}).get("name") or fallback_name or f"Queue {rid[:12]}"

            routing = str(detail.get("routing") or "").lower()
            total_agents = detail.get("total_agents") or queue_by_id.get(rid, {}).get("total_agents") or ""
            wait_music = detail.get("wait_music") or ""
            schedule = detail.get("schedule")

            default_action_type = detail.get("default_action_type") or ""
            default_action_id = str(detail.get("default_action_id") or "")
            default_action_label = detail.get("default_action_label") or ""

            output_labels = [""]  # primary path out
            g.add_node(
                ntype,
                rid,
                ntype=ntype,
                label=name,
                output_labels=output_labels,
                config={
                    "ringStrategy": routing or "round_robin",
                    "agentCount": str(total_agents),
                    "holdMusic": wait_music[:60] if wait_music else "",
                    "businessHours": "schedule" if schedule else "always",
                },
                notes=(
                    f"Queue: {name}\n"
                    f"Ring Strategy: {routing}\n"
                    f"Agents: {total_agents}\n"
                    + (f"Default Action: {default_action_label} ({default_action_type})\n" if default_action_label else "")
                    + (f"Schedule: {schedule}\n" if schedule else "")
                ),
            )

            # Follow default/overflow action
            if default_action_type and default_action_id:
                child_ntype = CTM_TYPE_MAP.get(default_action_type, default_action_type)
                if child_ntype in CTM_TYPE_MAP.values() or child_ntype in BADGE_MAP:
                    child_key = add_routing_node(child_ntype, default_action_id, default_action_label)
                    g.add_edge(key, 0, child_key)

        elif ntype == "SmartRouter":
            detail = get_router_detail(rid)
            name = detail.get("name") or router_by_id.get(rid, {}).get("name") or fallback_name or f"Router {rid[:12]}"

            conditions = (
                detail.get("conditions")
                or detail.get("rules")
                or detail.get("routers")
                or []
            )
            output_labels = []
            child_routes: List[Tuple[str, Dict]] = []

            for cond in conditions:
                cond_name = cond.get("name") or cond.get("label") or "Condition"
                next_rt = cond.get("route_to") or cond.get("routing") or {}
                output_labels.append(cond_name)
                child_routes.append((cond_name, next_rt))

            fallback = detail.get("fallback") or detail.get("default_route") or {}
            if fallback:
                output_labels.append("Default / Fallback")
                child_routes.append(("Default / Fallback", fallback))

            if not output_labels:
                output_labels = ["Condition 1", "Condition 2", ""]

            strategy = detail.get("routing_type") or detail.get("type") or "unknown"

            g.add_node(
                ntype,
                rid,
                ntype=ntype,
                label=name,
                output_labels=output_labels,
                config={
                    "routingStrategy": strategy,
                    "conditionCount": str(len([c for _, c in child_routes if c])),
                },
                notes=f"Router: {name}\nStrategy: {strategy}\nConditions: {len(conditions)}",
            )

            for i, (lbl, rt) in enumerate(child_routes):
                if rt:
                    _follow_route_to(key, rt, i)

        elif ntype == "ReceivingNumber":
            rn = rn_by_id.get(rid) or {}
            rn_name = rn.get("name") or rn.get("label") or fallback_name or ""
            rn_number = rn.get("number") or rn.get("formatted") or rn.get("display_number") or f"#{rid[:12]}"

            g.add_node(
                ntype,
                rid,
                ntype=ntype,
                label=rn_name or rn_number,
                output_labels=[""],
                config={
                    "phoneNumber": rn_number,
                    "contactName": rn_name,
                },
                notes=f"Number: {rn_number}" + (f"\nName: {rn_name}" if rn_name else ""),
            )

        elif ntype == "Voicemail":
            g.add_node(
                ntype,
                rid,
                ntype=ntype,
                label=fallback_name or f"Voicemail {rid[:12]}",
                output_labels=[""],
                config={},
                notes=f"Voicemail ID: {rid}",
            )

        else:
            # Unknown / unmapped type — render as a generic node
            g.add_node(
                ntype,
                rid,
                ntype="ReceivingNumber",
                label=fallback_name or f"{ntype} {rid[:12]}",
                output_labels=[""],
                config={},
                notes=f"Type: {ntype}\nID: {rid}",
            )

        return key

    def _follow_route_to(from_key: str, route_to: Dict, output_idx: int = 0):
        """Decode a CTM route_to dict, add the target node, and create an edge."""
        if not route_to:
            return
        rtype_ctm = str(route_to.get("type") or "")
        if rtype_ctm in ("", "none", "unknown"):
            return

        ntype = CTM_TYPE_MAP.get(rtype_ctm, rtype_ctm)

        # Extract ID and name from dial (can be list or dict)
        dial = route_to.get("dial")
        rid, name = "", ""
        if isinstance(dial, list) and dial:
            # Multi-target: first target for primary path (each gets own edge below)
            first = dial[0]
            rid = str(first.get("id") or "")
            name = first.get("name") or ""
        elif isinstance(dial, dict):
            rid = str(dial.get("id") or "")
            name = dial.get("name") or ""

        if not rid:
            rid = str(route_to.get("id") or "")
        if not name:
            name = route_to.get("name") or ""
        if not rid:
            return

        multi = route_to.get("multi") or False

        if multi and isinstance(dial, list) and len(dial) > 1:
            # Simultaneous/round-robin multi-target: each target is its own output
            # Update the parent node's output_labels first
            for i, target in enumerate(dial):
                t_rid = str(target.get("id") or "")
                t_name = target.get("name") or target.get("display_number") or target.get("number") or f"{ntype} {i+1}"
                if not t_rid:
                    continue
                child_key = add_routing_node(ntype, t_rid, t_name)
                g.add_edge(from_key, output_idx + i, child_key)
        else:
            child_key = add_routing_node(ntype, rid, name)
            g.add_edge(from_key, output_idx, child_key)

    # ── 4. Seed with tracking numbers ───────────────────────────────────
    print("\nBuilding routing graph...")
    for num in numbers:
        nid = str(num.get("id") or "")
        if not nid:
            continue

        number_str = num.get("number") or num.get("formatted") or ""
        label = num.get("name") or number_str or f"Number {nid[:12]}"
        source = num.get("source") or {}
        source_name = source.get("name") or "" if isinstance(source, dict) else ""
        route_to = num.get("route_to") or {}

        key = g.add_node(
            "TrackingNumber",
            nid,
            ntype="TrackingNumber",
            label=label,
            output_labels=[""],
            config={
                "phoneNumber": number_str,
                "numberType": num.get("type") or "local",
            },
            notes=(
                f"Number: {number_str}\n"
                + (f"Source: {source_name}\n" if source_name else "")
                + f"CTM ID: {nid[:20]}"
            ),
        )

        if route_to:
            _follow_route_to(key, route_to, 0)

    return g


# ── Layout (hierarchical BFS) ──────────────────────────────────────────────
COLUMN_WIDTH = 340
ROW_HEIGHT = 230


def assign_positions(graph: RoutingGraph):
    # Identify root nodes (no incoming edges)
    has_incoming = {e[2] for e in graph.edges}
    roots = [k for k in graph.nodes if k not in has_incoming]

    # BFS depth assignment
    depth: Dict[str, int] = {}
    queue: List[str] = []
    for r in roots:
        depth[r] = 0
        queue.append(r)

    i = 0
    while i < len(queue):
        curr = queue[i]
        i += 1
        for fk, _, tk in graph.edges:
            if fk == curr and tk not in depth:
                depth[tk] = depth[curr] + 1
                queue.append(tk)

    # Assign remaining nodes (islands / cycles)
    max_d = max(depth.values(), default=0) if depth else 0
    for k in graph.nodes:
        if k not in depth:
            max_d += 1
            depth[k] = max_d

    # Count nodes per column, assign row index
    col_count: Dict[int, int] = {}
    col_row: Dict[str, int] = {}
    for k in sorted(graph.nodes.keys(), key=lambda x: depth.get(x, 0)):
        d = depth[k]
        row_idx = col_count.get(d, 0)
        col_count[d] = row_idx + 1
        col_row[k] = row_idx

    # Vertically centre each column
    for k, node in graph.nodes.items():
        d = depth.get(k, 0)
        total = col_count.get(d, 1)
        row_idx = col_row[k]
        node["pos_x"] = 64 + d * COLUMN_WIDTH
        node["pos_y"] = 64 + row_idx * ROW_HEIGHT
        node["depth"] = d


# ── Drawflow JSON serialiser ───────────────────────────────────────────────

def to_drawflow_json(graph: RoutingGraph) -> Dict:
    # Build adjacency helpers
    out_map: Dict[str, Dict[int, str]] = {k: {} for k in graph.nodes}
    in_map: Dict[str, List[Tuple[str, int]]] = {k: [] for k in graph.nodes}

    for fk, oi, tk in graph.edges:
        if fk in graph.nodes and tk in graph.nodes:
            out_map[fk][oi] = tk
            in_map[tk].append((fk, oi))

    drawflow_nodes: Dict[str, Dict] = {}

    for key, node in graph.nodes.items():
        nid = node["node_id"]
        ntype = node.get("ntype", "TrackingNumber")
        label = node.get("label", "")
        output_labels = list(node.get("output_labels", [""]))
        config = node.get("config", {})
        end_actions = node.get("end_actions", [])
        notes = node.get("notes", "")

        # Ensure output_labels is wide enough for all outgoing edges
        max_out_idx = max(out_map[key].keys(), default=-1)
        while len(output_labels) <= max_out_idx:
            output_labels.append("")

        # Outputs
        outputs: Dict[str, Dict] = {}
        for i in range(max(len(output_labels), 1)):
            target_key = out_map[key].get(i)
            if target_key and target_key in graph.nodes:
                target_id = str(graph.nodes[target_key]["node_id"])
                outputs[f"output_{i + 1}"] = {
                    "connections": [{"node": target_id, "output": "input_1"}]
                }
            else:
                outputs[f"output_{i + 1}"] = {"connections": []}

        # Inputs (only TrackingNumber has no inputs)
        inputs: Dict[str, Dict] = {}
        if in_map[key]:
            conns = []
            for fk, oi in in_map[key]:
                if fk in graph.nodes:
                    conns.append(
                        {"node": str(graph.nodes[fk]["node_id"]), "input": f"output_{oi + 1}"}
                    )
            inputs["input_1"] = {"connections": conns}

        html = build_node_html(ntype, label, output_labels, notes, config, end_actions)

        drawflow_nodes[str(nid)] = {
            "id": nid,
            "name": ntype,
            "data": {
                "type": ntype,
                "label": label,
                "depth": node.get("depth", 0),
                "outputLabels": output_labels,
                "config": config,
                "endActions": end_actions,
                "notesValue": notes,
            },
            "class": "",
            "html": html,
            "typenode": False,
            "inputs": inputs,
            "outputs": outputs,
            "pos_x": node.get("pos_x", 64),
            "pos_y": node.get("pos_y", 64),
        }

    return {"drawflow": {"Home": {"data": drawflow_nodes}}}


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a Routing Planner JSON from a CTM account"
    )
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="CTM account ID")
    parser.add_argument(
        "--auth-token",
        default=DEFAULT_AUTH_TOKEN,
        help="CTM Basic Auth token (base64-encoded user:pass)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: ctm_routing_<account>_<timestamp>.json)",
    )
    args = parser.parse_args()

    account_id = args.account_id
    client = CTMClient(auth_token=args.auth_token)

    print(f"\n{'='*60}")
    print(f"  CTM → Routing Planner  |  Account: {account_id}")
    print(f"{'='*60}\n")

    graph = build_graph(client, account_id)

    print(f"\nAssigning layout positions...")
    assign_positions(graph)

    print("Serialising Drawflow JSON...")
    result = to_drawflow_json(graph)

    total_nodes = len(result["drawflow"]["Home"]["data"])
    output_path = (
        args.output
        or f"ctm_routing_{account_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"  ✓  {total_nodes} nodes written to: {output_path}")
    print(f"  Load with the 📂 Load button in the Routing Planner.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
