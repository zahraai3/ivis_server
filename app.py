# app.py

from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import monitor_state as ms
from monitor_state import state, lock
from fluid_data import FLUID_TABLE

app = Flask(__name__)
CORS(app)

# Fluid configuration table


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
            "required_flow_rate": state["required_flow_rate"],  
            "deviation":          state["deviation"],            
            "remaining_time":     state["remaining_time"],
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