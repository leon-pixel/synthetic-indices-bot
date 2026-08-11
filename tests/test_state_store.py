from sidx.state_store import load_state, save_state


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    payload = {"risk": {"trades_today": 3}, "trade": {"open_pos": None}}
    save_state(path, payload)
    assert load_state(path) == payload


def test_missing_and_corrupt(tmp_path):
    assert load_state(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_state(bad) == {}
