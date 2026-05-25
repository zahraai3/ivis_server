# iv_monitor.py
import time
import threading
from hx711 import HX711
import monitor_state as ms
from monitor_state import state, lock
from fluid_data import FLUID_TABLE

# ===== Setup =====
hx = HX711(dout_pin=5, pd_sck_pin=6)
hx.reset()
hx.tare()

# ===== Sync Tools =====
data_lock   = threading.Lock()
setup_done  = threading.Event()

# ===== Global Variables =====
volume_entered    = None
duration_min      = None
drop_factor       = None
density           = None
fluid_name        = None
offset            = None
required          = None
previous_volume   = None
previous_time     = None
previous_reading  = None
threshold         = 0.05
occlusion_timeout = None
last_change_time  = None
safety_factor     = 2
leak_factor       = 2

current_data = {
    "current_volume":    0,
    "current_flow_rate": 0,
    "required_flow_rate":0,
    "deviation":         0,
    "occlusion":         False,
    "leak":              False,
    "remaining_time":    "Calculating..."
}

# ===== Calibration =====
CALIBRATION_FACTOR = 656.0

def read_grams():
    hx.set_scale(CALIBRATION_FACTOR)
    weight = hx.get_weight_mean(10)
    return round(weight, 2)


# ===== Remaining Time =====
def calc_remaining_time(current_volume, current_flow_rate):
    if current_flow_rate <= 0:
        return "N/A"
    ml_per_min   = current_flow_rate / drop_factor
    remaining_min= current_volume / ml_per_min
    hours   = int(remaining_min // 60)
    minutes = int(remaining_min % 60)
    seconds = int((remaining_min * 60) % 60)
    if hours > 0:
        return f"{hours}h {minutes}min {seconds}sec"
    return f"{minutes}min {seconds}sec"

# ===== Setup من التطبيق ===== wait for flask to send the data ===
def setup_from_api():
    global volume_entered, duration_min, drop_factor
    global density, fluid_name, offset, required
    global previous_volume, previous_time
    global previous_reading, occlusion_timeout, last_change_time

    print("Waiting for setup from app...")
    while True : 
        ms.setup_event.wait()  # انتظر إشارة من Flask

        with lock:
            setup = ms.pending_setup

        volume_entered  = setup["capacity_ml"]
        duration_min    = setup["duration_min"]
        drop_factor     = setup["drop_factor"]
        density         = setup["density"]
        fluid_name      = setup["fluid_name"]

        print("Reading initial weight...")
        first_reading = read_grams()
        expected_mass = volume_entered * density
        offset        = first_reading - expected_mass

        with data_lock:
            previous_volume  = volume_entered
            previous_time    = time.time()
            previous_reading = first_reading
            last_change_time = time.time()

        required          = (volume_entered / duration_min) * drop_factor
        occlusion_timeout = (60.0 / required) * safety_factor

        with lock:
            state["setup_done"]         = True
            state["running"]            = True
            state["fluid_name"]         = fluid_name
            state["capacity_ml"]        = volume_entered
            state["required_flow_rate"] = round(required, 2)
            state["percent"]            = 100.0

        print(f"Setup complete — {fluid_name} | {round(required, 2)} drop/min")
        setup_done.set()

# ===== Load Cell Loop =====
def read_load_cell():
    global previous_volume, previous_time, previous_reading, last_change_time

    setup_done.wait()

    while True:
        with data_lock:
            if previous_reading is None:
                time.sleep(0.1)
                continue

        current_reading = read_grams()

        with data_lock:
            prev_reading = previous_reading
            prev_volume  = previous_volume
            prev_time    = previous_time
            req          = required
            occ_timeout  = occlusion_timeout
            lct          = last_change_time
            d_fact       = drop_factor
            dens         = density
            off          = offset

        if abs(current_reading - prev_reading) >= threshold:
            now = time.time()

            with data_lock:
                last_change_time = now

            # حساب الحجم الحالي
            net_mass       = current_reading - off
            current_volume = net_mass / dens

            # حساب التدفق
            delta_volume   = prev_volume - current_volume
            delta_time_sec = now - prev_time

            if delta_time_sec > 0:
                current_flow = (delta_volume / (delta_time_sec / 60.0)) * d_fact
            else:
                current_flow = 0.0

            deviation     = req - current_flow
            leak_detected = (current_flow > req * leak_factor) if req > 0 else False
            remaining     = calc_remaining_time(current_volume, current_flow)

            # حساب النسبة المئوية
            percent = 0.0
            if volume_entered and volume_entered > 0:
                percent = round((current_volume / volume_entered) * 100, 1)
                percent = max(0.0, min(100.0, percent))

            with data_lock:
                current_data["current_volume"]    = round(current_volume, 2)
                current_data["current_flow_rate"] = round(current_flow, 2)
                current_data["required_flow_rate"]= round(req, 2)
                current_data["deviation"]         = round(deviation, 2)
                current_data["remaining_time"]    = remaining
                current_data["leak"]              = leak_detected
                current_data["occlusion"]         = False

            # تحديث الـ state المشترك
            with lock:
                state["current_volume"]    = round(current_volume, 2)
                state["current_flow_rate"] = round(current_flow, 2)
                state["deviation"]         = round(deviation, 2)
                state["remaining_time"]    = remaining
                state["leak"]              = leak_detected
                state["running"]           = True
                state["percent"]           = percent
                state["occlusion"]         = False

                if percent <= 10 and not state["alarm10_ack"]:
                    state["alarm10_active"] = True

                if percent <= 0:
                    state["running"] = False

            with data_lock:
                previous_volume  = current_volume
                previous_time    = now
                previous_reading = current_reading

        else:
            # تحقق من الانسداد
            with data_lock:
                lct    = last_change_time
                occ_to = occlusion_timeout

            if occ_to and (time.time() - lct > occ_to):
                with data_lock:
                    current_data["occlusion"] = True
                with lock:
                    state["occlusion"] = True
                    state["running"]   = False

        time.sleep(0.05)


# ===== Run =====
if __name__ == "__main__":
    thread = threading.Thread(target=read_load_cell)
    thread.daemon = True
    thread.start()

    setup_from_api()

    print("\nSystem running...\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nSystem stopped.")