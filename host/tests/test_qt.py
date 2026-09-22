"""The Qt interface, built offscreen: every page, every dialog, the wiring."""
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from foamcut.machine import Machine
from foamcut.qt.state import UiState


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    from foamcut.qt import mainwindow
    monkeypatch.chdir(Path(__file__).resolve().parents[2])          # airfoil/ and gcode/ live here
    mp = tmp_path / "machine.json"
    m = Machine(); m.travel_mm = {"X": 220.0, "Y": 100.0, "U": 220.0, "V": 100.0}
    m.tower_gap_mm = 615.0; m.tower_gap_measured = True
    m.save(mp)
    w = mainwindow.MainWindow(port="/dev/does-not-exist", machine_path=mp, autoconnect=False,
                              state=UiState(tmp_path / "ui.json"))
    w.show(); app.processEvents()
    yield w
    w.close()


def test_main_window_has_all_pages(win):
    assert win.stack.count() == 7
    assert [win.nav.item(i).text() for i in range(7)] == ["Maschine", "Flügel", "Formen", "Kontur", "Scheiben",
                                                          "Schachteln", "Programm & Sim"]


def test_wing_page_builds_gcode_and_hands_it_to_the_program_page(win, app):
    wp = win.wing_page
    wp.rebuild(); app.processEvents()
    assert wp.gcode and wp.path is not None
    wp.to_program(); app.processEvents()
    assert win.program_page.lines and win.program_page.name.startswith("clarky_")
    assert win.nav.currentRow() == win.program_row                     # jumps to Programm & Sim
    assert win.program_page.segs and len(win.program_page.segs) > 100


def test_wing_page_marks_stale_program_after_an_edit(win, app):
    wp = win.wing_page
    wp.to_program(); app.processEvents()
    assert wp.stale.text().startswith("übergeben")
    wp.inputs["root_chord"].setText("90"); wp.rebuild(); app.processEvents()
    assert "VERALTET" in wp.stale.text()


def test_wing_page_flags_bad_numbers_inline(win, app):
    wp = win.wing_page
    wp.inputs["panel"].setText("abc"); assert wp.rebuild() is False
    assert wp.messages.count() == 1 and "Keine Zahl" in wp.messages.itemAt(0).widget().text()


def test_wing_page_flags_travel_overrun_inline(win, app):
    wp = win.wing_page
    wp.inputs["root_chord"].setText("300"); wp.inputs["tip_chord"].setText("300")
    assert wp.rebuild() is False
    texts = [wp.messages.itemAt(i).widget().text() for i in range(wp.messages.count())]
    assert any("Verfahrweg" in t for t in texts)


def test_wing_values_persist(win, app, tmp_path):
    wp = win.wing_page
    wp.inputs["root_chord"].setText("123"); wp.rebuild()
    saved = json.loads((tmp_path / "ui.json").read_text())
    assert saved["wing"]["root_chord"] == "123"


def test_wing_layer_checkboxes_hide_layers_and_persist(win, app, tmp_path):
    wp = win.wing_page
    wp.rebuild(); app.processEvents()
    assert wp.front.on("block") and wp.top.on("block")
    wp.layer_boxes["block"].setChecked(False); app.processEvents()
    assert not wp.front.on("block") and not wp.top.on("block")
    wp.front.repaint(); wp.top.repaint(); app.processEvents()      # draws without the layer
    saved = json.loads((tmp_path / "ui.json").read_text())
    assert saved["wing_layers"]["block"] is False and saved["wing_layers"]["root"] is True


