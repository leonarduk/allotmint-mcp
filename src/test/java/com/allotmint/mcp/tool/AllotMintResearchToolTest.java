package com.allotmint.mcp.tool;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.allotmint.mcp.ResearchAgentClient;
import com.allotmint.mcp.error.AllotMintApiException;
import com.allotmint.mcp.pojo.ResearchAnswer;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.ResourceAccessException;

class AllotMintResearchToolTest {

  private ResearchAgentClient client;
  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    client = mock(ResearchAgentClient.class);
    when(client.baseUrl()).thenReturn("http://localhost:8100");
    specification = AllotMintResearchTool.specification(client);
  }

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_research", arguments));
  }

  private static String textOf(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().getFirst()).text();
  }

  private static ResearchAnswer groundedAnswer() {
    return new ResearchAnswer(
        "Technology rose from 18% to 27% [1], driven by AI chip demand [2].",
        List.of(
            new ResearchAnswer.Citation(
                1, "document", "report:portfolio.sectors", "cosine distance 0.6171", "Technology"),
            new ResearchAnswer.Citation(
                2,
                "tool_call",
                "allotmint_portfolio",
                "allotmint_portfolio(action='exposure')",
                "{\"sectors\":[]}")),
        List.of(
            new ResearchAnswer.ToolCall(
                "allotmint_portfolio", Map.of("action", "exposure", "owner", "demo")),
            new ResearchAnswer.ToolCall("allotmint_instrument", Map.of("action", "news"))),
        true,
        List.of(),
        "ollama:llama3.2");
  }

  @Test
  void exposesTheSchemaFromTheDesignDoc() {
    McpSchema.Tool tool = specification.tool();

    assertThat(tool.name()).isEqualTo("allotmint_research");

    Map<String, Object> schema = tool.inputSchema();
    @SuppressWarnings("unchecked")
    Map<String, Object> properties = (Map<String, Object>) schema.get("properties");

    assertThat(properties).containsOnlyKeys("action", "question", "owner", "lookback_days");
    assertThat(schema.get("required")).isEqualTo(List.of("action", "question"));
    assertThat(schema.get("additionalProperties")).isEqualTo(false);

    @SuppressWarnings("unchecked")
    Map<String, Object> action = (Map<String, Object>) properties.get("action");
    assertThat(action.get("enum")).isEqualTo(List.of("ask"));

    @SuppressWarnings("unchecked")
    Map<String, Object> lookback = (Map<String, Object>) properties.get("lookback_days");
    assertThat(lookback.get("type")).isEqualTo("integer");
    assertThat(lookback.get("default")).isEqualTo(365);
  }

  @Test
  void requiresAConfiguredSidecarUrl() {
    ResearchAgentClient unconfigured = mock(ResearchAgentClient.class);
    when(unconfigured.baseUrl()).thenReturn("");

    assertThatThrownBy(() -> AllotMintResearchTool.specification(unconfigured))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("ALLOTMINT_RESEARCH_BASE_URL");
  }

  @Test
  void rejectsAnUnsupportedAction() {
    McpSchema.CallToolResult result = call(Map.of("action", "summarize", "question", "why?"));

    assertThat(result.isError()).isTrue();
    assertThat(textOf(result)).contains("action must be one of: ask");
  }

  @Test
  void rejectsABlankQuestion() {
    McpSchema.CallToolResult result = call(Map.of("action", "ask", "question", "   "));

    assertThat(result.isError()).isTrue();
    assertThat(textOf(result)).contains("question is required");
  }

  @Test
  void rejectsAnOutOfRangeLookback() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "ask", "question", "why?", "lookback_days", 99999));

    assertThat(result.isError()).isTrue();
    assertThat(textOf(result)).contains("lookback_days must be between 1 and 3650");
  }

  @Test
  void rejectsANonNumericLookback() {
    McpSchema.CallToolResult result =
        call(Map.of("action", "ask", "question", "why?", "lookback_days", "soon"));

    assertThat(result.isError()).isTrue();
    assertThat(textOf(result)).contains("lookback_days must be an integer");
  }

  @Test
  void defaultsLookbackToOneYearWhenAbsent() {
    when(client.ask(any(), any(), anyInt())).thenReturn(groundedAnswer());

    call(Map.of("action", "ask", "question", "how has my tech exposure changed?"));

    verify(client).ask("how has my tech exposure changed?", null, 365);
  }

  @Test
  void acceptsALookbackSentAsAJsonDouble() {
    // MCP clients are inconsistent about number types; 30 can arrive as 30.0.
    when(client.ask(any(), any(), anyInt())).thenReturn(groundedAnswer());

    call(Map.of("action", "ask", "question", "why?", "owner", "demo", "lookback_days", 30.0));

    verify(client).ask("why?", "demo", 30);
  }

  @Test
  void rendersTheAnswerWithANumberedSourceList() {
    when(client.ask(any(), any(), anyInt())).thenReturn(groundedAnswer());

    McpSchema.CallToolResult result =
        call(
            Map.of(
                "action",
                "ask",
                "question",
                "how has my tech exposure changed this year, and why?",
                "owner",
                "demo"));

    assertThat(result.isError()).isNotEqualTo(true);

    String text = textOf(result);
    assertThat(text).contains("Technology rose from 18% to 27% [1]");
    assertThat(text).contains("Sources:");
    assertThat(text).contains("[1] document: report:portfolio.sectors (cosine distance 0.6171)");
    assertThat(text).contains("[2] tool_call: allotmint_portfolio");

    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("owner", "demo").containsEntry("grounded", true);
    assertThat(structured).containsEntry("lookback_days", 365);
    assertThat(structured).containsEntry("model", "ollama:llama3.2");

    @SuppressWarnings("unchecked")
    List<Map<String, Object>> toolCalls = (List<Map<String, Object>>) structured.get("tool_calls");
    assertThat(toolCalls)
        .extracting(row -> row.get("tool"))
        .containsExactly("allotmint_portfolio", "allotmint_instrument");
  }

  @Test
  void surfacesAgentWarningsAlongsideTheAnswer() {
    ResearchAnswer answer =
        new ResearchAnswer(
            "I could not retrieve the sector breakdown.",
            List.of(
                new ResearchAnswer.Citation(
                    1, "tool_call", "allotmint_health", "allotmint_health()", "{}")),
            List.of(new ResearchAnswer.ToolCall("allotmint_health", Map.of())),
            true,
            List.of("Retrieval store unavailable (connection refused)"),
            "ollama:llama3.2");
    when(client.ask(any(), any(), anyInt())).thenReturn(answer);

    McpSchema.CallToolResult result = call(Map.of("action", "ask", "question", "why?"));

    assertThat(textOf(result)).contains("Warning: Retrieval store unavailable");
  }

  @Test
  void reportsAnUngroundedAnswerAsAnErrorRatherThanProse() {
    // The whole point of the tool: prose with nothing traceable behind it is a
    // failure, not a result. It must never reach the client as a normal answer.
    ResearchAnswer ungrounded =
        new ResearchAnswer(
            "Your technology exposure grew substantially this year.",
            List.of(),
            List.of(),
            false,
            List.of("Retrieval store unavailable (connection refused)"),
            "ollama:llama3.2");
    when(client.ask(any(), any(), anyInt())).thenReturn(ungrounded);

    McpSchema.CallToolResult result = call(Map.of("action", "ask", "question", "why?"));

    assertThat(result.isError()).isTrue();
    assertThat(textOf(result))
        .contains("no retrieved context and no tool calls")
        .contains("Retrieval store unavailable")
        .doesNotContain("grew substantially");
  }

  @Test
  void reportsASidecarErrorReadably() {
    when(client.ask(any(), any(), anyInt()))
        .thenThrow(new AllotMintApiException(500, "Research agent returned 500: boom"));

    McpSchema.CallToolResult result = call(Map.of("action", "ask", "question", "why?"));

    assertThat(result.isError()).isTrue();
    assertThat(textOf(result)).contains("Research agent returned 500");
  }

  @Test
  void reportsAnUnreachableSidecarWithItsUrl() {
    when(client.ask(eq("why?"), any(), anyInt()))
        .thenThrow(new ResourceAccessException("Connection refused"));

    McpSchema.CallToolResult result = call(Map.of("action", "ask", "question", "why?"));

    assertThat(result.isError()).isTrue();
    assertThat(textOf(result))
        .contains("Unable to reach the research agent at http://localhost:8100");
  }
}
