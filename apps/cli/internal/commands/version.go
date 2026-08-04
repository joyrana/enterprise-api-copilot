// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package commands

import (
	"fmt"
	"runtime"

	"github.com/spf13/cobra"
)

// Build-time variables. Injected via -ldflags during `go build`.
var (
	version   = "0.1.0-SNAPSHOT"
	commit    = "unknown"
	buildDate = "unknown"
)

// newVersionCommand returns the `copilot version` command.
func newVersionCommand() *cobra.Command {
	var short bool

	cmd := &cobra.Command{
		Use:   "version",
		Short: "Print version information",
		Long:  `Print the version, commit hash, build date, and Go runtime information.`,
		Run: func(cmd *cobra.Command, args []string) {
			if short {
				fmt.Println(version)
				return
			}

			fmt.Printf("Enterprise API Copilot CLI\n\n")
			fmt.Printf("  Version:    %s\n", version)
			fmt.Printf("  Commit:     %s\n", commit)
			fmt.Printf("  Build Date: %s\n", buildDate)
			fmt.Printf("  Go Version: %s\n", runtime.Version())
			fmt.Printf("  OS/Arch:    %s/%s\n", runtime.GOOS, runtime.GOARCH)
		},
	}

	cmd.Flags().BoolVar(&short, "short", false, "Print only the version number")

	return cmd
}
