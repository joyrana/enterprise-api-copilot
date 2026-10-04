// Copyright 2026 Enterprise API Copilot Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.

// Package client is a typed client for the platform API
// (contracts/openapi/platform-api.yaml). It talks only to the platform backend.
//
// Safety rules: bearer tokens are never sent over plain HTTP to a non-loopback host,
// responses are size-limited, redirects are not followed, and every request carries an
// X-Request-Id for correlation with server logs.
package client

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const maxResponseBytes = 4 << 20

// APIError is the platform's error body plus the HTTP status.
type APIError struct {
	Status    int    `json:"-"`
	Code      string `json:"code"`
	Message   string `json:"message"`
	RequestID string `json:"requestId"`
}

func (e *APIError) Error() string {
	return fmt.Sprintf("%s (HTTP %d): %s [request %s]", e.Code, e.Status, e.Message, e.RequestID)
}

// Client calls the platform API.
type Client struct {
	base      *url.URL
	token     string
	http      *http.Client
	userAgent string
}

// New validates the base URL and returns a client. A token is only accepted for HTTPS
// URLs or loopback hosts.
func New(baseURL, token, version string, timeout time.Duration) (*Client, error) {
	u, err := url.Parse(strings.TrimRight(baseURL, "/"))
	if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
		return nil, fmt.Errorf("invalid backend URL %q", baseURL)
	}
	if u.User != nil {
		return nil, errors.New("backend URL must not contain credentials")
	}
	if token != "" && u.Scheme == "http" && !isLoopback(u.Hostname()) {
		return nil, fmt.Errorf("refusing to send a token over plain HTTP to %s; use https", u.Host)
	}
	return &Client{
		base:  u,
		token: token,
		http: &http.Client{
			Timeout:       timeout,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
		userAgent: "copilot-cli/" + version,
	}, nil
}

func isLoopback(host string) bool {
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func requestID() string {
	b := make([]byte, 8)
	if _, err := rand.Read(b); err != nil {
		return "req_cli"
	}
	return "req_" + hex.EncodeToString(b)
}

func (c *Client) do(ctx context.Context, method, path string, query url.Values, body, out any) error {
	// path is already escaped segment-by-segment; set RawPath so it is not escaped
	// again and never cleaned (url.JoinPath would resolve ".." segments).
	u := *c.base
	rawPath := c.base.EscapedPath() + path
	unescaped, err := url.PathUnescape(rawPath)
	if err != nil {
		return fmt.Errorf("invalid request path: %w", err)
	}
	u.Path, u.RawPath = unescaped, rawPath
	if query != nil {
		u.RawQuery = query.Encode()
	}
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("encode request: %w", err)
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, u.String(), reader)
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", c.userAgent)
	req.Header.Set("X-Request-Id", requestID())
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}
	if len(raw) > maxResponseBytes {
		return errors.New("response exceeded size limit")
	}
	if resp.StatusCode >= 300 {
		apiErr := &APIError{Status: resp.StatusCode}
		if json.Unmarshal(raw, apiErr) != nil || apiErr.Code == "" {
			apiErr.Code = "HTTP_" + strconv.Itoa(resp.StatusCode)
			apiErr.Message = strings.TrimSpace(string(raw))
			if len(apiErr.Message) > 200 {
				apiErr.Message = apiErr.Message[:200]
			}
		}
		if apiErr.RequestID == "" {
			apiErr.RequestID = resp.Header.Get("X-Request-Id")
		}
		return apiErr
	}
	if out == nil {
		return nil
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	return nil
}

// Health checks GET /api/v1/health (no authentication).
func (c *Client) Health(ctx context.Context) (Health, error) {
	var h Health
	return h, c.do(ctx, http.MethodGet, "/api/v1/health", nil, nil, &h)
}

// DevToken obtains a development token (local mode only).
func (c *Client) DevToken(ctx context.Context, subject string) (Token, error) {
	var t Token
	return t, c.do(ctx, http.MethodPost, "/api/v1/auth/dev-token", nil, map[string]string{"subject": subject}, &t)
}

// Me returns the authenticated principal.
func (c *Client) Me(ctx context.Context) (Me, error) {
	var m Me
	return m, c.do(ctx, http.MethodGet, "/api/v1/me", nil, nil, &m)
}

// Skills lists registered skills.
func (c *Client) Skills(ctx context.Context) ([]Skill, error) {
	var out struct {
		Skills []Skill `json:"skills"`
	}
	return out.Skills, c.do(ctx, http.MethodGet, "/api/v1/skills", nil, nil, &out)
}

// SearchAPIs searches the API catalog.
func (c *Client) SearchAPIs(ctx context.Context, q string, limit int) ([]SearchHit, error) {
	var out struct {
		Results []SearchHit `json:"results"`
	}
	query := url.Values{"q": {q}, "limit": {strconv.Itoa(limit)}}
	return out.Results, c.do(ctx, http.MethodGet, "/api/v1/apis/search", query, nil, &out)
}

// DescribeAPI returns one operation's contract.
func (c *Client) DescribeAPI(ctx context.Context, operationID string) (Operation, error) {
	var op Operation
	return op, c.do(ctx, http.MethodGet, "/api/v1/apis/"+url.PathEscape(operationID), nil, nil, &op)
}

// CreateRun asks the copilot to handle a request.
func (c *Client) CreateRun(ctx context.Context, query, environment string) (Run, error) {
	var r Run
	body := map[string]string{"query": query, "environment": environment}
	return r, c.do(ctx, http.MethodPost, "/api/v1/runs", nil, body, &r)
}

// ListRuns lists runs in the caller's tenant (status may be empty).
func (c *Client) ListRuns(ctx context.Context, status string, limit int) ([]Run, error) {
	var out struct {
		Runs []Run `json:"runs"`
	}
	query := url.Values{"limit": {strconv.Itoa(limit)}}
	if status != "" {
		query.Set("status", status)
	}
	return out.Runs, c.do(ctx, http.MethodGet, "/api/v1/runs", query, nil, &out)
}

// GetRun fetches one run.
func (c *Client) GetRun(ctx context.Context, runID string) (Run, error) {
	var r Run
	return r, c.do(ctx, http.MethodGet, "/api/v1/runs/"+url.PathEscape(runID), nil, nil, &r)
}

// Approve approves the pending action whose hash the user saw.
func (c *Client) Approve(ctx context.Context, runID, actionHash string) (Run, error) {
	var r Run
	body := map[string]string{"action_hash": actionHash}
	return r, c.do(ctx, http.MethodPost, "/api/v1/runs/"+url.PathEscape(runID)+"/approve", nil, body, &r)
}

// Reject rejects the pending action.
func (c *Client) Reject(ctx context.Context, runID, reason string) (Run, error) {
	var r Run
	body := map[string]string{}
	if reason != "" {
		body["reason"] = reason
	}
	return r, c.do(ctx, http.MethodPost, "/api/v1/runs/"+url.PathEscape(runID)+"/reject", nil, body, &r)
}
