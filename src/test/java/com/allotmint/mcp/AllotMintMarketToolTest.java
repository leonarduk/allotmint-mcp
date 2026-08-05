package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class AllotMintMarketToolTest {

  private AllotMintClient client;
  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    client = mock(AllotMintClient.class);
    specification = AllotMintMarketTool.specification(client);
  }

  @Test
  void metadataRestrictsActionToTheThreeSupportedValues() {
    McpSchema.Tool tool = specification.tool();

    assertThat(tool.name()).isEqualTo("allotmint_market");
    assertThat(tool.inputSchema()).containsEntry("required", List.of(AllotMintMarketTool.ACTION));

    @SuppressWarnings("unchecked")
    Map<String, Object> properties = (Map<String, Object>) tool.inputSchema().get("properties");
    assertThat(properties.get(AllotMintMarketTool.ACTION))
        .isEqualTo(
            Map.of(
                "type",
                "string",
                "enum",
                List.of(
                    AllotMintMarketTool.OVERVIEW,
                    AllotMintMarketTool.MOVERS,
                    AllotMintMarketTool.INDICES)));
  }

  @Test
  void overviewReturnsTheCombinedBackendResponseFromOneCall() {
    Map<String, Object> overview =
        Map.of(
            "indexes", Map.of("FTSE 100", Map.of("level", 8200, "change", 0.4)),
            "sectors", List.of(Map.of("sector", "Energy", "change", 1.2)),
            "headlines", List.of(Map.of("headline", "Markets rise")));
    when(client.marketOverview()).thenReturn(overview);

    McpSchema.CallToolResult result = call(AllotMintMarketTool.OVERVIEW);

    assertThat(result.structuredContent()).isEqualTo(overview);
    verify(client).marketOverview();
    verify(client, never()).marketMovers();
  }

  @Test
  void moversReturnsTheStandaloneMoversResponse() {
    Map<String, Object> movers =
        Map.of(
            "gainers", List.of(Map.of("ticker", "AAA", "change", 4.2)),
            "losers", List.of(Map.of("ticker", "BBB", "change", -3.1)));
    when(client.marketMovers()).thenReturn(movers);

    McpSchema.CallToolResult result = call(AllotMintMarketTool.MOVERS);

    assertThat(result.structuredContent()).isEqualTo(movers);
    verify(client).marketMovers();
    verify(client, never()).marketOverview();
  }

  @Test
  void indicesSlicesIndexesFromOneOverviewCall() {
    Map<String, Object> indexes = Map.of("S&P 500", Map.of("level", 5500, "change", -0.2));
    when(client.marketOverview())
        .thenReturn(
            Map.of(
                "indexes", indexes,
                "sectors", List.of(Map.of("sector", "Technology", "change", 0.8)),
                "headlines", List.of()));

    McpSchema.CallToolResult result = call(AllotMintMarketTool.INDICES);

    assertThat(result.structuredContent()).isEqualTo(indexes);
    verify(client).marketOverview();
    verify(client, never()).marketMovers();
  }

  @Test
  void indicesAlsoAcceptsAnIndicesKeyFromCompatibleBackends() {
    Map<String, Object> indices = Map.of("NASDAQ", Map.of("level", 18000, "change", 0.5));
    when(client.marketOverview()).thenReturn(Map.of("indices", indices));

    McpSchema.CallToolResult result = call(AllotMintMarketTool.INDICES);

    assertThat(result.structuredContent()).isEqualTo(indices);
  }

  @Test
  void missingAndUnsupportedActionsAreRejected() {
    assertThatThrownBy(
            () ->
                specification
                    .callHandler()
                    .apply(null, new McpSchema.CallToolRequest("allotmint_market", Map.of())))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("action is required");

    assertThatThrownBy(() -> call("unknown"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("Unsupported action 'unknown'");
  }

  private McpSchema.CallToolResult call(String action) {
    return specification
        .callHandler()
        .apply(
            null,
            new McpSchema.CallToolRequest(
                "allotmint_market", Map.of(AllotMintMarketTool.ACTION, action)));
  }
}
