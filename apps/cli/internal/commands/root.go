// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

// Package commands contains all CLI command implementations.
package commands

import (
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

var cfgFile string

// NewRootCommand creates and returns the root cobra command.
// All sub-commands are registered here.
func NewRootCommand() *cobra.Command {
	rootCmd := &cobra.Command{
		Use:   "copilot",
		Short: "Enterprise API Copilot CLI",
		Long: `Enterprise API Copilot — Agentic AI Platform for Enterprise API Discovery,
Testing, Troubleshooting and Automation.

Interact with your enterprise APIs using natural language:

  copilot ask "List all available payment APIs"
  copilot ask "Create a sandbox payment of ₹500"
  copilot api run --method POST --path /v1/payments

Full documentation: https://github.com/your-org/enterprise-api-copilot`,
		SilenceUsage:  true,
		SilenceErrors: true,
	}

	// Persistent flags (available to all sub-commands)
	rootCmd.PersistentFlags().StringVar(&cfgFile, "config", "", "config file (default: $HOME/.config/copilot/config.yaml)")
	rootCmd.PersistentFlags().String("backend-url", "http://localhost:8080", "Backend API URL")
	rootCmd.PersistentFlags().String("output", "pretty", "Output format: pretty, json, yaml")
	rootCmd.PersistentFlags().BoolP("verbose", "v", false, "Enable verbose output")

	_ = viper.BindPFlag("backend-url", rootCmd.PersistentFlags().Lookup("backend-url"))
	_ = viper.BindPFlag("output", rootCmd.PersistentFlags().Lookup("output"))

	// Register sub-commands
	rootCmd.AddCommand(newLoginCommand())
	rootCmd.AddCommand(newAskCommand())
	rootCmd.AddCommand(newApiCommand())
	rootCmd.AddCommand(newDoctorCommand())
	rootCmd.AddCommand(newVersionCommand())

	return rootCmd
}
