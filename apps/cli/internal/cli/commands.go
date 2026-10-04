// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package cli

import (
	"bufio"
	"context"
	"errors"
	"flag"
	"fmt"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/client"
	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/output"
)

func (a *app) apiSearch(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("api search", flag.ContinueOnError)
	limit := fs.Int("limit", 5, "")
	positional, err := parse(fs, args)
	if err != nil {
		return ExitUsage, err
	}
	if len(positional) == 0 {
		return ExitUsage, usagef("api search needs a query")
	}
	if *limit < 1 || *limit > 20 {
		return ExitUsage, usagef("--limit must be between 1 and 20")
	}
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	hits, err := c.SearchAPIs(ctx, strings.Join(positional, " "), *limit)
	if err != nil {
		return ExitError, err
	}
	if a.format == output.JSON {
		return ExitOK, output.WriteJSON(a.io.Out, hits)
	}
	if len(hits) == 0 {
		a.printf("No matching operations.\n")
		return ExitOK, nil
	}
	rows := make([][]string, 0, len(hits))
	for _, h := range hits {
		rows = append(rows, []string{strconv.Itoa(h.Rank), h.OperationID, h.Method + " " + h.Path, strings.Join(h.Scopes, ","), h.Summary})
	}
	return ExitOK, output.Table(a.io.Out, []string{"#", "OPERATION", "ENDPOINT", "SCOPES", "SUMMARY"}, rows)
}

func (a *app) apiDescribe(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("api describe", flag.ContinueOnError)
	positional, err := parse(fs, args)
	if err != nil {
		return ExitUsage, err
	}
	if len(positional) != 1 {
		return ExitUsage, usagef("api describe needs exactly one operation id")
	}
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	op, err := c.DescribeAPI(ctx, positional[0])
	if err != nil {
		return ExitError, err
	}
	if a.format == output.JSON {
		return ExitOK, output.WriteJSON(a.io.Out, op)
	}
	a.printf("%s — %s %s  (%s %s)\n", op.OperationID, op.Method, op.Path, op.APITitle, op.APIVersion)
	if op.Description != "" {
		a.printf("%s\n", op.Description)
	}
	a.printf("\nAuthentication: %s\n", op.Authentication)
	a.printf("Side effect:    %s (invoked via %s)\n", op.SideEffect, op.InvocationSkill)
	if op.RequiresIdempotencyKey {
		a.printf("Idempotency:    Idempotency-Key header required\n")
	}
	if len(op.Parameters) > 0 {
		a.printf("\nParameters:\n")
		for _, p := range op.Parameters {
			req := ""
			if p.Required {
				req = " (required)"
			}
			a.printf("  %-18s %-7s%s %s\n", p.Name, p.Location, req, p.Description)
		}
	}
	if op.RequestBodySchema != nil {
		if required, ok := op.RequestBodySchema["required"].([]any); ok {
			fields := make([]string, 0, len(required))
			for _, f := range required {
				fields = append(fields, fmt.Sprint(f))
			}
			a.printf("\nRequest body required fields: %s\n", strings.Join(fields, ", "))
		}
	}
	if len(op.Responses) > 0 {
		a.printf("\nResponses:\n")
		for code, text := range op.Responses {
			a.printf("  %s  %s\n", code, text)
		}
	}
	return ExitOK, nil
}

func (a *app) ask(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("ask", flag.ContinueOnError)
	env := fs.String("env", "sandbox", "")
	positional, err := parse(fs, args)
	if err != nil {
		return ExitUsage, err
	}
	if len(positional) == 0 {
		return ExitUsage, usagef("ask needs a question or request")
	}
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	run, err := c.CreateRun(ctx, strings.Join(positional, " "), *env)
	if err != nil {
		return ExitError, err
	}
	return a.showRun(run, false)
}

func runExitCode(status string) int {
	switch status {
	case "COMPLETED":
		return ExitOK
	case "AWAITING_APPROVAL", "NEEDS_CLARIFICATION":
		return ExitActionNeeded
	default:
		return ExitRunFailed
	}
}

func (a *app) showRun(run client.Run, withTimeline bool) (int, error) {
	code := runExitCode(run.Status)
	if a.format == output.JSON {
		return code, output.WriteJSON(a.io.Out, run)
	}
	a.printf("[%s] %s  (%s, %d tool calls)\n\n%s\n", run.Status, run.RunID, run.Environment, run.ToolCalls, run.Message)
	if p := run.PendingApproval; p != nil {
		a.printf("\nPending action (%s in %s):\n  %s\n  action hash: %s\n", p.SkillID, p.Environment, p.Summary, p.ActionHash)
		a.printf("An approver can run:  copilot runs approve %s\n", run.RunID)
	}
	if len(run.MissingFields) > 0 {
		a.printf("\nMissing: %s — ask again with these details.\n", strings.Join(run.MissingFields, ", "))
	}
	if len(run.Evidence) > 0 {
		a.printf("\nEvidence: %s\n", strings.Join(run.Evidence, ", "))
	}
	if withTimeline {
		a.printf("\nTimeline:\n")
		for _, e := range run.Timeline {
			a.printf("  - %s %s\n", e.Kind, compact(e.Detail))
		}
	}
	return code, nil
}

