from config.settings import load_settings


def test_load_settings_reads_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_HOST=db.local\nDATABASE_PORT=5433\nDATABASE_NAME=wren_demo\n"
        "DATABASE_USER=postgres\nDATABASE_PASSWORD=secret\n",
        encoding="utf-8",
    )
    s = load_settings(env)
    assert s.pg_host == "db.local"
    assert s.pg_port == 5433
    assert s.pg_database == "wren_demo"


def test_password_never_appears_in_repr(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_PASSWORD=sup3rsecret\n", encoding="utf-8")
    s = load_settings(env)
    assert s.pg_password == "sup3rsecret"
    assert "sup3rsecret" not in repr(s)
    assert "sup3rsecret" not in str(s)


def test_defaults_apply_when_env_missing(tmp_path):
    s = load_settings(tmp_path / "does-not-exist")
    assert s.pg_database == "wren_demo"
    assert s.claude_command == "claude"
    assert s.benchmark_privacy_mode == "strict"
    assert s.benchmark_config == "D"


def test_malformed_port_falls_back_to_default(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_PORT=not-a-number\n", encoding="utf-8")
    assert load_settings(env).pg_port == 5432


def test_config_and_memory_dirs_are_per_configuration(tmp_path):
    s = load_settings(tmp_path / "none")
    assert s.project_dir("A") != s.project_dir("D")
    assert s.memory_dir("A") != s.memory_dir("D")
    assert s.project_dir("a") == s.project_dir("A")


def test_secrets_lists_only_non_empty_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_PASSWORD=pw1\nDATABASE_READONLY_PASSWORD=\n", encoding="utf-8")
    assert load_settings(env).secrets() == ["pw1"]
