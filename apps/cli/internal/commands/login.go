// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package commands

import (
	"fmt"

	"github.com/spf13/cobra"
)

// newLoginCommand returns the `copilot login` command.
//
// Authenticates the user with the API Copilot platform and stores
// credentials securely in the OS keychain / config directory.
//
// TODO(#60): Implement OAuth 2.0 device flow for browser-based login.
// TODO(#61): Implement client credentials flow for CI/CD environments.
// TODO(#62): Store tokens in OS keychain using go-keyring.
func newLoginCommand() *cobra.Command {
	var env string

	cmd := &cobra.Command{
		Use:   "login",
		Short: "Authenticate with the API Copilot platform",
		Long: `Authenticate with the Enterprise API Copilot platform.

This command initiates the login flow based on the target environment.
After successful authentication, credentials are stored securely.

Examples:
  copilot login
  copilot login --env sandbox
  copilot login --env production`,
		RunE: func(cmd *cobra.Command, args []string) error {
			// TODO(#60): Implement login flow
			fmt.Printf("🔐 Login to API Copilot (env: %s)\n\n", env)
			fmt.Println("⚠️  Login is not yet implemented.")
			fmt.Println("   This feature is coming in Phase 2.")
			fmt.Println("\n   Track progress: https://github.com/your-org/enterprise-api-copilot/issues/60")
			return nil
		},
	}

	cmd.Flags().StringVarP(&env, "env", "e", "sandbox", "Target environment (sandbox, staging, production)")

	return cmd
}
