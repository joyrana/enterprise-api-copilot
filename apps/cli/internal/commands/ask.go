// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package commands

import (
	"fmt"
	"strings"

	"github.com/spf13/cobra"
)

// newAskCommand returns the `copilot ask` command.
//
// Sends a natural language query to the AI Copilot and streams the response.
//
// TODO(#70): Connect to POST /api/v1/copilot/ask with SSE streaming.
// TODO(#71): Implement interactive TUI with BubbleTea for streaming output.
// TODO(#72): Add conversation history support (--conversation-id flag).
func newAskCommand() *cobra.Command {
	var conversationID string
	var noStream bool

	cmd := &cobra.Command{
		Use:   "ask [query]",
		Short: "Ask a question or run an API in natural language",
		Long: `Send a natural language query to the Enterprise API Copilot.

The copilot will understand your request, discover the relevant API,
authenticate, execute it, and explain the results.

Examples:
  copilot ask "List all available payment APIs"
  copilot ask "Create a sandbox payment of ₹500 for customer cust_abc123"
  copilot ask "What is the rate limit for the Orders API?"
  copilot ask --conversation-id conv_xyz "Now cancel that payment"`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			query := strings.Join(args, " ")

			// TODO(#70): Replace with real backend call
			fmt.Printf("🤖 Copilot\n\n")
			fmt.Printf("   Query: %s\n\n", query)
			if conversationID != "" {
				fmt.Printf("   Conversation: %s\n\n", conversationID)
			}
			fmt.Println("⚠️  Agent execution is not yet implemented.")
			fmt.Println("   This feature is coming in Phase 2.")
			fmt.Println("\n   Track progress: https://github.com/your-org/enterprise-api-copilot/issues/70")
			return nil
		},
	}

	cmd.Flags().StringVar(&conversationID, "conversation-id", "", "Continue an existing conversation")
	cmd.Flags().BoolVar(&noStream, "no-stream", false, "Wait for full response instead of streaming")

	return cmd
}
