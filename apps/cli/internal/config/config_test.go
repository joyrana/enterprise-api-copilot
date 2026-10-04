package config

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestSaveLoadRoundTripWithOwnerOnlyPermissions(t *testing.T) {
	t.Setenv("COPILOT_BACKEND_URL", "")
	t.Setenv("COPILOT_TOKEN", "")
	path := filepath.Join(t.TempDir(), "copilot", "config.json")
	want := Config{BackendURL: "https://api.example.com", Token: "t0k", Subject: "alice"}
	if err := Save(path, want); err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" {
		info, _ := os.Stat(path)
		if info.Mode().Perm() != 0o600 {
			t.Fatalf("mode = %v, want 0600", info.Mode().Perm())
		}
		dir, _ := os.Stat(filepath.Dir(path))
		if dir.Mode().Perm() != 0o700 {
			t.Fatalf("dir mode = %v, want 0700", dir.Mode().Perm())
		}
	}
	got, err := Load(path)
	if err != nil || got != want {
		t.Fatalf("got %+v, %v", got, err)
	}
}

func TestMissingFileUsesDefaultsAndEnvOverrides(t *testing.T) {
	t.Setenv("COPILOT_BACKEND_URL", "")
	t.Setenv("COPILOT_TOKEN", "")
	cfg, err := Load(filepath.Join(t.TempDir(), "absent.json"))
	if err != nil || cfg.BackendURL != DefaultBackendURL || cfg.Token != "" {
		t.Fatalf("got %+v, %v", cfg, err)
	}
	t.Setenv("COPILOT_BACKEND_URL", "https://other")
	t.Setenv("COPILOT_TOKEN", "envtok")
	cfg, _ = Load(filepath.Join(t.TempDir(), "absent.json"))
	if cfg.BackendURL != "https://other" || cfg.Token != "envtok" {
		t.Fatalf("env overrides not applied: %+v", cfg)
	}
}

func TestWorldReadableConfigIsRefused(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX permissions")
	}
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte(`{"token":"x"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("expected refusal of world-readable config")
	}
}

func TestCorruptConfig(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	_ = os.WriteFile(path, []byte("{"), 0o600)
	if _, err := Load(path); err == nil {
		t.Fatal("expected parse error")
	}
}