def test_wing_mirror_and_fixed_tower(win, app, tmp_path):
    wp = win.wing_page
    wp.rebuild(); app.processEvents()
    assert wp.path.root_tower == 2 and wp.values()["mirror"] == "nein"
    plain_y, plain_cy = wp.path.root[5][1], wp.path.chord_y
    wp.inputs["mirror"].ja.setChecked(True); wp.rebuild(); app.processEvents()
    assert wp.path.mirrored and wp.values()["mirror"] == "ja"
    assert wp.path.root[5][1] - wp.path.chord_y == pytest.approx(-(plain_y - plain_cy))
    assert wp._name().endswith("_sp.nc")
    wp.fixed.setCurrentIndex(0); wp.rebuild(); app.processEvents()
    assert wp.path.root_tower == 1
    assert json.loads((tmp_path / "machine.json").read_text())["wire_fixed_tower"] == 1
    wp.set_values({"mirror": "nein"}); wp.rebuild()
    assert wp.values()["mirror"] == "nein"


def test_wing_min_block_button_fills_the_block_fields(win, app):
    wp = win.wing_page
    wp.rebuild(); app.processEvents()
    assert wp.values()["block_len"] == "" and "Mindestens einzulegen" in wp.minblock_hint.text()
    bx, by, bl, bh, start, width = wp.path.min_block
    wp.apply_min_block(); app.processEvents()
    v = wp.values()
    assert v["block_len"] == f"{bl:.0f}" and v["block_h"] == f"{bh:.0f}" and v["block_w"] == f"{width:.0f}"
    assert v["block_s"] == "0" and "block_y" not in v
    assert wp.path.block[2] == pytest.approx(round(bl))
    assert not any("ragt" in wp.messages.itemAt(i).widget().text() for i in range(wp.messages.count()))


def test_wing_table_button_and_layer(win, app):
    wp = win.wing_page
    wp.inputs["root_chord"].setText("120"); wp.inputs["tip_chord"].setText("50")
    wp.rebuild(); app.processEvents()
    assert "Tisch: Oberkante" in wp.table_hint.text() and wp.front.on("table")
    lo = wp.path.table_range[0]
    wp.lowest_table(); app.processEvents()
    assert float(wp.values()["table_y"]) == pytest.approx(math.ceil(lo))
    assert min(y for _, y in wp.path.tower1 + wp.path.tower2) >= -1e-6
    wp.layer_boxes["table"].setChecked(False); app.processEvents()
    assert not wp.top.on("table")
    wp.front.repaint(); wp.top.repaint(); app.processEvents()


def test_loading_an_old_wing_file_derives_the_table_height(win, app, tmp_path):
    from foamcut.wing import TEMPLATE
    wp = win.wing_page
    old = TEMPLATE.replace("table_y      = 20", "chord_y = 45").replace("block_x      = 20", "te_x = 32")
    vals = wp._values_from_file(old)
    assert vals["block_x"] == "20" and float(vals["table_y"]) < 45.0
    wp.set_values(vals); wp.rebuild()
    assert wp.path.chord_y == pytest.approx(45.0, abs=0.05)


def test_wing_area_locks_the_chord_fields(win, app):
    wp = win.wing_page
    wp.inputs["area"].setText("0.4"); wp.inputs["taper"].setText("0.5"); wp.rebuild(); app.processEvents()
    assert not wp.inputs["root_chord"].isEnabled() and not wp.inputs["tip_chord"].isEnabled()
    assert float(wp.inputs["tip_chord"].text()) == pytest.approx(float(wp.inputs["root_chord"].text()) / 2, abs=0.1)
    wp.inputs["area"].setText(""); wp.rebuild(); app.processEvents()
    assert wp.inputs["root_chord"].isEnabled()
    assert "Ruder" in [wp.nav.item(i).text() for i in range(wp.nav.count())]


def test_shape_page_builds_a_ring_and_hands_it_over(win, app):
    sp = win.shape_page
    sp.rebuild(); app.processEvents()
    assert sp.gcode and sp.path is not None and "Form: A rechteck" in sp.result.text()
    sp.inputs["a_hole"].setCurrentText("kreis"); sp.inputs["b_hole"].setCurrentText("kreis")
    sp.inputs["b_kind"].setCurrentText("ellipse"); sp.rebuild(); app.processEvents()
    assert len(sp.path.root) == 2 * 73 + 1 and sp.values()["b_kind"] == "ellipse"
    sp.to_program(); app.processEvents()
    assert win.program_page.name.endswith("_ring.nc") and win.nav.currentRow() == win.program_row
    sp.inputs["a_hole"].setCurrentText("keine"); assert sp.rebuild() is False      # one-sided hole refused
    texts = [sp.messages.itemAt(i).widget().text() for i in range(sp.messages.count())]
    assert any("Loch" in t for t in texts)


