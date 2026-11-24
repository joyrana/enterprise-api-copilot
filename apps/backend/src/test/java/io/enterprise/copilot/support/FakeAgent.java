/*
 * Copyright 2026 Enterprise API Copilot Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package io.enterprise.copilot.support;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.enterprise.copilot.application.AgentGateway;
import io.enterprise.copilot.application.Caller;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

/** Scripted agent service: records each call and answers from a handler. */
public class FakeAgent implements AgentGateway {

  /**
   * One recorded call.
   *
   * @param method the method
   * @param path the path
   * @param query the query
   * @param caller the acting user
   * @param body the body
   */
  public record Call(
      String method, String path, Map<String, String> query, Caller caller, JsonNode body) {}

  private static final ObjectMapper MAPPER = new ObjectMapper();

  public final List<Call> calls = new ArrayList<>();
  public Function<Call, Response> handler = call -> json(200, "{}");
  public String stream = "id: 1\nevent: created\ndata: {}\n\n";
  public String lastEventIdSeen;

  /**
   * Builds a response from JSON text.
   *
   * @param status the status
   * @param json the body
   * @return the response
   */
  public static Response json(int status, String json) {
    try {
      return new Response(status, MAPPER.readTree(json), null);
    } catch (IOException e) {
      throw new IllegalStateException(e);
    }
  }

  @Override
  public Response send(
      String method, String path, Map<String, String> query, Caller caller, JsonNode body) {
    Call call = new Call(method, path, query, caller, body);
    calls.add(call);
    return handler.apply(call);
  }

  @Override
  public void stream(String path, Caller caller, String lastEventId, OutputStream out)
      throws IOException {
    lastEventIdSeen = lastEventId;
    out.write(stream.getBytes(StandardCharsets.UTF_8));
    out.flush();
  }
}
