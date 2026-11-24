// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package cli

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/client"
	"github.com/joyrana/enterprise-api-copilot/apps/cli/internal/output"
)

// renderComponents prints the generative-UI components the agent chose, as text. Props come
// from the server (built from real step output); unknown components are skipped so a newer
// server never breaks an older CLI. Use --json for the raw run.
func (a *app) renderComponents(run client.Run) {
	for _, c := range run.UI {
		switch c.Component {
		case "operation_list":
			a.renderOperationList(c.Props)
		case "operation_detail":
			a.renderOperationDetail(c.Props)
		case "code_snippets":
			a.renderCodeSnippets(c.Props)
		case "api_response":
			a.renderAPIResponse(c.Props)
		case "doc_sources":
			a.renderDocSources(c.Props)
		case "jwt_report":
			a.renderJWTReport(c.Props)
		case "run_trace":
			a.renderRunTrace(c.Props)
		case "approval_request":
			a.renderApproval(run, c.Props)
		case "clarification":
			a.renderClarification(run, c.Props)
		}
	}
}

func str(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case float64:
		if t == float64(int64(t)) {
			return fmt.Sprintf("%d", int64(t))
		}
		return fmt.Sprintf("%g", t)
	default:
		return fmt.Sprint(t)
	}
}

func list(v any) []any {
	items, _ := v.([]any)
	return items
}