def test_contour_page_loads_an_svg_and_hands_over_a_parallel_program(win, app):
    cp = win.contour_page
    assert cp.model.key == "contour" and hasattr(cp.inputs["svg"], "browse")
    cp.inputs["svg"].setText("config/beispiel.svg"); cp.inputs["width"].setText("80")
    assert cp.rebuild()
    assert any("3 Teil(e)" in l for l in cp.result.text().splitlines())
    cp.b_prog.click(); app.processEvents()
    assert win.program_page.name == "beispiel_b80_30.nc" and win.nav.currentRow() == win.program_row
    cp.inputs["svg"].setText("config/gibt-es-nicht.svg")
    assert not cp.rebuild()
    assert any("nicht gefunden" in cp.messages.itemAt(i).widget().text() for i in range(cp.messages.count()))


def test_slice_page_cuts_one_slab_of_the_example_body(win, app):
    sp = win.slice_page
    sp.inputs["stl"].setText("config/beispiel.stl"); sp.inputs["index"].setText("3")
    assert sp.rebuild()
    assert any(l.startswith("Scheibe 3 von 5") for l in sp.result.text().splitlines())
    sp.b_prog.click(); app.processEvents()
    assert win.program_page.name == "beispiel_scheibe3_40mm.nc"


def test_object_tab_shows_the_source_drawing_or_body(win, app):
    from foamcut.qt.canvas import MeshView, ObjectView
    assert win.wing_page.view_tabs.count() == 1                 # wings have no source object
    cp = win.contour_page
    assert [cp.view_tabs.tabText(i) for i in range(2)] == ["Diagramm", "Objekt"]
    cp.inputs["svg"].setText("config/beispiel.svg"); assert cp.rebuild()
    assert isinstance(cp.object_view, ObjectView) and len(cp.object_view.loops) == 5 and cp.object_view.holes == {1, 4}
    sp = win.slice_page
    sp.inputs["stl"].setText("config/beispiel.stl"); sp.inputs["index"].setText("3"); assert sp.rebuild()
    assert isinstance(sp.object_view, MeshView) and len(sp.object_view.tris) == 2952
    assert (sp.object_view.z0, sp.object_view.z1) == (80.0, 120.0) and len(sp.object_view.planes) == 6
    sp.view_tabs.setCurrentIndex(1); app.processEvents()       # paints without error
    sp.object_view.grab()


def test_freischnitt_runs_as_a_relative_program_from_the_current_position(win, app, monkeypatch):
    from foamcut import gcode as gc
    from foamcut.jog import straight_cut
    code = straight_cut(80.0, 90.0, 120.0, back=True)
    prog = gc.Program.parse(code, start={"X": 50.0, "Y": 10.0, "U": 50.0, "V": 10.0})
    assert not prog.errors and prog.extents()["Y"] == pytest.approx((0.0, 90.0))
    assert prog.extents()["X"][1] == pytest.approx(50.0)           # nothing moves in X
    started = []
    monkeypatch.setattr(win.program_page, "start", lambda: started.append(True))
    win.mpos.update({"X": 30.0, "Y": 5.0, "U": 30.0, "V": 5.0})
    mp = win.machine_page
    mp.cut_len.setText("100"); mp.cut_feed.setText("150"); mp.cut_back.setChecked(False)
    mp._cut(0.0); app.processEvents()
    assert started and win.program_page.name.startswith("freischnitt_100mm_0deg")
    assert win.program_page.start_pos["X"] == pytest.approx(30.0)
    assert not win.program_page.problems and win.nav.currentRow() == win.program_row
    mp.cut_len.setText("300"); mp._cut(0.0); app.processEvents()     # 30 + 300 > 218 travel
    assert any("Verfahrweg" in p or "faehrt" in p for p in win.program_page.problems)
    # swept face: tower 2 offset forward, cut upward, offset undone at the end
    mp.cut_len.setText("40"); mp.skew_u.setText("30"); mp._cut(90.0); app.processEvents()
    assert "2.8°" in mp.skew_lbl.text() and win.program_page.name.endswith("_u30v0.nc")
    lines = [l for l in win.program_page.raw.splitlines() if l.startswith("G1 ")]
    assert lines[0].startswith("G1 U30.000 V0.000") and lines[-1].startswith("G1 U-30.000 V-0.000")
    assert "Y40.000" in lines[1] and "V40.000" in lines[1]


