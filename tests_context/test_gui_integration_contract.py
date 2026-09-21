import importlib.util
import json
import subprocess
import sys
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "minimal_packet.txt"


def load_adapter():
    spec = importlib.util.spec_from_file_location("clone_context_adapter", CLONE / "context_engine_adapter.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prepare_module(tmp_path):
    module_root = tmp_path / "moduł ze spacją"
    (module_root / "apex_context_engine").mkdir(parents=True)
    (module_root / "apex_context_engine" / "cli.py").write_text("", encoding="utf-8")
    return module_root


def test_gui_a_no_packet_safe():
    result = load_adapter().run_context_engine("", Path("missing"), Path("out"))
    assert result.status == "BLOCKED" and result.reason == "MISSING_OR_NOT_READY_PACKET"


def test_gui_b_valid_packet_returns_json_and_txt(tmp_path, monkeypatch):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    output = tmp_path / "wyniki Łódź"
    json_path, text_path = output / "APEX_CONTEXT_PACKET.json", output / "APEX_CONTEXT_REPORT.txt"
    output.mkdir()
    json_path.write_text("{}", encoding="utf-8")
    text_path.write_text("PASS", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, f"CONTEXT_ENGINE_STATUS=PASS\nJSON={json_path}\nTEXT={text_path}\n", ""))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, output)
    assert result.status == "PASS" and result.json_path == json_path and result.text_path == text_path


def test_gui_c_corrupt_packet_safe():
    result = load_adapter().run_context_engine("BETCLIC_FULL_ODDS_PACKET{\n}", Path("missing"), Path("out"))
    assert result.status == "BLOCKED" and result.reason == "MISSING_OR_NOT_READY_PACKET"


def test_gui_c2_marker_only_packet_never_enables_context():
    corrupt = 'BETCLIC_FULL_ODDS_PACKET{\nMATCH="Home - Away";\nCOMPETITION="X";\n}\nODD{\n}'
    adapter = load_adapter()
    assert not adapter.packet_is_ready(corrupt)
    result = adapter.run_context_engine(corrupt, Path("missing"), Path("out"))
    assert result.status == "BLOCKED" and result.reason == "MISSING_OR_NOT_READY_PACKET"


def test_gui_c3_valid_markers_with_inconsistent_count_never_enable_context():
    corrupt = FIXTURE.read_text(encoding="utf-8").replace("ODDS_COUNT=9;", "ODDS_COUNT=99;")
    assert not load_adapter().packet_is_ready(corrupt)


def test_gui_c4_readiness_cache_is_bounded_and_content_keyed():
    adapter = load_adapter()
    adapter.packet_is_ready.cache_clear()
    valid = FIXTURE.read_text(encoding="utf-8")
    assert adapter.packet_is_ready(valid)
    assert adapter.packet_is_ready(valid)
    invalid = valid.replace("ODDS_COUNT=9;", "ODDS_COUNT=99;")
    assert not adapter.packet_is_ready(invalid)
    info = adapter.packet_is_ready.cache_info()
    assert info.maxsize == 4 and info.hits == 1 and info.misses == 2 and info.currsize == 2


def test_gui_d_double_click_guard_and_exactly_one_button():
    source = (CLONE / "gui.py").read_text(encoding="utf-8")
    assert source.count('text="ZBUDUJ KONTEKST RYNKU"') == 1
    method = source[source.index("def start_context_build"):source.index("def _context_worker")]
    assert "if self.context_is_running:" in method and "return" in method
    compile(source, str(CLONE / "gui.py"), "exec")


def test_gui_e_write_error_controlled(tmp_path):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    bad_output = tmp_path / "occupied"
    bad_output.write_text("file", encoding="utf-8")
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, bad_output)
    assert result.status == "BLOCKED" and result.reason.startswith("CONTEXT_ENGINE_OS_ERROR:")


def test_gui_f_missing_module_does_not_break_extractor(tmp_path):
    result = load_adapter().run_context_engine(FIXTURE.read_text(encoding="utf-8"), tmp_path / "missing", tmp_path / "out")
    assert result.status == "BLOCKED" and result.reason == "CONTEXT_ENGINE_MODULE_NOT_FOUND"
    compile((CLONE / "gui.py").read_text(encoding="utf-8"), str(CLONE / "gui.py"), "exec")


