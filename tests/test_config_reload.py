"""The chat reload command must see edits to the mounted .env file."""

from dotenv import load_dotenv

from ctfblood.config import load_settings


def test_reload_reads_changed_dotenv_over_container_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CTF_BASE_URL=https://example.org\n"
        "CTF_RACE_ID=new-race\n"
        "CTF_VIEWER_KEY=new-key\n"
        "CTF_GROUP_ID=987654\n"
        f"CTF_DB_PATH={tmp_path / 'data.sqlite3'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CTF_BASE_URL", "https://old.example.org")
    monkeypatch.setenv("CTF_RACE_ID", "old-race")
    monkeypatch.setenv("CTF_VIEWER_KEY", "old-key")
    monkeypatch.setenv("CTF_GROUP_ID", "123456")
    monkeypatch.setattr(
        "ctfblood.config.load_dotenv",
        lambda *, override: load_dotenv(env_file, override=override),
    )

    assert load_settings().race_id == "old-race"
    reloaded = load_settings(reload_file=True)
    assert reloaded.race_id == "new-race"
    assert reloaded.viewer_key == "new-key"
    assert reloaded.group_id == 987654