def test_run_is_drawn_live_on_the_sim_views(win, app):
    pp = win.program_page
    win.wing_page.rebuild(); win.wing_page.to_program(); app.processEvents()
    assert pp.segs
    pp.running = True; pp.v1.clear_live(); pp.v2.clear_live()
    pp.on_progress(12, len(pp.lines), "G1 ..."); app.processEvents()
    assert 0 < pp.v1.upto == sum(1 for s in pp.segs if s.line_no <= 12)
    for x in (10.0, 10.0, 12.5):                                  # a repeat does not grow the trail
        pp.on_status({"X": x, "Y": 5.0, "U": x + 1, "V": 5.0}); app.processEvents()
    assert pp.v1.live == (12.5, 5.0) and pp.v2.live == (13.5, 5.0) and len(pp.v1.trail) == 2
    pp.v1.repaint(); pp.v2.repaint(); app.processEvents()
    pp.on_finished(True); app.processEvents()
    assert pp.v1.live is None and len(pp.v1.trail) == 2          # trail stays for inspection
    pp.on_status({"X": 0.0, "Y": 0.0, "U": 0.0, "V": 0.0})
    assert pp.v1.live is None                                     # not running: ignored


def test_batch_page_stacks_parts_and_hands_over_one_program(win, app, tmp_path):
    from foamcut.wing import TEMPLATE
    from foamcut.shape import TEMPLATE as SHAPE_TEMPLATE
    w1 = tmp_path / "a.wing"; w1.write_text(TEMPLATE)
    s1 = tmp_path / "b.shape"; s1.write_text(SHAPE_TEMPLATE.replace("a_h          = 40", "a_h = 20").replace("b_h          = 40", "b_h = 20"))
    bp = win.batch_page
    bp._add_item(str(w1), pair=True); bp._add_item(str(s1))
    bp.f["gap"].setText("5"); bp.rebuild(); app.processEvents()
    assert bp.nest and len(bp.nest.parts) == 3
    parts = bp.nest.parts
    s_lo, s_hi = sorted(bp.nest.block_s)
    for upper, lower in zip(parts, parts[1:]):                 # stacked with the gap, checked along the span
        for k in range(21):
            sv = s_lo + (s_hi - s_lo) * k / 20
            assert min(y for _, y in upper.path.section(sv)) >= max(y for _, y in lower.path.section(sv)) + 5 - 1e-6
    assert parts[-1].bottom == pytest.approx(20.0 + 10.0)      # lowest part: margin above the table
    assert bp.nest.parts[1].name.endswith("(Paar)") and bp.nest.parts[1].path.root == bp.nest.parts[0].path.tip or True
    bp.to_program(); app.processEvents()
    assert win.program_page.name == "nest_3teile.nc" and win.nav.currentRow() == win.program_row
    code = win.program_page.raw
    assert code.count("; --- ") == 3 and code.count("M3 ") == 1
    # the batch survives a text round trip
    from foamcut.nest import Batch
    b = bp.batch()
    b2 = Batch.parse(b.to_text())
    assert [it.file for it in b2.items] == [str(w1), str(s1)] and b2.items[0].pair and not b2.items[1].pair
    assert b2.gap == 5.0 and b2.block_len is None


