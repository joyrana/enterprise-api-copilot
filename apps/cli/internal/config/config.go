// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

// Package config loads and stores CLI settings and the access token.
//
// The file lives at $XDG_CONFIG_HOME/copilot/config.json (or ~/.config/...), is written
// atomically with mode 0600 inside a 0700 directory, and is refused on load if other
// users can read it. Environment variables COPILOT_BACKEND_URL and COPILOT_TOKEN
// override the file (useful in CI).
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
)

// DefaultBackendURL is the local platform API.
const DefaultBackendURL = "http://localhost:8080"

// Config is the persisted CLI configuration.
type Config struct {
	BackendURL string `json:"backend_url,omitempty"`
	Token      string `json:"token,omitempty"`
	Subject    string `json:"subject,omitempty"`
}

// DefaultPath returns the config file location.
func DefaultPath() (string, error) {
	base := os.Getenv("XDG_CONFIG_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", fmt.Errorf("locate home directory: %w", err)
		}
		base = filepath.Join(home, ".config")
	}
	return filepath.Join(base, "copilot", "config.json"), nil
}

// Load reads the config file (a missing file is not an error) and applies env overrides.
func Load(path string) (Config, error) {
	var cfg Config
	info, err := os.Stat(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
	case err != nil:
		return cfg, fmt.Errorf("stat config: %w", err)
	default:
		if runtime.GOOS != "windows" && info.Mode().Perm()&0o077 != 0 {
			return cfg, fmt.Errorf("config %s is readable by other users (mode %v); run: chmod 600 %s", path, info.Mode().Perm(), path)
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return cfg, fmt.Errorf("read config: %w", err)
		}
		if err := json.Unmarshal(raw, &cfg); err != nil {
			return cfg, fmt.Errorf("parse config %s: %w", path, err)
		}
	}
	if v := os.Getenv("COPILOT_BACKEND_URL"); v != "" {
		cfg.BackendURL = v
	}
	if v := os.Getenv("COPILOT_TOKEN"); v != "" {
		cfg.Token = v
	}
	if cfg.BackendURL == "" {
		cfg.BackendURL = DefaultBackendURL
	}
	return cfg, nil
}

// Save writes the config atomically with owner-only permissions.
func Save(path string, cfg Config) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("create config dir: %w", err)
	}
	raw, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("encode config: %w", err)
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".config-*.json")
	if err != nil {
		return fmt.Errorf("create temp config: %w", err)
	}
	defer os.Remove(tmp.Name()) //nolint:errcheck // best-effort cleanup after rename
	if err := tmp.Chmod(0o600); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("chmod config: %w", err)
	}
	if _, err := tmp.Write(append(raw, '\n')); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("write config: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("close config: %w", err)
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		return fmt.Errorf("replace config: %w", err)
	}
	return nil
}
