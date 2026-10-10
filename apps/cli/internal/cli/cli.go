// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

// Package cli implements the copilot command line (ADR-0009: standard library only).
package cli

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/client"
	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/config"
	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/output"
)

// Exit codes. Scripts can distinguish "needs a human" from failures.
const (
	ExitOK           = 0
	ExitError        = 1
	ExitUsage        = 2
	ExitActionNeeded = 3 // awaiting approval or clarification
	ExitRunFailed    = 4 // run rejected or failed
)

// Build information, injected with -ldflags -X.
var (
	version   = "0.3.0-dev"
	commit    = "unknown"
	buildDate = "unknown"
)

// IO carries the process streams so commands are testable.
type IO struct {
	In  io.Reader
	Out io.Writer
	Err io.Writer
}

type app struct {
	io         IO
	configPath string
	backendURL string
	format     output.Format
	timeout    time.Duration
}

type usageError struct{ msg string }

func (e usageError) Error() string { return e.msg }

func usagef(format string, args ...any) error { return usageError{fmt.Sprintf(format, args...)} }

const usage = `copilot — Enterprise API Copilot CLI

Usage:
  copilot [global flags] <command> [args]

Commands:
  version [--short]                  Print version information
  doctor                             Check configuration, backend and login
  login --user NAME | --token-stdin  Authenticate (dev users in local mode, or a token on stdin)
  logout                             Forget the stored token
  ask QUERY... [--env sandbox]       Ask the copilot to do something
  api search QUERY... [--limit N]    Search the API catalog
  api describe OPERATION_ID          Show an operation's auth, scopes and schema
  runs list [--status S] [--limit N] List runs in your tenant
  runs get RUN_ID                    Show a run and its timeline
  runs approve RUN_ID [--yes]        Approve the exact pending action
  runs reject RUN_ID [--reason R]    Reject the pending action
  approvals                          List runs awaiting approval
  skills list                        List registered skills
  eval run [--suite smoke|full] [--repo DIR]  Run the offline evaluation (needs Python)

Global flags:
  --backend-url URL   Platform API (default from config, COPILOT_BACKEND_URL or http://localhost:8080)
  --output FORMAT     pretty | json (default pretty)
  --config PATH       Config file (default ~/.config/copilot/config.json)
  --timeout DURATION  Request timeout (default 2m)

Exit codes: 0 ok, 1 error, 2 usage, 3 needs approval/clarification, 4 run rejected/failed.
`

// Run executes the CLI and returns the process exit code.
func Run(args []string, streams IO) int {
	a := &app{io: streams}
	global := flag.NewFlagSet("copilot", flag.ContinueOnError)
	global.SetOutput(io.Discard)
	global.StringVar(&a.backendURL, "backend-url", "", "")
	formatFlag := global.String("output", "pretty", "")
	global.StringVar(&a.configPath, "config", "", "")
	global.DurationVar(&a.timeout, "timeout", 2*time.Minute, "")
	help := global.Bool("help", false, "")
	if err := global.Parse(args); err != nil {
		return a.fail(usagef("%v", err))
	}
	if *help || global.NArg() == 0 {
		_, _ = fmt.Fprint(streams.Out, usage)
		return ExitOK
	}
	format, err := output.ParseFormat(*formatFlag)
	if err != nil {
		return a.fail(usageError{err.Error()})
	}
	a.format = format
	if a.configPath == "" {
		if a.configPath, err = config.DefaultPath(); err != nil {
			return a.fail(err)
		}
	}
	rest := global.Args()
	ctx := context.Background()
	code, err := a.dispatch(ctx, rest[0], rest[1:])
	if err != nil {
		failed := a.fail(err)
		if failed == ExitUsage || code == ExitOK {
			return failed
		}
		return code // keep a specific code such as ExitRunFailed
	}
	return code
}

func (a *app) fail(err error) int {
	var ue usageError
	if errors.As(err, &ue) {
		_, _ = fmt.Fprintf(a.io.Err, "error: %s\nRun 'copilot --help' for usage.\n", ue.msg)
		return ExitUsage
	}
	_, _ = fmt.Fprintf(a.io.Err, "error: %v\n", err)
	return ExitError
}