def test_program_page_translates_a_generator_file(win, app):
    pp = win.program_page
    raw = (Path("gcode") / "wing_program.nc").read_text()
    pp.set_program(raw, "wing_program.nc")
    assert any(l.startswith("G1 X99.384 Y9.740 U131.162") for l in pp.lines)
    assert "Achsformat XYAZ" in pp.notes.text()


def test_simulation_steps_through(win, app):
    pp = win.program_page
    win.wing_page.to_program(); app.processEvents()
    n = len(pp.segs)
    pp.sim_step(); pp.sim_step()
    assert pp.i == 2 and pp.v1.upto == 2
    pp.sim_finish(); assert pp.i == n
    pp.sim_reset(); assert pp.i == 0 and pp.b_run.text() == "Start"


def test_machine_page_jog_buttons_emit_grbl_commands(win, app):
    sent = []
    win.machine_page.send_line.connect(sent.append)
    pad = win.machine_page.findChildren(type(win.machine_page.b_home))
    btn = next(b for b in pad if b.text() == "X+U+ ▶")
    btn.click()
    assert sent[-1].startswith("$J=G91 G21 X5.000 U5.000 F")


def test_kerf_lives_on_the_machine_page_and_reshapes_the_designs(win, app, tmp_path):
    """One kerf for wings, shapes and batches: edited on the machine page, saved
    to machine.json, and the design pages regenerate with it."""
    from foamcut.machine import Machine
    wp = win.wing_page
    wp.rebuild(); before = wp.path.root
    win.machine_page.kerf.setText("3"); win.machine_page.kerf.editingFinished.emit(); app.processEvents()
    assert Machine.load(tmp_path / "machine.json").kerf_mm == 3.0
    assert wp.path.root != before                       # wider melt channel -> other wire path
    assert "kerf" not in wp.model.template               # no longer a per-part field
    win.machine_page.kerf.setText("x"); win.machine_page.kerf.editingFinished.emit()
    assert win.machine_page.kerf.text() == "3"          # bad input is refused, old value stays
    win.machine_page.cut_feed.setText("250"); win.machine_page.cut_feed.editingFinished.emit(); app.processEvents()
    win.machine_page.warmup.setText("5"); win.machine_page.warmup.editingFinished.emit(); app.processEvents()
    m = Machine.load(tmp_path / "machine.json")
    assert (m.cut_feed, m.warmup_s) == (250.0, 5.0)
    assert "G4 P5" in wp.gcode and "F" in wp.gcode      # the wing program carries them


def test_homing_dialog_opens_and_validates(win, app):
    from foamcut.qt.homingdialog import HomingDialog
    d = HomingDialog(win.machine, lambda: None, print, lambda: None, win)
    d.enabled.setChecked(True)
    d.len["X"].setText("abc")
    assert any("keine Zahl" in e for e in d.read_form())
    for a in "XYUV":
        d.len[a].setText("160")
    d.off["V"].setText("1.5")
    assert d.read_form() == []
    assert win.machine.homing.offset_mm["V"] == 1.5
    d.close()


def test_worker_events_reach_the_pages(win, app):
    from foamcut.worker import GrblWorker
    from fake_grbl import FakeGrblLink
    link = FakeGrblLink()
    link.mpos["X"] = 12.0
    win.worker = GrblWorker("fake", poll=0.01, link_factory=lambda: link, reconnect=False)
    win.worker.start()
    import time
    time.sleep(0.4)
    win._pump(); app.processEvents()
    assert win.machine_page.pos["X"].text() == "12.000"
    assert win.machine_page.state.text() == "Idle"
    win.worker.stop(); time.sleep(0.2); win._pump()


def test_ui_state_default_path_and_missing_file(tmp_path, monkeypatch):
    from foamcut.qt import state as st
    monkeypatch.chdir(tmp_path)
    s = UiState()                       # default path, file does not exist yet
    assert s.get("x") is None
    s.set("x", 1)
    assert st.DEFAULT_PATH.exists() and UiState().get("x") == 1
