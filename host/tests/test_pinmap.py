"""The hwtest pin map and the grbl cpu_map must describe the same board."""
from pathlib import Path

import pytest

from foamcut import pinmap as pm

ROOT = Path(__file__).resolve().parents[2]
HWTEST = ROOT / "firmware" / "hwtest" / "src" / "gt2560_pins.h"
CPUMAP = ROOT / "firmware" / "grbl5x" / "overlay" / "cpu_map_gt2560.h"

# grbl axis index -> the board slot the hwtest header names it by
AXIS_SLOT = {0: "X", 1: "Y", 2: "Z", 3: "E0"}


@pytest.fixture(scope="module")
def hw():
    return pm.read_hwtest_pins(HWTEST, "GT2560_REV_A")


@pytest.fixture(scope="module")
def grbl():
    return pm.read_defines(CPUMAP)


def test_mega_pin_table_is_a_bijection():
    assert len(pm.PORT_BIT_TO_PIN) == len(pm.MEGA_PIN) == 70


@pytest.mark.parametrize("pin,port,bit", [
    (2, "E", 4), (4, "G", 5), (13, "B", 7), (22, "A", 0), (25, "A", 3),
    (30, "C", 7), (37, "C", 0), (38, "D", 7), (43, "L", 6), (54, "F", 0),
    (69, "K", 7),
])
def test_known_mega_pins(pin, port, bit):
    assert pm.MEGA_PIN[pin] == (port, bit)
    assert pm.pin_of(port, bit) == pin


@pytest.mark.parametrize("axis", sorted(AXIS_SLOT))
@pytest.mark.parametrize("kind,grbl_prefix,hw_prefix", [
    ("step", "STEP", "PIN_STEP_"),
    ("dir", "DIRECTION", "PIN_DIR_"),
    ("enable", "STEPPER_DISABLE", "PIN_EN_"),
])
def test_stepper_pins_agree(hw, grbl, axis, kind, grbl_prefix, hw_prefix):
    got = pm.read_grbl_pin(grbl, f"{grbl_prefix}_PORT_{axis}", f"{grbl_prefix}_BIT_{axis}")
    want = hw[hw_prefix + AXIS_SLOT[axis]]
    assert got == want, (
        f"axis {axis} {kind}: cpu_map says {pm.name_of(got)}, "
        f"gt2560_pins.h says {pm.name_of(want)}"
    )


# One switch per axis, wired 2026-09-18 to the X and Y connector pairs
# (X -> X_MIN, Y -> X_MAX, U -> Y_MIN, V -> Y_MAX); the Z pair and EXP2 stay free.
@pytest.mark.parametrize("axis,hw_key", [(0, "PIN_X_MIN"), (1, "PIN_X_MAX"), (2, "PIN_Y_MIN"), (3, "PIN_Y_MAX")])
def test_min_limits_follow_the_real_wiring(hw, grbl, axis, hw_key):
    got = pm.read_grbl_pin(grbl, f"MIN_LIMIT_PORT_{axis}", f"MIN_LIMIT_BIT_{axis}")
    assert got == hw[hw_key]


@pytest.mark.parametrize("axis,hw_key", [(0, "PIN_Z_MIN"), (1, "PIN_Z_MAX"), (2, "PIN_EXP2_7"), (3, "PIN_EXP2_5")])
def test_max_limits_are_the_spare_inputs(hw, grbl, axis, hw_key):
    got = pm.read_grbl_pin(grbl, f"MAX_LIMIT_PORT_{axis}", f"MAX_LIMIT_BIT_{axis}")
    assert got == hw[hw_key]


def test_all_min_limits_sit_on_port_a(grbl):
    # NC switches are inverted at compile time (INVERT_MIN_LIMIT_PIN_MASK); the
    # pin map keeps all four on PORTA so one port read covers them.
    for axis in range(4):
        assert grbl[f"MIN_LIMIT_PORT_{axis}"] == "A"


