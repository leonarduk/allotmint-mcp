package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.client.ResearchAgentClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import com.allotmint.mcp.model.ResearchAnswer;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClientException;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import static com.allotmint.mcp.tool.ToolArguments.optionalString;

/**
 * The {@code allotmint_research} tool: answers a compound natural-language question by running an
 * agentic RAG loop - retrieve relevant embedded context, then chain the read-only v0 tools ({@code
 * allotmint_portfolio}, {@code allotmint_instrument}, {@code allotmint_market}, {@code
 * allotmint_health}) as the question requires - and returns a grounded answer with citations.
 *
 * <p>The agent loop itself lives in the Python sidecar (see {@code research-agent/}); this class is
 * the MCP surface over it. That split is the interop decision recorded on issue #12: the agent is a
 * local HTTP service, called the same way {@link AllotMintClient} calls the AllotMint backend.
 *
 * <p>Read-only, like every other tool here. The sidecar reaches the v0 tools as an MCP client
 * against this same server and allowlists those four names, so no write path exists to reach - and
 * {@code allotmint_research} is excluded from that allowlist, so the agent cannot recurse into
 * itself.
 *
 * <p>Registered only when {@code ALLOTMINT_MCP_RESEARCH_ENABLED=true}, following the {@link
 * AllotMintFilesTool} precedent: this is the server's first LLM dependency and its first outbound
 * dependency beyond the AllotMint backend, so it is opt-in rather than a default.
 *
 * <p>Because the sidecar reaches the v0 tools over this server's own streamable HTTP endpoint, the
 * server must be started with the {@code http} profile for this tool to work - stdio alone exposes
 * no {@code /mcp} endpoint for the agent to connect back to. Both transports can run at once, so a
 * stdio client such as Claude Desktop still works: launch with {@code
 * --spring.profiles.active=http}.
 */
public final class AllotMintResearchTool {

  static final String ACTION = "action";
  static final String QUESTION = "question";
  static final String OWNER = "owner";
  static final String LOOKBACK_DAYS = "lookback_days";
  static final String LLM_PROVIDER = "llm_provider";

  /** The only supported action. Kept as a list so adding a second one stays a one-line change. */
  private static final List<String> ACTIONS = List.of("ask");

  private static final int DEFAULT_LOOKBACK_DAYS = 365;
  private static final int MAX_LOOKBACK_DAYS = 3650;

  private AllotMintResearchTool() {}

  /**
   * Returns the tool specification bound to the given sidecar client.
   *
   * @param client the research agent sidecar client
   * @return the tool specification
   * @throws IllegalArgumentException if the sidecar base URL is not configured
   */
  public static McpServerFeatures.SyncToolSpecification specification(ResearchAgentClient client) {
    if (client == null || !StringUtils.hasText(client.baseUrl())) {
      throw new IllegalArgumentException(
          "ALLOTMINT_RESEARCH_BASE_URL is required when ALLOTMINT_MCP_RESEARCH_ENABLED=true");
    }

    Map<String, Object> properties = new LinkedHashMap<>();
    properties.put(ACTION, Map.of("type", "string", "enum", ACTIONS));
    properties.put(
        QUESTION,
        Map.of(
            "type",
            "string",
            "minLength",
            1,
            "description",
            "Natural-language question about the portfolio, an instrument, or the" + " market"));
    properties.put(
        OWNER,
        Map.of(
            "type", "string",
            "minLength", 1,
            "description", "Owner slug scoping portfolio lookups; returned by GET /owners"));
    properties.put(
        LOOKBACK_DAYS,
        Map.of(
            "type",
            "integer",
            "minimum",
            1,
            "maximum",
            MAX_LOOKBACK_DAYS,
            "default",
            DEFAULT_LOOKBACK_DAYS,
            "description",
            "How far back dated documents are considered during retrieval"));
    properties.put(
        LLM_PROVIDER,
        Map.of(
            "type", "string",
            "minLength", 1,
            "description",
                "Optional LLM provider advertised by the research-agent health endpoint"));

    Map<String, Object> inputSchema =
        Map.of(
            "type",
            "object",
            "properties",
            properties,
            "required",
            List.of(ACTION, QUESTION),
            "additionalProperties",
            false);

    McpSchema.Tool tool =
        McpSchema.Tool.builder("allotmint_research", inputSchema)
            .description(
                "Answers a compound question about AllotMint data by retrieving relevant context"
                    + " and chaining the read-only allotmint_portfolio, allotmint_instrument,"
                    + " allotmint_market, and allotmint_health tools as needed. Returns a"
                    + " grounded answer whose [n] markers cite the retrieved documents and tool"
                    + " calls it is built from. Read-only.")
            .build();

    return McpServerFeatures.SyncToolSpecification.builder()
        .tool(tool)
        .callHandler((exchange, request) -> call(client, request.arguments()))
        .build();
  }

