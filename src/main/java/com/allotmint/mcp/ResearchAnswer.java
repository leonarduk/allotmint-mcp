package com.allotmint.mcp;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * Response shape of the research agent sidecar's {@code POST /research/ask}.
 *
 * <p>Citations are assembled by the sidecar from what actually happened during the agent run - the
 * documents retrieval returned and the tool calls the agent really made - not from what the model
 * claims in its prose. That is what makes them traceable: a citation exists here only if the
 * underlying retrieval or tool call exists too. See {@code research-agent/app/agent.py}.
 *
 * @param answer the synthesized prose answer, with inline {@code [n]} markers referring to {@link
 *     #citations()}
 * @param citations every source the answer could draw on, numbered from 1
 * @param toolCalls the v0 MCP tool calls the agent actually made, in order
 * @param grounded false when the run produced neither a retrieved document nor a tool call, meaning
 *     the answer has nothing traceable behind it
 * @param warnings non-fatal problems worth surfacing (retrieval unavailable, no inline citations,
 *     ...)
 * @param model identifier of the LLM the sidecar ran, e.g. {@code ollama:llama3.2}
 */
@JsonIgnoreProperties(ignoreUnknown = true)
record ResearchAnswer(
    String answer,
    List<Citation> citations,
    @JsonProperty("tool_calls") List<ToolCall> toolCalls,
    boolean grounded,
    List<String> warnings,
    String model) {

  /**
   * One numbered source behind the answer.
   *
   * @param id the {@code [n]} marker this citation is referenced by
   * @param kind {@code document} for a retrieved document, {@code tool_call} for an MCP tool call
   * @param ref the document source identifier, or the tool name
   * @param detail distance for documents, serialized arguments for tool calls
   * @param excerpt a short snippet of the retrieved text or tool response
   */
  @JsonIgnoreProperties(ignoreUnknown = true)
  record Citation(int id, String kind, String ref, String detail, String excerpt) {}

  /**
   * One MCP tool invocation made during the agent run.
   *
   * @param tool the MCP tool name, always one of the four read-only v0 tools
   * @param arguments the arguments the agent passed
   */
  @JsonIgnoreProperties(ignoreUnknown = true)
  record ToolCall(String tool, Map<String, Object> arguments) {}

  List<Citation> citationsOrEmpty() {
    return citations == null ? List.of() : citations;
  }

  List<ToolCall> toolCallsOrEmpty() {
    return toolCalls == null ? List.of() : toolCalls;
  }

  List<String> warningsOrEmpty() {
    return warnings == null ? List.of() : warnings;
  }
}
