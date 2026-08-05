package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class AllotMintInstrumentToolTest {

  private AllotMintClient client;
  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    client = mock(AllotMintClient.class);
    specification = AllotMintInstrumentTool.specification(client);
  }

  @Test
  void exposesTheDocumentedInputSchema() {
    assertThat(specification.tool().name()).isEqualTo("allotmint_instrument");
    assertThat(specification.tool().inputSchema().required()).containsExactly("action");
    assertThat(specification.tool().inputSchema().properties())
        .containsKeys("action", "query", "ticker", "exchange");
  }

  @Test
  void searchReturnsBackendMatches() {
    List<Map<String, Object>> matches = List.of(Map.of("ticker", "AAPL", "name", "Apple"));
    when(client.searchInstruments("apple")).thenReturn(matches);

    McpSchema.CallToolResult result = call(Map.of("action", "search", "query", " apple "));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent()).isEqualTo(matches);
    verify(client).searchInstruments("apple");
  }

  @Test
  void detailMergesPriceHistoryPositionsAndNews() {
    Map<String, Object> detail =
        Map.of(
            "ticker", "AAPL",
            "prices", List.of(Map.of("date", "2026-08-04", "close", 210.5)),
            "positions", List.of(Map.of("owner", "steve", "units", 2)));
    List<Map<String, Object>> news = List.of(Map.of("headline", "Apple headline"));
    when(client.instrumentDetail("AAPL")).thenReturn(detail);
    when(client.instrumentNews("AAPL")).thenReturn(news);

    McpSchema.CallToolResult result = call(Map.of("action", "detail", "ticker", " AAPL "));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of(
                "ticker",
                "AAPL",
                "prices",
                detail.get("prices"),
                "positions",
                detail.get("positions"),
                "news",
                news));
    verify(client).instrumentDetail("AAPL");
    verify(client).instrumentNews("AAPL");
  }

  @Test
  void pricesReturnsLatestQuoteAndAcceptsUnusedExchange() {
    List<Map<String, Object>> quotes = List.of(Map.of("symbol", "VWRL.L", "price", 135.2));
    when(client.latestQuotes("VWRL.L")).thenReturn(quotes);

    McpSchema.CallToolResult result =
        call(Map.of("action", "prices", "ticker", "VWRL.L", "exchange", "LSE"));

    assertThat(result.structuredContent()).isEqualTo(quotes);
    verify(client).latestQuotes("VWRL.L");
  }

  @Test
  void newsReturnsRecentHeadlines() {
    List<Map<String, Object>> news = List.of(Map.of("headline", "Fund headline"));
    when(client.instrumentNews("VWRL.L")).thenReturn(news);

    McpSchema.CallToolResult result = call(Map.of("action", "news", "ticker", "VWRL.L"));

    assertThat(result.structuredContent()).isEqualTo(news);
    verify(client).instrumentNews("VWRL.L");
  }

  @Test
  void missingQueryIsAToolLevelErrorWithoutCallingTheBackend() {
    McpSchema.CallToolResult result = call(Map.of("action", "search"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("'query' is required");
    verifyNoInteractions(client);
  }

  @Test
  void missingTickerIsAToolLevelErrorWithoutCallingTheBackend() {
    McpSchema.CallToolResult result = call(Map.of("action", "detail"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("'ticker' is required");
    verifyNoInteractions(client);
  }

  @Test
  void unsupportedActionIsAToolLevelError() {
    McpSchema.CallToolResult result = call(Map.of("action", "fundamentals"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Unsupported action 'fundamentals'");
    verifyNoInteractions(client);
  }

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_instrument", arguments));
  }

  private String text(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().getFirst()).text();
  }
}
