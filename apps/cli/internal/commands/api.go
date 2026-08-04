// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package commands

import (
	"fmt"

	"github.com/spf13/cobra"
)

// newApiCommand returns the `copilot api` command group.
//
// Provides API management utilities: list, search, run, and inspect.
//
// TODO(#80): Implement `copilot api list` — list all indexed APIs.
// TODO(#81): Implement `copilot api run` — execute an API by path/method.
// TODO(#82): Implement `copilot api search` — search API catalog.
// TODO(#83): Implement `copilot api inspect` — show full API spec.
func newApiCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "api",
		Short: "API catalog and execution utilities",
		Long: `Commands for browsing, searching, and executing enterprise APIs.

Examples:
  copilot api list
  copilot api search "payment"
  copilot api run --method POST --path /v1/payments
  copilot api inspect /v1/payments`,
	}

	cmd.AddCommand(newApiListCommand())
	cmd.AddCommand(newApiRunCommand())
	cmd.AddCommand(newApiSearchCommand())

	return cmd
}

func newApiListCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all APIs in the catalog",
		RunE: func(cmd *cobra.Command, args []string) error {
			// TODO(#80): Implement API list
			fmt.Println("⚠️  `copilot api list` is not yet implemented. Coming in Phase 2.")
			return nil
		},
	}
}

func newApiRunCommand() *cobra.Command {
	var method, path, body string

	cmd := &cobra.Command{
		Use:   "run",
		Short: "Execute an API call",
		RunE: func(cmd *cobra.Command, args []string) error {
			// TODO(#81): Implement API run
			fmt.Printf("⚠️  `copilot api run` is not yet implemented.\n")
			fmt.Printf("   Method: %s, Path: %s\n", method, path)
			return nil
		},
	}

	cmd.Flags().StringVar(&method, "method", "GET", "HTTP method (GET, POST, PUT, DELETE)")
	cmd.Flags().StringVar(&path, "path", "", "API path (e.g., /v1/payments)")
	cmd.Flags().StringVar(&body, "body", "", "Request body (JSON)")
	_ = cmd.MarkFlagRequired("path")

	return cmd
}

func newApiSearchCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "search [query]",
		Short: "Search the API catalog",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			// TODO(#82): Implement API search
			fmt.Printf("⚠️  `copilot api search` is not yet implemented.\n")
			fmt.Printf("   Query: %s\n", args[0])
			return nil
		},
	}
}