func (a *app) dispatch(ctx context.Context, cmd string, args []string) (int, error) {
	switch cmd {
	case "version":
		return a.version(args)
	case "doctor":
		return a.doctor(ctx)
	case "login":
		return a.login(ctx, args)
	case "logout":
		return a.logout()
	case "ask":
		return a.ask(ctx, args)
	case "api":
		return a.sub(ctx, "api", args, map[string]func(context.Context, []string) (int, error){
			"search": a.apiSearch, "describe": a.apiDescribe,
		})
	case "runs":
		return a.sub(ctx, "runs", args, map[string]func(context.Context, []string) (int, error){
			"list": a.runsList, "get": a.runsGet, "approve": a.runsApprove, "reject": a.runsReject,
		})
	case "approvals":
		return a.runsList(ctx, append([]string{"--status", "AWAITING_APPROVAL"}, args...))
	case "skills":
		return a.sub(ctx, "skills", args, map[string]func(context.Context, []string) (int, error){"list": a.skillsList})
	case "eval":
		return a.sub(ctx, "eval", args, map[string]func(context.Context, []string) (int, error){"run": a.evalRun})
	default:
		return ExitUsage, usagef("unknown command %q", cmd)
	}
}

func (a *app) sub(ctx context.Context, group string, args []string, cmds map[string]func(context.Context, []string) (int, error)) (int, error) {
	if len(args) == 0 {
		return ExitUsage, usagef("%s needs a subcommand", group)
	}
	fn, ok := cmds[args[0]]
	if !ok {
		return ExitUsage, usagef("unknown command %q", group+" "+args[0])
	}
	return fn(ctx, args[1:])
}

// parse parses flags that may appear before or after positional arguments.
func parse(fs *flag.FlagSet, args []string) ([]string, error) {
	fs.SetOutput(io.Discard)
	var positional []string
	for {
		if err := fs.Parse(args); err != nil {
			return nil, usagef("%v", err)
		}
		args = fs.Args()
		if len(args) == 0 {
			return positional, nil
		}
		if args[0] == "--" {
			return append(positional, args[1:]...), nil
		}
		positional = append(positional, args[0])
		args = args[1:]
	}
}

func (a *app) loadConfig() (config.Config, error) {
	cfg, err := config.Load(a.configPath)
	if err != nil {
		return cfg, fmt.Errorf("load config: %w", err)
	}
	if a.backendURL != "" {
		cfg.BackendURL = a.backendURL
	}
	return cfg, nil
}

func (a *app) client(requireToken bool) (*client.Client, config.Config, error) {
	cfg, err := a.loadConfig()
	if err != nil {
		return nil, cfg, err
	}
	if requireToken && cfg.Token == "" {
		return nil, cfg, errors.New("not logged in; run 'copilot login'")
	}
	c, err := client.New(cfg.BackendURL, cfg.Token, version, a.timeout)
	if err != nil {
		return nil, cfg, fmt.Errorf("backend client: %w", err)
	}
	return c, cfg, nil
}

func (a *app) printf(format string, args ...any) {
	_, _ = fmt.Fprintf(a.io.Out, format, args...)
}

func (a *app) version(args []string) (int, error) {
	fs := flag.NewFlagSet("version", flag.ContinueOnError)
	short := fs.Bool("short", false, "")
	if _, err := parse(fs, args); err != nil {
		return ExitUsage, err
	}
	if *short {
		a.printf("%s\n", version)
		return ExitOK, nil
	}
	if a.format == output.JSON {
		return ExitOK, output.WriteJSON(a.io.Out, map[string]string{"version": version, "commit": commit, "build_date": buildDate})
	}
	a.printf("Enterprise API Copilot CLI\n  Version:    %s\n  Commit:     %s\n  Build date: %s\n", version, commit, buildDate)
	return ExitOK, nil
}

