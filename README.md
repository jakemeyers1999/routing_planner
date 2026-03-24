<img width="1155" height="669" alt="Screenshot 2026-03-24 at 7 42 02 AM" src="https://github.com/user-attachments/assets/fc2cbd97-c8ff-4b2e-8175-02d464c0120c" />


# CTM Routing Planner — Visual Call Flow Designer

A web-based drag-and-drop call flow designer built for scoping and documenting CTM (CallTrackingMetrics) routing configurations. Designed for solutions architects to visually map IVRs, queues, smart routers, and post-call automation before implementation.

Powered by [Drawflow](https://github.com/jerosoler/Drawflow).

---

## Features

### Canvas & Navigation
- Drag-and-drop visual flow editor on a large scrollable canvas
- Click any output port to branch and connect a new node
- Grid snap — nodes auto-snap for clean alignment
- **⚡ Auto Arrange** — one-click hierarchical layout using topological sort (columns by depth, rows evenly spaced)
- Keyboard `Delete` / `Backspace` removes selected nodes
- Double-click any node label to rename it inline

### Node Types

| Node | Description |
|---|---|
| **Tracking Number** | Entry point for a call flow; captures number, type, recording/whisper settings |
| **IVR Menu** | Multi-path keypress menu; add unlimited paths with "+ Add Path"; captures greeting type, timeout, retry behavior |
| **Queue** | Call queue with ring strategy, agent list, hold music, announcements, callback, and schedule config |
| **Smart Router** | Conditional routing node (geographic, time-based, tag-based, priority, etc.) |
| **Receiving Number** | Final agent/team destination; captures number, whisper, screening, simultaneous dial |
| **Voicemail** | Voicemail destination with greeting and transcription settings |
| **No Answer Branch** | Handles unanswered calls; configures ring timeout, overflow action, and missed-call alerts |
| **End Action** | Terminal node for post-call automation (no outputs) |

### Per-Node Configuration (⚙ Configure)
Every node has a **Configure** panel that captures CTM-specific scoping fields for each type:
- After saving, a **summary badge** appears on the node card showing key settings at a glance
- All config is serialized to JSON with save/load

### End Actions (⚡)
Each node supports post-call automation via the **End Actions** panel:

| Action Type | Fields |
|---|---|
| **Trigger** | Action type (tag, remove tag, schedule, transfer, SMS), tag/value, condition |
| **Webhook** | URL, authentication (none/basic/bearer), custom Mustache body, notes |
| **Google Conversion** | Conversion label, value, minimum call duration threshold |
| **Email Alert** | Recipients, subject, trigger condition (all/answered/missed/voicemail), call details toggle |

After saving, the End Actions button updates to show the configured action type(s) with a green `✓` indicator (e.g. `🌐 Webhook ✓`, `⚡🌐 Trigger + Webhook ✓`).

### Save / Load
- Export the full flow as a timestamped `.json` file
- Load any previously saved flow from JSON

---

## Getting Started

1. **Clone this repository**
   ```bash
   git clone https://github.com/CTMJSON/routing_planner_branded.git
   cd routing_planner_branded
   ```

2. **Start a local web server** (required — browser security blocks local JS file loading)
   ```bash
   python3 -m http.server 8080
   ```

3. **Open in your browser**
   ```
   http://localhost:8080/routing_planner.html
   ```

---

## Building a Flow

1. Select a node type from the dropdown and click **+ Add Node** to place it on the canvas
2. Click an **output port** (white circle on the right edge of a node) to branch and connect a new downstream node
3. Click **⚙ Configure** on any node to fill in CTM-specific scoping details
4. Click **⚡ End Actions** on any node to add post-call automation
5. Use **⚡ Auto Arrange** to clean up the layout at any time
6. Click **💾 Save** to export the flow as JSON, **📂 Load** to restore one

---

## File Overview

| File | Purpose |
|---|---|
| `routing_planner.html` | Full application — all UI, logic, and styles (single file, no build step) |
| `drawflow.min.js` | Drawflow drag-and-drop engine (bundled) |
| `drawflow.min.css` | Drawflow base styles (bundled) |

---

## Attribution

Powered by [Drawflow](https://github.com/jerosoler/Drawflow) (MIT License).

---

*Created by Jacob Meyers*