func compact(detail map[string]any) string {
	if len(detail) == 0 {
		return ""
	}
	parts := make([]string, 0, len(detail))
	for _, k := range []string{"skill_id", "ok", "error", "intent", "status_code", "approver", "approval_wait_s", "mentioned", "using"} {
		if v, ok := detail[k]; ok && v != nil {
			parts = append(parts, fmt.Sprintf("%s=%v", k, v))
		}
	}
	return strings.Join(parts, " ")
}

func (a *app) runsList(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("runs list", flag.ContinueOnError)
	status := fs.String("status", "", "")
	limit := fs.Int("limit", 20, "")
	if _, err := parse(fs, args); err != nil {
		return ExitUsage, err
	}
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	runs, err := c.ListRuns(ctx, *status, *limit)
	if err != nil {
		return ExitError, err
	}
	if a.format == output.JSON {
		return ExitOK, output.WriteJSON(a.io.Out, runs)
	}
	if len(runs) == 0 {
		a.printf("No runs.\n")
		return ExitOK, nil
	}
	rows := make([][]string, 0, len(runs))
	for _, r := range runs {
		query := r.Query
		if len(query) > 60 {
			query = query[:57] + "..."
		}
		rows = append(rows, []string{r.RunID, r.Status, r.RequestedBy, r.CreatedAt, query})
	}
	return ExitOK, output.Table(a.io.Out, []string{"RUN", "STATUS", "BY", "CREATED", "REQUEST"}, rows)
}

func (a *app) runID(args []string, name string) (string, error) {
	if len(args) != 1 {
		return "", usagef("%s needs exactly one run id", name)
	}
	return args[0], nil
}

func (a *app) runsGet(ctx context.Context, args []string) (int, error) {
	id, err := a.runID(args, "runs get")
	if err != nil {
		return ExitUsage, err
	}
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	run, err := c.GetRun(ctx, id)
	if err != nil {
		return ExitError, err
	}
	_, err = a.showRun(run, true)
	return ExitOK, err
}

func (a *app) runsApprove(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("runs approve", flag.ContinueOnError)
	yes := fs.Bool("yes", false, "")
	positional, err := parse(fs, args)
	if err != nil {
		return ExitUsage, err
	}
	id, err := a.runID(positional, "runs approve")
	if err != nil {
		return ExitUsage, err
	}
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	run, err := c.GetRun(ctx, id)
	if err != nil {
		return ExitError, err
	}
	p := run.PendingApproval
	if run.Status != "AWAITING_APPROVAL" || p == nil {
		return ExitError, fmt.Errorf("run %s is %s, not awaiting approval", id, run.Status)
	}
	a.printf("Requested by %s:\n  %s\n  skill %s, environment %s\n  action hash %s\n", run.RequestedBy, p.Summary, p.SkillID, p.Environment, p.ActionHash)
	if !*yes {
		a.printf("Approve exactly this action? [y/N] ")
		answer, _ := bufio.NewReader(a.io.In).ReadString('\n')
		if a := strings.ToLower(strings.TrimSpace(answer)); a != "y" && a != "yes" {
			return ExitRunFailed, errors.New("not approved")
		}
	}
	// The hash sent is the one displayed: the server rejects it if the action changed.
	done, err := c.Approve(ctx, id, p.ActionHash)
	if err != nil {
		return ExitError, err
	}
	return a.showRun(done, false)
}

func (a *app) runsReject(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("runs reject", flag.ContinueOnError)
	reason := fs.String("reason", "", "")
	positional, err := parse(fs, args)
	if err != nil {
		return ExitUsage, err
	}
	id, err := a.runID(positional, "runs reject")
	if err != nil {
		return ExitUsage, err
	}
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	run, err := c.Reject(ctx, id, *reason)
	if err != nil {
		return ExitError, err
	}
	_, err = a.showRun(run, false)
	return ExitOK, err
}

// evalRun runs the Python evaluation suite from a repository checkout. Arguments are
// fixed (no shell), and the suite name is validated.
func (a *app) evalRun(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("eval run", flag.ContinueOnError)
	suite := fs.String("suite", "smoke", "")
	repo := fs.String("repo", ".", "")
	python := fs.String("python", "python3", "")
	if _, err := parse(fs, args); err != nil {
		return ExitUsage, err
	}
	if *suite != "smoke" && *suite != "full" {
		return ExitUsage, usagef("--suite must be smoke or full")
	}
	root, err := filepath.Abs(*repo)
	if err != nil {
		return ExitError, fmt.Errorf("resolve repo: %w", err)
	}
	cmd := exec.CommandContext(ctx, *python, "-m", "evals", "run", "--suite", *suite) //nolint:gosec // fixed argv, validated suite
	cmd.Dir = root
	cmd.Stdout, cmd.Stderr = a.io.Out, a.io.Err
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return ExitRunFailed, errors.New("evaluation gates failed (see report above)")
		}
		return ExitError, fmt.Errorf("run evaluation: %w", err)
	}
	return ExitOK, nil
}