func (a *app) login(ctx context.Context, args []string) (int, error) {
	fs := flag.NewFlagSet("login", flag.ContinueOnError)
	user := fs.String("user", "", "")
	tokenStdin := fs.Bool("token-stdin", false, "")
	if _, err := parse(fs, args); err != nil {
		return ExitUsage, err
	}
	if (*user == "") == !*tokenStdin {
		return ExitUsage, usagef("login needs exactly one of --user NAME or --token-stdin")
	}
	cfg, err := a.loadConfig()
	if err != nil {
		return ExitError, err
	}
	c, err := client.New(cfg.BackendURL, "", version, a.timeout)
	if err != nil {
		return ExitError, fmt.Errorf("backend client: %w", err)
	}
	token := ""
	if *tokenStdin {
		raw, err := io.ReadAll(io.LimitReader(a.io.In, 16<<10))
		if err != nil {
			return ExitError, fmt.Errorf("read token: %w", err)
		}
		token = strings.TrimSpace(string(raw))
	} else {
		t, err := c.DevToken(ctx, *user)
		if err != nil {
			return ExitError, fmt.Errorf("login: %w", err)
		}
		token = t.AccessToken
	}
	authed, err := client.New(cfg.BackendURL, token, version, a.timeout)
	if err != nil {
		return ExitError, fmt.Errorf("backend client: %w", err)
	}
	me, err := authed.Me(ctx)
	if err != nil {
		return ExitError, fmt.Errorf("token rejected: %w", err)
	}
	cfg.Token, cfg.Subject = token, me.Subject
	if err := config.Save(a.configPath, cfg); err != nil {
		return ExitError, err
	}
	a.printf("Logged in as %s (tenant %s, roles %s) at %s\n", me.Subject, me.TenantID, strings.Join(me.Roles, ","), cfg.BackendURL)
	return ExitOK, nil
}

func (a *app) logout() (int, error) {
	cfg, err := a.loadConfig()
	if err != nil {
		return ExitError, err
	}
	cfg.Token, cfg.Subject = "", ""
	if err := config.Save(a.configPath, cfg); err != nil {
		return ExitError, err
	}
	a.printf("Logged out.\n")
	return ExitOK, nil
}

func (a *app) doctor(ctx context.Context) (int, error) {
	ok := true
	check := func(name string, err error, detail string) {
		if err != nil {
			ok = false
			a.printf("  ✗ %-22s %v\n", name, err)
			return
		}
		a.printf("  ✓ %-22s %s\n", name, detail)
	}
	a.printf("Enterprise API Copilot — doctor\n\n")
	cfg, err := a.loadConfig()
	check("config", err, a.configPath)
	if err != nil {
		return ExitError, nil
	}
	c, err := client.New(cfg.BackendURL, cfg.Token, version, 10*time.Second)
	check("backend URL", err, cfg.BackendURL)
	if err != nil {
		return ExitError, nil
	}
	h, err := c.Health(ctx)
	check("backend health", err, fmt.Sprintf("%s %s (%s)", h.Service, h.Version, h.Status))
	if cfg.Token == "" {
		check("login", errors.New("not logged in (run 'copilot login')"), "")
	} else {
		me, err := c.Me(ctx)
		check("login", err, fmt.Sprintf("%s @ %s", me.Subject, me.TenantID))
	}
	if !ok {
		return ExitError, nil
	}
	return ExitOK, nil
}

func (a *app) skillsList(ctx context.Context, _ []string) (int, error) {
	c, _, err := a.client(true)
	if err != nil {
		return ExitError, err
	}
	skills, err := c.Skills(ctx)
	if err != nil {
		return ExitError, err
	}
	if a.format == output.JSON {
		return ExitOK, output.WriteJSON(a.io.Out, skills)
	}
	rows := make([][]string, 0, len(skills))
	for _, s := range skills {
		approval := "no"
		if s.RequiresApproval {
			approval = "yes"
		}
		rows = append(rows, []string{s.ID, s.Version, s.SideEffect, approval, strings.Join(s.RequiredPermissions, ",")})
	}
	return ExitOK, output.Table(a.io.Out, []string{"SKILL", "VERSION", "SIDE EFFECT", "APPROVAL", "PERMISSIONS"}, rows)
}

func osIO() IO { return IO{In: os.Stdin, Out: os.Stdout, Err: os.Stderr} }

// Main runs the CLI with the process streams.
func Main() int { return Run(os.Args[1:], osIO()) }
