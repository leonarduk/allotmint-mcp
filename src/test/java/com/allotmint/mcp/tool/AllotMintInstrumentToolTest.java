package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.error.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentMatchers;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AllotMintInstrumentToolTest {

  @Mock private AllotMintClient client;

  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    specification = AllotMintInstrumentTool.specification(client);
  }

  @Test
  void schemaRequiresOnlyAction() {
    assertThat(specification.tool().name()).isEqualTo("allotmint_instrument");
    assertThat(specification.tool().inputSchema().get("required")).isEqualTo(List.of("action"));
  }

  @Test
  void missingActionReturnsError() {
    McpSchema.CallToolResult result = call(Map.of());

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("action must be one of");
  }

  @Test
  void unknownActionReturnsError() {
    McpSchema.CallToolResult result = call(Map.of("action", "delete"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("action must be one of");
  }

  @Test
  void searchWithoutQueryReturnsErrorWithoutCallingBackend() {
    McpSchema.CallToolResult result = call(Map.of("action", "search"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("query is required");
    verify(client, never()).instrumentSearch(ArgumentMatchers.anyString());
  }

  @Test
  void searchReturnsMatches() {
    List<Map<String, Object>> matches =
        List.of(Map.of("ticker", "VWRL.L", "name", "Vanguard FTSE All-World", "sector", "ETF"));
    when(client.instrumentSearch("vanguard")).thenReturn(matches);

    Map<String, Object> structured =
        structured(call(Map.of("action", "search", "query", "vanguard")));

    assertThat(structured).containsEntry("action", "search").containsEntry("query", "vanguard");
    assertThat(structured.get("matches")).isSameAs(matches);
  }

  @Test
  void detailWithoutTickerReturnsErrorWithoutCallingBackend() {
    McpSchema.CallToolResult result = call(Map.of("action", "detail"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("ticker is required").contains("detail");
    verify(client, never()).instrumentDetail(ArgumentMatchers.anyString());
  }

  @Test
  void detailMergesInstrumentAndNews() {
    Map<String, Object> instrument =
        Map.of(
            "ticker",
            "VWRL.L",
            "name",
            "Vanguard FTSE All-World",
            "positions",
            List.of(Map.of("owner", "steve", "units", 10)),
            "prices",
            List.of(Map.of("date", "2026-08-04", "close", 108.5)));
    List<Map<String, Object>> news =
        List.of(Map.of("headline", "Markets rally", "url", "https://example.com"));
    when(client.instrumentDetail("VWRL.L")).thenReturn(instrument);
    when(client.news("VWRL.L")).thenReturn(news);

    Map<String, Object> structured =
        structured(call(Map.of("action", "detail", "ticker", "VWRL.L")));

    assertThat(structured).containsEntry("action", "detail").containsEntry("ticker", "VWRL.L");
    assertThat(structured).containsEntry("name", "Vanguard FTSE All-World");
    assertThat(structured.get("positions")).isEqualTo(instrument.get("positions"));
    assertThat(structured.get("prices")).isEqualTo(instrument.get("prices"));
    assertThat(structured.get("news")).isSameAs(news);
  }

  @Test
  void pricesWithoutTickerReturnsError() {
    McpSchema.CallToolResult result = call(Map.of("action", "prices"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("ticker is required").contains("prices");
    verify(client, never()).quotes(ArgumentMatchers.anyString());
  }

  @Test
  void pricesReturnsLatestQuote() {
    Map<String, Object> quote = Map.of("symbol", "VWRL.L", "price", 108.5, "previous_close", 107.9);
    when(client.quotes("VWRL.L")).thenReturn(List.of(quote));

    Map<String, Object> structured =
        structured(call(Map.of("action", "prices", "ticker", "VWRL.L")));

    assertThat(structured)
        .containsEntry("action", "prices")
        .containsEntry("ticker", "VWRL.L")
        .containsEntry("quote", quote);
  }

  @Test
  void pricesWithNoQuoteFoundReturnsNullQuote() {
    when(client.quotes("MISSING.L")).thenReturn(List.of());

    Map<String, Object> structured =
        structured(call(Map.of("action", "prices", "ticker", "MISSING.L")));

    assertThat(structured).containsEntry("action", "prices");
    assertThat(structured).containsKey("quote");
    assertThat(structured.get("quote")).isNull();
  }

  @Test
  void newsWithoutTickerReturnsError() {
    McpSchema.CallToolResult result = call(Map.of("action", "news"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("ticker is required").contains("news");
    verify(client, never()).news(ArgumentMatchers.anyString());
  }

  @Test
  void newsReturnsHeadlines() {
    List<Map<String, Object>> headlines =
        List.of(Map.of("headline", "Markets rally", "url", "https://example.com"));
    when(client.news("VWRL.L")).thenReturn(headlines);

    Map<String, Object> structured = structured(call(Map.of("action", "news", "ticker", "VWRL.L")));

    assertThat(structured).containsEntry("action", "news").containsEntry("ticker", "VWRL.L");
    assertThat(structured.get("headlines")).isSameAs(headlines);
  }

  @Test
  void exchangeIsAppendedWhenTickerHasNoSuffix() {
    when(client.news("VWRL.L")).thenReturn(List.of());

    call(Map.of("action", "news", "ticker", "VWRL", "exchange", "L"));

    verify(client).news("VWRL.L");
  }

  @Test
  void exchangeIsIgnoredWhenTickerAlreadyHasASuffix() {
    when(client.news("VWRL.L")).thenReturn(List.of());

    call(Map.of("action", "news", "ticker", "VWRL.L", "exchange", "US"));

    verify(client).news("VWRL.L");
  }

  @Test
  void backendApiErrorsBecomeMcpErrors() {
    when(client.instrumentDetail("MISSING.L"))
        .thenThrow(new AllotMintApiException(404, "AllotMint backend returned 404: not found"));

    McpSchema.CallToolResult result = call(Map.of("action", "detail", "ticker", "MISSING.L"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("404").contains("not found");
  }

  @Test
  void unreachableBackendBecomesMcpError() {
    when(client.instrumentSearch("vanguard"))
        .thenThrow(new RestClientException("connection refused"));

    McpSchema.CallToolResult result = call(Map.of("action", "search", "query", "vanguard"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Unable to reach the AllotMint backend");
  }

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_instrument", arguments));
  }

  @SuppressWarnings("unchecked")
  private static Map<String, Object> structured(McpSchema.CallToolResult result) {
    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    return (Map<String, Object>) result.structuredContent();
  }

  private static String text(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().getFirst()).text();
  }
}