def test_gui_g_engine_error_isolated(tmp_path, monkeypatch):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 2, "CONTEXT_ENGINE_STATUS=BLOCKED\n", "ENGINE_FAILURE"))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, tmp_path / "out")
    assert result.status == "BLOCKED" and result.reason == "ENGINE_FAILURE"


def test_gui_g2_frozen_engine_exception_isolated(tmp_path, monkeypatch):
    adapter = load_adapter()
    monkeypatch.setattr(adapter.sys, "frozen", True, raising=False)
    import apex_context_engine.engine as engine
    monkeypatch.setattr(engine, "build_context", lambda packet: (_ for _ in ()).throw(RuntimeError("boom")))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), CLONE, tmp_path / "out")
    assert result.status == "BLOCKED"
    assert result.reason == "CONTEXT_ENGINE_ERROR:RuntimeError:boom"


def test_gui_g3_process_error_cannot_report_false_pass(tmp_path, monkeypatch):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    output = tmp_path / "outputs"
    output.mkdir()
    json_path, text_path = output / "APEX_CONTEXT_PACKET.json", output / "APEX_CONTEXT_REPORT.txt"
    json_path.write_text("{}", encoding="utf-8")
    text_path.write_text("PASS", encoding="utf-8")
    stdout = f"CONTEXT_ENGINE_STATUS=PASS\nJSON={json_path}\nTEXT={text_path}\n"
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 7, stdout, "crash"))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, output)
    assert result.status == "BLOCKED"
    assert result.reason == "CONTEXT_ENGINE_PROCESS_EXIT:7:crash"


def test_gui_g4_missing_outputs_cannot_report_false_pass(tmp_path, monkeypatch):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    output = tmp_path / "outputs"
    stdout = f"CONTEXT_ENGINE_STATUS=PASS\nJSON={output / 'missing.json'}\nTEXT={output / 'missing.txt'}\n"
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout, ""))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, output)
    assert result.status == "BLOCKED"
    assert result.reason == "CONTEXT_ENGINE_OUTPUT_MISSING:JSON,TEXT"


def test_gui_g5_temporary_cleanup_error_does_not_escape(tmp_path, monkeypatch):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    output = tmp_path / "outputs"
    output.mkdir()
    json_path, text_path = output / "APEX_CONTEXT_PACKET.json", output / "APEX_CONTEXT_REPORT.txt"
    json_path.write_text("{}", encoding="utf-8")
    text_path.write_text("PASS", encoding="utf-8")
    stdout = f"CONTEXT_ENGINE_STATUS=PASS\nJSON={json_path}\nTEXT={text_path}\n"
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout, ""))
    monkeypatch.setattr(adapter.Path, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("locked")))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, output)
    assert result.status == "PASS"


def test_gui_g6_unknown_engine_status_is_blocked(tmp_path, monkeypatch):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, "CONTEXT_ENGINE_STATUS=SUCCESS\n", ""))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, tmp_path / "out")
    assert result.status == "BLOCKED"
    assert result.reason == "CONTEXT_ENGINE_STATUS_INVALID:SUCCESS"


def test_gui_h_timeout_isolated(tmp_path, monkeypatch):
    adapter, module_root = load_adapter(), prepare_module(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("cmd", 1)))
    result = adapter.run_context_engine(FIXTURE.read_text(encoding="utf-8"), module_root, tmp_path / "out")
    assert result.status == "BLOCKED" and result.reason == "CONTEXT_ENGINE_TIMEOUT"


def test_gui_i_restart_import_side_effect_free_and_unicode_paths():
    before = set(CLONE.iterdir())
    first, second = load_adapter(), load_adapter()
    after = set(CLONE.iterdir())
    assert before == after and first.packet_is_ready(FIXTURE.read_text(encoding="utf-8")) and second.packet_is_ready(FIXTURE.read_text(encoding="utf-8"))


def test_gui_j_authoritative_runtime_contract_is_consolidated():
    policy = (CLONE / "AGENTS.md").read_text(encoding="utf-8")
    assert "single authoritative source tree" in policy
    assert "run_context_engine" in (CLONE / "gui.py").read_text(encoding="utf-8")
    assert "SOURCE_RAW_RECORD_IDS" in (CLONE / "core.py").read_text(encoding="utf-8")
    assert "pierwszy strzelec" in (CLONE / "parser.py").read_text(encoding="utf-8")
    assert (CLONE / "replay.py").is_file()
    assert (CLONE / "apex_context_engine" / "cli.py").is_file()
