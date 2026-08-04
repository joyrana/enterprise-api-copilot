// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

// Command copilot is the Enterprise API Copilot CLI.
//
// It provides natural language access to enterprise APIs through
// a simple terminal interface. All communication is routed through
// the backend API — no direct agent or external API calls.
//
// Usage:
//
//	copilot [command] [flags]
//
// Available Commands:
//
//	login    Authenticate with the API Copilot platform
//	ask      Ask a question or run an API in natural language
//	api      API management utilities
//	doctor   Check platform health and configuration
//	version  Print the version information
package main

import (
	"os"

	"github.com/your-org/enterprise-api-copilot/cli/internal/commands"
)

func main() {
	if err := commands.NewRootCommand().Execute(); err != nil {
		os.Exit(1)
	}
}