  private static McpSchema.CallToolResult call(
      ResearchAgentClient client, Map<String, Object> arguments) {
    String action = optionalString(arguments, ACTION);
    if (action == null || !ACTIONS.contains(action.toLowerCase(Locale.ROOT))) {
      return error("action must be one of: ask");
    }

    String question = optionalString(arguments, QUESTION);
    if (question == null) {
      return error("question is required and must be a non-empty string");
    }

    String owner = optionalString(arguments, OWNER);
    String llmProvider = optionalString(arguments, LLM_PROVIDER);

    Object rawLookback = arguments.get(LOOKBACK_DAYS);
    Integer lookbackDays = optionalInteger(rawLookback);
    if (lookbackDays == null) {
      if (rawLookback != null) {
        return error("lookback_days must be an integer");
      }
      lookbackDays = DEFAULT_LOOKBACK_DAYS;
    } else if (lookbackDays < 1 || lookbackDays > MAX_LOOKBACK_DAYS) {
      return error("lookback_days must be between 1 and %d".formatted(MAX_LOOKBACK_DAYS));
    }

    ResearchAnswer answer;
    try {
      answer =
          llmProvider == null
              ? client.ask(question, owner, lookbackDays)
              : client.ask(question, owner, lookbackDays, llmProvider);
    } catch (AllotMintApiException e) {
      return error(e.getMessage());
    } catch (RestClientException e) {
      return error(
          "Unable to reach the research agent at %s: %s"
              .formatted(client.baseUrl(), e.getMessage()));
    }

    return render(question, owner, lookbackDays, answer);
  }

  /**
   * Renders the sidecar's answer as MCP content. The text block is the answer followed by a
   * numbered Sources list, so a client that only renders text still sees where every {@code [n]}
   * marker points; the same data is repeated verbatim in {@code structuredContent} for clients that
   * consume it programmatically.
   *
   * <p>An ungrounded run - no retrieved document and no tool call behind it - is returned as an
   * error rather than as prose. Plausible-sounding text with nothing traceable behind it is exactly
   * the failure mode this tool exists to avoid.
   */
  private static McpSchema.CallToolResult render(
      String question, String owner, int lookbackDays, ResearchAnswer answer) {
    List<ResearchAnswer.Citation> citations = answer.citationsOrEmpty();

    if (!answer.grounded()) {
      return error(
          "The research agent produced an answer with no retrieved context and no tool calls"
              + " behind it, so it cannot be cited. Check that the retrieval store is populated"
              + " (research-agent/ingest.py) and that the v0 MCP tools are reachable from the"
              + " agent."
              + (answer.warningsOrEmpty().isEmpty()
                  ? ""
                  : " Agent warnings: " + String.join("; ", answer.warningsOrEmpty())));
    }

    StringBuilder text = new StringBuilder(answer.answer() == null ? "" : answer.answer());
    if (!citations.isEmpty()) {
      text.append("\n\nSources:");
      for (ResearchAnswer.Citation citation : citations) {
        text.append("\n[%d] %s: %s".formatted(citation.id(), citation.kind(), citation.ref()));
        if (StringUtils.hasText(citation.detail())) {
          text.append(" (%s)".formatted(citation.detail()));
        }
      }
    }
    for (String warning : answer.warningsOrEmpty()) {
      text.append("\n\nWarning: ").append(warning);
    }

    Map<String, Object> structured = new LinkedHashMap<>();
    structured.put("action", "ask");
    structured.put("question", question);
    if (owner != null) {
      structured.put("owner", owner);
    }
    structured.put(LOOKBACK_DAYS, lookbackDays);
    structured.put("answer", answer.answer());
    structured.put("citations", citationMaps(citations));
    structured.put("tool_calls", toolCallMaps(answer.toolCallsOrEmpty()));
    structured.put("grounded", answer.grounded());
    structured.put("warnings", answer.warningsOrEmpty());
    if (answer.model() != null) {
      structured.put("model", answer.model());
    }

    return McpSchema.CallToolResult.builder()
        .addTextContent(text.toString())
        .structuredContent(structured)
        .build();
  }

  private static List<Map<String, Object>> citationMaps(List<ResearchAnswer.Citation> citations) {
    List<Map<String, Object>> rows = new ArrayList<>();
    for (ResearchAnswer.Citation citation : citations) {
      Map<String, Object> row = new LinkedHashMap<>();
      row.put("id", citation.id());
      row.put("kind", citation.kind());
      row.put("ref", citation.ref());
      if (citation.detail() != null) {
        row.put("detail", citation.detail());
      }
      if (citation.excerpt() != null) {
        row.put("excerpt", citation.excerpt());
      }
      rows.add(row);
    }
    return rows;
  }

  private static List<Map<String, Object>> toolCallMaps(List<ResearchAnswer.ToolCall> toolCalls) {
    List<Map<String, Object>> rows = new ArrayList<>();
    for (ResearchAnswer.ToolCall toolCall : toolCalls) {
      Map<String, Object> row = new LinkedHashMap<>();
      row.put("tool", toolCall.tool());
      row.put("arguments", toolCall.arguments() == null ? Map.of() : toolCall.arguments());
      rows.add(row);
    }
    return rows;
  }

  /**
   * Reads an integer argument. MCP clients are inconsistent about JSON number types - a value that
   * left the client as {@code 30} can arrive as an Integer, a Double, or a String - so all three
   * are accepted, and anything else is treated as absent.
   */
  private static Integer optionalInteger(Object value) {
    if (value instanceof Number number) {
      // Reject non-integral values (e.g. 30.5) instead of silently truncating them,
      // so this matches the String path below, where Integer.valueOf("30.5") throws.
      double doubleValue = number.doubleValue();
      if (doubleValue != Math.rint(doubleValue)) {
        return null;
      }
      return number.intValue();
    }
    if (value instanceof String text && !text.isBlank()) {
      try {
        return Integer.valueOf(text.trim());
      } catch (NumberFormatException ignored) {
        return null;
      }
    }
    return null;
  }

  private static McpSchema.CallToolResult error(String message) {
    return McpSchema.CallToolResult.builder().addTextContent(message).isError(true).build();
  }
}