def test_hot_wire_pwm_is_the_same_pin_in_both_firmwares(hw, grbl):
    assert pm.read_grbl_pin(grbl, "SPINDLE_PWM_PORT", "SPINDLE_PWM_BIT") == hw["PIN_HEATER_1"]


def test_hot_wire_pwm_pin_is_on_timer3(grbl):
    # grbl owns timer 0 (step pulse reset) and timer 1 (stepper). D3 = OC3C is
    # the only GT2560 power output left on a timer grbl does not use.
    assert grbl["SPINDLE_TCCRA_REGISTER"] == "TCCR3A"
    assert grbl["SPINDLE_OCR_REGISTER"] == "OCR3C"
    assert pm.read_grbl_pin(grbl, "SPINDLE_PWM_PORT", "SPINDLE_PWM_BIT") == 3


def test_coolant_flood_is_the_board_fan(hw, grbl):
    assert pm.read_grbl_pin(grbl, "COOLANT_FLOOD_PORT", "COOLANT_FLOOD_BIT") == hw["PIN_FAN"]


def test_control_pins_are_on_a_pin_change_interrupt_port(grbl):
    # grbl needs PCINT for reset / feed hold / cycle start. On the ATmega2560
    # only PORTB, PORTE0, PORTJ and PORTK have one, and of those only PORTK is
    # free on a GT2560.
    assert grbl["CONTROL_PORT"] == "PORTK"
    assert grbl["CONTROL_PCMSK"] == "PCMSK2"
    bits = {int(grbl[k]) for k in (
        "CONTROL_RESET_BIT", "CONTROL_FEED_HOLD_BIT",
        "CONTROL_CYCLE_START_BIT", "CONTROL_SAFETY_DOOR_BIT")}
    assert len(bits) == 4, "control inputs must not share a bit"
    # A8..A10 (PK0..PK2) carry the thermistor dividers - keep off them.
    assert bits.isdisjoint({0, 1, 2})


def test_no_grbl_output_collides_with_a_stepper_pin(grbl):
    stepper = set()
    for prefix in ("STEP", "DIRECTION", "STEPPER_DISABLE"):
        for axis in range(4):
            stepper.add(pm.read_grbl_pin(grbl, f"{prefix}_PORT_{axis}", f"{prefix}_BIT_{axis}"))
    others = {
        "spindle enable": ("SPINDLE_ENABLE_PORT", "SPINDLE_ENABLE_BIT"),
        "spindle pwm": ("SPINDLE_PWM_PORT", "SPINDLE_PWM_BIT"),
        "spindle direction": ("SPINDLE_DIRECTION_PORT", "SPINDLE_DIRECTION_BIT"),
        "coolant flood": ("COOLANT_FLOOD_PORT", "COOLANT_FLOOD_BIT"),
        "coolant mist": ("COOLANT_MIST_PORT", "COOLANT_MIST_BIT"),
        "probe": ("PROBE_PORT", "PROBE_BIT"),
    }
    for name, (pk, bk) in others.items():
        pin = pm.read_grbl_pin(grbl, pk, bk)
        assert pin not in stepper, f"{name} (D{pin}) collides with a stepper pin"


def test_every_grbl_pin_comment_names_the_right_arduino_pin():
    """Each `#define ..._BIT_n 3   // ... - D25` comment must be truthful."""
    import re
    text = CPUMAP.read_text()
    pattern = re.compile(r"#define\s+(\w*(?:STEP|DIRECTION|DISABLE|LIMIT)\w*_BIT_(\d))\s+(\d+)\s*//[^\n]*?-\s*D(\d+)")
    checked = 0
    for m in pattern.finditer(text):
        name, axis, bit, claimed = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        port_key = name.replace(f"_BIT_{axis}", f"_PORT_{axis}")
        port = pm.read_defines(CPUMAP)[port_key]
        assert pm.pin_of(port, bit) == claimed, f"{name}: comment says D{claimed}"
        checked += 1
    assert checked >= 16, f"only {checked} commented pins found - regex out of date?"
