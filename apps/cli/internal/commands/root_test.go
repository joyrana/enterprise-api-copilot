// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package commands

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRootCommand_HasAllSubcommands(t *testing.T) {
	root := NewRootCommand()

	subcommandNames := make(map[string]bool)
	for _, cmd := range root.Commands() {
		subcommandNames[cmd.Name()] = true
	}

	expectedCommands := []string{"login", "ask", "api", "doctor", "version"}
	for _, name := range expectedCommands {
		assert.True(t, subcommandNames[name], "expected sub-command %q to be registered", name)
	}
}

func TestVersionCommand_ShortFlag(t *testing.T) {
	root := NewRootCommand()
	root.SetArgs([]string{"version", "--short"})
	err := root.Execute()
	require.NoError(t, err)
}

func TestAskCommand_RequiresArgs(t *testing.T) {
	root := NewRootCommand()
	root.SetArgs([]string{"ask"})
	err := root.Execute()
	assert.Error(t, err)
}
