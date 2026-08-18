package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AllotMintDataQualityToolTest {

  private AllotMintClient client;
  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    client = mock(AllotMintClient.class);
    specification = AllotMintDataQualityTool.specification(client, true);
  }

  @Test
  void metadataRestrictsActionToTheSevenSupportedValues() {
    McpSchema.Tool tool = specification.tool();

    assertThat(tool.name()).isEqualTo("allotmint_data_quality");
    assertThat(tool.inputSchema())
        .containsEntry("required", List.of(AllotMintDataQualityTool.ACTION));
    assertThat(tool.inputSchema()).containsEntry("additionalProperties", false);

    @SuppressWarnings("unchecked")
    Map<String, Object> properties = (Map<String, Object>) tool.inputSchema().get("properties");
    assertThat(properties.get(AllotMintDataQualityTool.ACTION))
        .isEqualTo(
            Map.of(
                "type",
                "string",
                "enum",
                List.of("issues", "series", "preview", "fix", "dedupe", "audit", "undo")));
    assertThat(properties.get(AllotMintDataQualityTool.CONFIRM))
        .isEqualTo(
            Map.of(
                "type",
                "boolean",
                "default",
                false,
                "description",
                "Must be true for the write actions fix, dedupe, and undo; the tool refuses to "
                    + "mutate state otherwise."));
  }

  @Test
  void issuesRequiresNoOwnerAndPassesNoFiltersByDefault() {
    when(client.dataQualityIssues(Map.of())).thenReturn(Map.of("count", 0, "issues", List.of()));

    McpSchema.CallToolResult result = call("issues");

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent())
        .isEqualTo(Map.of("action", "issues", "count", 0, "issues", List.of()));
    verify(client).dataQualityIssues(Map.of());
  }

  @Test
  void issuesForwardsProvidedFilters() {
    when(client.dataQualityIssues(Map.of("type", "WRONG_EXCHANGE", "severity", "high")))
        .thenReturn(Map.of("count", 1, "issues", List.of(Map.of("id", "i1"))));

    McpSchema.CallToolResult result =
        call("issues", Map.of("type", "WRONG_EXCHANGE", "severity", "high"));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    verify(client).dataQualityIssues(Map.of("type", "WRONG_EXCHANGE", "severity", "high"));
  }

  @Test
  void seriesReturnsTheBackendTimeseriesResponse() {
    when(client.dataQualitySeries())
        .thenReturn(Map.of("count", 1, "positions", List.of(Map.of("ticker", "MICC"))));

    McpSchema.CallToolResult result = call("series");

    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of("action", "series", "count", 1, "positions", List.of(Map.of("ticker", "MICC"))));
    verify(client).dataQualitySeries();
  }

  @Test
  void previewRequiresAnIssueId() {
    McpSchema.CallToolResult result = call("preview");

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).contains("issue_id is required"));
    verify(client, never()).dataQualityPreview(anyString());
  }

  @Test
  void previewCallsTheClientWithTheIssueId() {
    when(client.dataQualityPreview("i1"))
        .thenReturn(Map.of("id", "i1", "type", "WRONG_EXCHANGE", "fixable", true));

    McpSchema.CallToolResult result = call("preview", Map.of("issue_id", "i1"));

    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of(
                "action", "preview",
                "issue_id", "i1",
                "id", "i1",
                "type", "WRONG_EXCHANGE",
                "fixable", true));
    verify(client).dataQualityPreview("i1");
  }

  @Test
  void fixRejectedWithoutConfirm() {
    McpSchema.CallToolResult result = call("fix", Map.of("issue_id", "i1"));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class, text -> assertThat(text.text()).contains("confirm=true"));
    verify(client, never()).dataQualityFix(anyString(), anyBoolean());
  }

  @Test
  void fixRejectedWithoutAnIssueIdEvenWhenConfirmed() {
    McpSchema.CallToolResult result = call("fix", Map.of("confirm", true));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).contains("issue_id is required"));
    verify(client, never()).dataQualityFix(anyString(), anyBoolean());
  }

  @Test
  void fixAppliesWhenConfirmed() {
    when(client.dataQualityFix("i1", true))
        .thenReturn(Map.of("status", "fixed", "audit_id", "aud-1"));

    McpSchema.CallToolResult result = call("fix", Map.of("issue_id", "i1", "confirm", true));

    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of(
                "action", "fix",
                "issue_id", "i1",
                "status", "fixed",
                "audit_id", "aud-1"));
    verify(client).dataQualityFix("i1", true);
  }

  @Test
  void dedupeRequiresTickerAndExchange() {
    McpSchema.CallToolResult result = call("dedupe", Map.of("ticker", "MICC", "confirm", true));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).contains("ticker and exchange are required"));
    verify(client, never()).dataQualityDedupe(anyString(), anyString(), anyBoolean());
  }

  @Test
  void dedupeCallsTheClientWhenConfirmed() {
    when(client.dataQualityDedupe("MICC", "L", true))
        .thenReturn(Map.of("status", "fixed", "audit_id", "aud-2"));

    McpSchema.CallToolResult result =
        call("dedupe", Map.of("ticker", "MICC", "exchange", "L", "confirm", true));

    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of(
                "action", "dedupe",
                "ticker", "MICC",
                "exchange", "L",
                "status", "fixed",
                "audit_id", "aud-2"));
    verify(client).dataQualityDedupe("MICC", "L", true);
  }

  @Test
  void auditReturnsTheBackendHistory() {
    when(client.dataQualityAudit())
        .thenReturn(Map.of("count", 1, "entries", List.of(Map.of("id", "aud-1"))));

    McpSchema.CallToolResult result = call("audit");

    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of("action", "audit", "count", 1, "entries", List.of(Map.of("id", "aud-1"))));
    verify(client).dataQualityAudit();
  }

  @Test
  void undoRequiresAnAuditId() {
    McpSchema.CallToolResult result = call("undo", Map.of("confirm", true));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).contains("audit_id is required"));
    verify(client, never()).dataQualityUndo(anyString(), anyBoolean());
  }

  @Test
  void undoCallsTheClientWhenConfirmed() {
    when(client.dataQualityUndo("aud-1", true))
        .thenReturn(Map.of("status", "undone", "audit_id", "aud-1"));

    McpSchema.CallToolResult result = call("undo", Map.of("audit_id", "aud-1", "confirm", true));

    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of(
                "action", "undo",
                "audit_id", "aud-1",
                "status", "undone"));
    verify(client).dataQualityUndo("aud-1", true);
  }

  @Test
  void writeActionsAreRejectedWhenWritesAreDisabled() {
    McpServerFeatures.SyncToolSpecification readOnly =
        AllotMintDataQualityTool.specification(client, false);

    McpSchema.CallToolResult result =
        readOnly
            .callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_data_quality",
                    Map.of("action", "fix", "issue_id", "i1", "confirm", true)));

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text ->
                assertThat(text.text())
                    .contains("write capability is disabled")
                    .contains("allotmint.mcp.write.enabled=false"));
    verify(client, never()).dataQualityFix(anyString(), anyBoolean());
  }

  @Test
  void readActionsStillWorkWhenWritesAreDisabled() {
    McpServerFeatures.SyncToolSpecification readOnly =
        AllotMintDataQualityTool.specification(client, false);
    when(client.dataQualityIssues(Map.of())).thenReturn(Map.of("count", 0, "issues", List.of()));

    McpSchema.CallToolResult result =
        readOnly
            .callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_data_quality", Map.of("action", "issues")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    verify(client).dataQualityIssues(Map.of());
  }

  @Test
  void missingAndUnsupportedActionsAreRejected() {
    McpSchema.CallToolResult missing = call(null);
    assertThat(missing.isError()).isEqualTo(Boolean.TRUE);
    assertThat(missing.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).contains("action must be one of"));

    McpSchema.CallToolResult unsupported = call("unknown");
    assertThat(unsupported.isError()).isEqualTo(Boolean.TRUE);
    assertThat(unsupported.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).contains("action must be one of"));
  }

  @Test
  void backendErrorsSurfaceAsActionableMessages() {
    when(client.dataQualityIssues(Map.of()))
        .thenThrow(new AllotMintApiException(409, "AllotMint backend returned 409: not fixable"));

    McpSchema.CallToolResult result = call("issues");

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).contains("409").contains("not fixable"));
  }

  @Test
  void unreachableBackendIsReportedAsSuch() {
    when(client.dataQualityIssues(Map.of()))
        .thenThrow(new RestClientException("connection refused"));

    McpSchema.CallToolResult result = call("issues");

    assertThat(result.isError()).isEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text ->
                assertThat(text.text())
                    .startsWith("Unable to reach the AllotMint backend:")
                    .contains("connection refused"));
  }

  private McpSchema.CallToolResult call(String action) {
    return call(action, Map.of());
  }

  private McpSchema.CallToolResult call(String action, Map<String, Object> extra) {
    Map<String, Object> arguments = new java.util.LinkedHashMap<>(extra);
    if (action != null) {
      arguments.put(AllotMintDataQualityTool.ACTION, action);
    }
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_data_quality", arguments));
  }
}
