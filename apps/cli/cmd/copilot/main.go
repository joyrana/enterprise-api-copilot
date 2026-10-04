// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

// Command copilot is the Enterprise API Copilot CLI. It talks only to the platform API.
package main

import (
	"os"

	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/cli"
)

func main() {
	os.Exit(cli.Main())
}
