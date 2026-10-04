// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

package client

// Health mirrors the Health schema.
type Health struct {
	Status  string `json:"status"`
	Service string `json:"service"`
	Version string `json:"version"`
	Mode    string `json:"mode,omitempty"`
}

// Token mirrors TokenResponse.
type Token struct {
	AccessToken string `json:"access_token"`
	TokenType   string `json:"token_type"`
	ExpiresIn   int    `json:"expires_in"`
}

// Me mirrors the Me schema.
type Me struct {
	Subject  string   `json:"subject"`
	TenantID string   `json:"tenant_id"`
	Roles    []string `json:"roles"`
}

// Skill mirrors the Skill schema.
type Skill struct {
	ID                  string   `json:"id"`
	Name                string   `json:"name"`
	Version             string   `json:"version"`
	Description         string   `json:"description"`
	SideEffect          string   `json:"side_effect"`
	RequiredPermissions []string `json:"required_permissions"`
	RequiresApproval    bool     `json:"requires_approval"`
}

// SearchHit mirrors ApiSearchHit.
type SearchHit struct {
	OperationID     string   `json:"operation_id"`
	API             string   `json:"api"`
	Method          string   `json:"method"`
	Path            string   `json:"path"`
	Summary         string   `json:"summary"`
	Scopes          []string `json:"scopes"`
	InvocationSkill string   `json:"invocation_skill"`
	Score           float64  `json:"score"`
	Rank            int      `json:"rank"`
}

// Parameter is one operation parameter.
type Parameter struct {
	Name        string `json:"name"`
	Location    string `json:"location"`
	Required    bool   `json:"required"`
	Description string `json:"description"`
}

// Operation mirrors ApiOperation.
type Operation struct {
	OperationID            string            `json:"operation_id"`
	APITitle               string            `json:"api_title"`
	APIVersion             string            `json:"api_version"`
	Method                 string            `json:"method"`
	Path                   string            `json:"path"`
	Summary                string            `json:"summary"`
	Description            string            `json:"description"`
	Parameters             []Parameter       `json:"parameters"`
	RequestBodySchema      map[string]any    `json:"request_body_schema"`
	RequestBodyRequired    bool              `json:"request_body_required"`
	RequiredScopes         []string          `json:"required_scopes"`
	Authentication         string            `json:"authentication"`
	Responses              map[string]string `json:"responses"`
	RequiresIdempotencyKey bool              `json:"requires_idempotency_key"`
	InvocationSkill        string            `json:"invocation_skill"`
	SideEffect             string            `json:"side_effect"`
}

// PendingApproval mirrors the PendingApproval schema.
type PendingApproval struct {
	StepID      string `json:"step_id"`
	SkillID     string `json:"skill_id"`
	ActionHash  string `json:"action_hash"`
	Environment string `json:"environment"`
	Summary     string `json:"summary"`
}

// TimelineEvent mirrors TimelineEvent.
type TimelineEvent struct {
	Kind   string         `json:"kind"`
	Detail map[string]any `json:"detail"`
}

// Run mirrors the Run schema.
type Run struct {
	RunID           string           `json:"run_id"`
	Status          string           `json:"status"`
	Intent          *string          `json:"intent"`
	Query           string           `json:"query"`
	Environment     string           `json:"environment"`
	Message         string           `json:"message"`
	RequestedBy     string           `json:"requested_by"`
	CreatedAt       string           `json:"created_at"`
	ElapsedS        float64          `json:"elapsed_s"`
	Evidence        []string         `json:"evidence"`
	MissingFields   []string         `json:"missing_fields"`
	ToolCalls       int              `json:"tool_calls"`
	PendingApproval *PendingApproval `json:"pending_approval"`
	Timeline        []TimelineEvent  `json:"timeline"`
}
