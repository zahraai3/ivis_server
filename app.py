# app.py

from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import monitor_state as ms
from monitor_state import state, lock

app = Flask(__name__)
CORS(app)

# Fluid configuration table
FLUID_TABLE = {
    1: {
        1: {"name": "0.45% NaCl",  "density": 1.0016},
        2: {"name": "0.9% NaCl",   "density": 1.0046},
        3: {"name": "3% NaCl",     "density": 1.0160},
        4: {"name": "5% NaCl",     "density": 1.0280},
        5: {"name": "7.5% NaCl",   "density": 1.0450},
    },
    2: {
        1: {"name": "Lactated Ringer", "density": 1.0050},
        2: {"name": "Acetated Ringer", "density": 1.0050},
        3: {"name": "LR + D5",         "density": 1.0210},
        4: {"name": "AR + D5",         "density": 1.0210},
    },
    3: {
        1: {"name": "D5W",  "density": 1.0180},
        2: {"name": "D10W", "density": 1.0340},
        3: {"name": "D20W", "density": 1.0680},
    },
    4: {
        1: {"name": "D5 1/2NS", "density": 1.0190},
        2: {"name": "D5NS",     "density": 1.0220},
        3: {"name": "D10NS",    "density": 1.0380},
    },
    5: {
        1: {"name": "Mannitol 5%",  "density": 1.0200},
        2: {"name": "Mannitol 10%", "density": 1.0330},
        3: {"name": "Mannitol 15%", "density": 1.0510},
        4: {"name": "Mannitol 20%", "density": 1.0670},
    },
    6: {
        1: {"name": "Plasma-Lyte A",  "density": 1.0050},
        2: {"name": "Plasma-Lyte D5", "density": 1.0200},
        3: {"name": "Hartmann's",     "density": 1.0050},
    },
    7: {
        1: {"name": "Dextran 40 10%", "density": 1.0300},
        2: {"name": "Dextran 70 6%",  "density": 1.0200},
        3: {"name": "HES 6%",         "density": 1.0100},
    },
}


# to verify server is running
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "alive"})

# Get current system status
# Returns live IV monitoring data
@app.route("/status", methods=["GET"])
def get_status():
    with lock:
        return jsonify({
            "need_setup":      not state["setup_done"],
            "reset":           False,
            "percent":         state["percent"],              # remaining fluid %
            "running":         state["running"],              # pump running state
            "flow_rate_ml_hr": state["current_flow_rate"],    # current flow rate
            "obstructed":      state["occlusion"],            # blockage detection
            "alarm10_active":  state["alarm10_active"],       # 10% alarm state
            "alarm10_ack":     state["alarm10_ack"],          # alarm acknowledged
        })


# Setup IV infusion parameters
# Called before starting infusion
@app.route("/setup", methods=["POST"])
def post_setup():
    data = request.get_json()

    # Validate input
    if not data:
        return jsonify({"error": "No data"}), 400

    # Read setup parameters from request
    capacity_ml   = data.get("capacity_ml")
    group_num     = data.get("group")
    item_num      = data.get("item")
    room          = data.get("room", "")
    duration_val  = data.get("duration_value", 1)
    duration_unit = data.get("duration_unit", "h")
    drop_factor   = data.get("drop_factor", 20)

    # Convert hours to minutes if needed
    duration_min = duration_val * 60 if duration_unit == "h" else duration_val

    # Get fluid information from table
    try:
        fluid_info = FLUID_TABLE[group_num][item_num]
        fluid_name = fluid_info["name"]
        density    = fluid_info["density"]
    except KeyError:
        return jsonify({"error": "Invalid fluid"}), 400

    # Save setup data safely (thread-safe)
    with lock:
        ms.pending_setup = {
            "capacity_ml":  capacity_ml,
            "duration_min": duration_min,
            "drop_factor":  drop_factor,
            "density":      density,
            "fluid_name":   fluid_name,
            "room":         room,
        }

        # Reset system state before starting
        state["setup_done"]     = False
        state["running"]        = False
        state["percent"]        = 100.0
        state["alarm10_active"] = False
        state["alarm10_ack"]    = False

    # Notify monitoring thread that setup is ready
    ms.setup_event.set()
    ms.setup_event.clear()

    return jsonify({"status": "ok"})



# Acknowledge 10% alarm
# User confirms alarm and clears it
@app.route("/ack10", methods=["POST"])
def ack_alarm10():
    with lock:
        state["alarm10_ack"]    = True
        state["alarm10_active"] = False
    return jsonify({"status": "ok"})



# Background monitoring thread starter
# Runs IV monitoring logic in parallel
def start_monitor():
    import iv_monitor
    iv_monitor.setup_from_api()
    iv_monitor.read_load_cell()



# Main entry point
# Starts Flask + monitoring thread
if __name__ == "__main__":
    monitor_thread = threading.Thread(
        target=start_monitor, daemon=True
    )
    monitor_thread.start()

    # Run Flask server
    app.run(host="0.0.0.0", port=80, debug=False)