func obj(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func strs(v any) []string {
	out := []string{}
	for _, item := range list(v) {
		out = append(out, str(item))
	}
	return out
}

func (a *app) heading(title string) { a.printf("\n== %s ==\n", title) }

func (a *app) renderOperationList(p map[string]any) {
	a.heading("Matching operations")
	rows := [][]string{}
	for _, item := range list(p["operations"]) {
		op := obj(item)
		rows = append(rows, []string{
			str(op["operation_id"]), str(op["method"]), str(op["path"]), str(op["summary"]),
			strings.Join(strs(op["scopes"]), ","),
		})
	}
	if len(rows) == 0 {
		a.printf("(none)\n")
		return
	}
	_ = output.Table(a.io.Out, []string{"OPERATION", "METHOD", "PATH", "SUMMARY", "SCOPES"}, rows)
}

func (a *app) renderOperationDetail(p map[string]any) {
	a.heading(str(p["operation_id"]))
	a.printf("%s %s", str(p["method"]), str(p["path"]))
	if title := str(p["api_title"]); title != "" {
		a.printf("  (%s %s)", title, str(p["api_version"]))
	}
	a.printf("\n%s\n", str(p["summary"]))
	if desc := str(p["description"]); desc != "" && desc != str(p["summary"]) {
		a.printf("%s\n", desc)
	}
	a.printf("Auth: %s   Scopes: %s   Side effect: %s\n",
		str(p["authentication"]), strings.Join(strs(p["scopes"]), ","), str(p["side_effect"]))
	if params := list(p["parameters"]); len(params) > 0 {
		a.printf("\nParameters:\n")
		rows := [][]string{}
		for _, item := range params {
			q := obj(item)
			required := "optional"
			if b, _ := q["required"].(bool); b {
				required = "required"
			}
			rows = append(rows, []string{str(q["name"]), str(q["location"]), required, str(q["description"])})
		}
		_ = output.Table(a.io.Out, []string{"NAME", "IN", "", "DESCRIPTION"}, rows)
	}
	if fields := list(p["body_fields"]); len(fields) > 0 {
		a.printf("\nRequest body fields:\n")
		rows := [][]string{}
		for _, item := range fields {
			f := obj(item)
			required := "optional"
			if b, _ := f["required"].(bool); b {
				required = "required"
			}
			rows = append(rows, []string{str(f["name"]), str(f["type"]), required, str(f["description"])})
		}
		_ = output.Table(a.io.Out, []string{"FIELD", "TYPE", "", "DESCRIPTION"}, rows)
	}
	if responses := obj(p["responses"]); len(responses) > 0 {
		codes := make([]string, 0, len(responses))
		for code := range responses {
			codes = append(codes, code)
		}
		sort.Strings(codes)
		a.printf("\nResponses:\n")
		for _, code := range codes {
			a.printf("  %s  %s\n", code, str(responses[code]))
		}
	}
}

func (a *app) renderCodeSnippets(p map[string]any) {
	a.heading("Code for " + str(p["operation_id"]))
	snippets := obj(p["snippets"])
	langs := make([]string, 0, len(snippets))
	for lang := range snippets {
		langs = append(langs, lang)
	}
	sort.Strings(langs)
	for _, lang := range langs {
		a.printf("\n--- %s ---\n%s\n", lang, str(snippets[lang]))
	}
	for _, note := range strs(p["notes"]) {
		a.printf("note: %s\n", note)
	}
}

func (a *app) renderAPIResponse(p map[string]any) {
	a.heading("API response")
	verdict := "rejected by the API"
	if b, _ := p["ok"].(bool); b {
		verdict = "succeeded"
	}
	a.printf("%s %s %s with HTTP %s (correlation id %s)\n",
		str(p["method"]), str(p["path"]), verdict, str(p["status_code"]), str(p["correlation_id"]))
	if retry := str(p["retry_after_s"]); retry != "" {
		a.printf("Retry after %s seconds.\n", retry)
	}
	if body := p["response_body"]; body != nil {
		if pretty, err := json.MarshalIndent(body, "", "  "); err == nil {
			a.printf("%s\n", pretty)
		}
	} else if preview := str(p["response_preview"]); preview != "" {
		a.printf("%s\n…(truncated)\n", preview)
	}
	if curl := str(p["curl"]); curl != "" {
		a.printf("\nEquivalent cURL:\n%s\n", curl)
	}
}

func (a *app) renderDocSources(p map[string]any) {
	a.heading("Documentation")
	if b, _ := p["abstained"].(bool); b {
		a.printf("No supported answer was found in the documentation.\n")
	} else if extract := str(p["extract"]); extract != "" {
		a.printf("%s\n", extract)
	}
	if sources := list(p["sources"]); len(sources) > 0 {
		a.printf("\nSources:\n")
		for _, item := range sources {
			s := obj(item)
			flag := ""
			if b, _ := s["flagged"].(bool); b {
				flag = "  [flagged as suspicious]"
			}
			a.printf("  - %s (%s)%s\n", str(s["title"]), str(s["source_id"]), flag)
		}
	}
}

func (a *app) renderJWTReport(p map[string]any) {
	a.heading("Token report")
	a.printf("Algorithm: %s   Kind: %s   Signature verified: %s\n",
		str(p["algorithm"]), str(p["kind"]), str(p["verified"]))
	a.printf("Issued: %s   Expires: %s   Expired: %s\n", str(p["issued_at"]), str(p["expires_at"]), str(p["expired"]))
	a.printf("Scopes: %s\n", strings.Join(strs(p["scopes"]), ", "))
	if missing := strs(p["missing_scopes"]); len(missing) > 0 {
		a.printf("Missing scopes: %s\n", strings.Join(missing, ", "))
	}
	if issues := strs(p["issues"]); len(issues) > 0 {
		a.printf("Problems:\n")
		for _, issue := range issues {
			a.printf("  - %s\n", issue)
		}
	} else {
		a.printf("No problems detected.\n")
	}
	if note := str(p["note"]); note != "" {
		a.printf("%s\n", note)
	}
}

func (a *app) renderRunTrace(p map[string]any) {
	steps := list(p["steps"])
	if len(steps) == 0 {
		return
	}
	a.heading("Steps taken")
	for _, item := range steps {
		s := obj(item)
		mark := "?"
		if ok, isBool := s["ok"].(bool); isBool {
			mark = map[bool]string{true: "ok", false: "failed"}[ok]
		}
		a.printf("  [%s] %-12s %-16s %s\n", mark, str(s["step_id"]), str(s["skill_id"]), str(s["purpose"]))
	}
}

func (a *app) renderApproval(run client.Run, p map[string]any) {
	a.heading("Approval required")
	// The hash shown is the run's authoritative pending approval, never the component's copy.
	summary, hash, skill, env := str(p["summary"]), str(p["action_hash"]), str(p["skill_id"]), str(p["environment"])
	if pending := run.PendingApproval; pending != nil {
		summary, hash, skill, env = pending.Summary, pending.ActionHash, pending.SkillID, pending.Environment
	}
	a.printf("%s in %s:\n  %s\n  action hash: %s\n", skill, env, summary, hash)
	if run.Status == "AWAITING_APPROVAL" {
		a.printf("An approver can run:  copilot runs approve %s   (or: copilot runs reject %s)\n", run.RunID, run.RunID)
	}
}

func (a *app) renderClarification(run client.Run, p map[string]any) {
	a.heading("More information needed")
	if q := str(p["question"]); q != "" && q != run.Message {
		a.printf("%s\n", q)
	}
	fields := []string{}
	for _, f := range strs(p["missing_fields"]) {
		if i := strings.Index(f, "."); i >= 0 {
			f = f[i+1:]
		}
		fields = append(fields, f)
	}
	if len(fields) > 0 {
		a.printf("Missing: %s\n", strings.Join(fields, ", "))
	}
	if run.Status == "NEEDS_CLARIFICATION" {
		a.printf("Answer with:  copilot runs clarify %s \"...\"\n", run.RunID)
	}
}
