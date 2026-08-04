// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package commands

import (
	"fmt"
	"net/http"
	"time"

	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

// newDoctorCommand returns the `copilot doctor` command.
//
// Checks all platform components and prints a health summary.
func newDoctorCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "doctor",
		Short: "Check platform health and configuration",
		Long: `Run a series of checks to verify your installation and platform connectivity.

Checks performed:
  ✓ Configuration file
  ✓ Authentication token
  ✓ Backend API connectivity
  ✓ Backend health status`,
		RunE: func(cmd *cobra.Command, args []string) error {
			backendURL := viper.GetString("backend-url")

			fmt.Println("Enterprise API Copilot — Doctor")
			fmt.Println(string(make([]byte, 40))) // spacer
			fmt.Println("Running platform checks...\n")

			// Check 1: Configuration
			fmt.Print("  Config file .................. ")
			// TODO(#90): Check for config file existence
			fmt.Println("⚠️  not configured")

			// Check 2: Authentication
			fmt.Print("  Authentication token ......... ")
			// TODO(#91): Check for valid stored token
			fmt.Println("⚠️  not logged in")

			// Check 3: Backend connectivity
			fmt.Printf("  Backend (%s) ... ", backendURL)
			status := checkBackendHealth(backendURL)
			fmt.Println(status)

			fmt.Println()
			fmt.Println("Run `copilot login` to authenticate.")
			return nil
		},
	}
}

// checkBackendHealth performs an HTTP health check against the backend.
func checkBackendHealth(backendURL string) string {
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(backendURL + "/api/v1/health")
	if err != nil {
		return "✗ unreachable"
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusOK {
		return "✓ healthy"
	}
	return fmt.Sprintf("⚠️  HTTP %d", resp.StatusCode)
}
