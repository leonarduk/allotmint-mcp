package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.ResourceAccessException;

import java.math.BigDecimal;
import java.net.ConnectException;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AllotMintPortfolioToolTest {

  @Mock private AllotMintClient client;

  private McpServerFeatures.SyncToolSpecification specification;

  @BeforeEach
  void setUp() {
    specification = AllotMintPortfolioTool.specification(client);
  }

  @Test
  void schemaRequiresActionAndOwner() {
    assertThat(specification.tool().name()).isEqualTo("allotmint_portfolio");
    assertThat(specification.tool().inputSchema().get("required"))
        .isEqualTo(List.of("action", "owner"));
  }

  @Test
  void missingOwnerReturnsDiscoveryHintWithoutCallingBackend() {
    McpSchema.CallToolResult result = call(Map.of("action", "summary"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("owner is required").contains("GET /owners");
    verify(client, never()).portfolio(org.mockito.ArgumentMatchers.anyString());
  }

  @Test
  void summaryComposesPortfolioAndPerformance() {
    when(client.portfolio("steve")).thenReturn(portfolio());
    when(client.performance("steve")).thenReturn(Map.of("owner", "steve", "max_drawdown", -0.12));

    McpSchema.CallToolResult result = call(Map.of("action", "summary", "owner", "steve"));

    Map<String, Object> structured = structured(result);
    assertThat(structured)
        .containsEntry("total_value_gbp", new BigDecimal("1500.0"))
        .containsEntry("day_change_gbp", new BigDecimal("7.5"));
    assertThat((List<?>) structured.get("allocation")).hasSize(2);
    assertThat(structured.get("performance"))
        .isEqualTo(Map.of("owner", "steve", "max_drawdown", -0.12));
    verify(client).portfolio("steve");
    verify(client).performance("steve");
  }

  @Test
  void summaryTreatsNullAndNoneStringsAsAbsentFilters() {
    when(client.portfolio("steve")).thenReturn(portfolio());
    when(client.performance("steve")).thenReturn(Map.of());

    Map<String, Object> withoutFilters =
        structured(call(Map.of("action", "summary", "owner", "steve")));
    Map<String, Object> withSentinels =
        structured(
            call(
                Map.of(
                    "action", "summary",
                    "owner", "steve",
                    "account_type", "NULL",
                    "currency", " none ")));

    assertThat(withSentinels).isEqualTo(withoutFilters);
    assertThat(withSentinels).containsEntry("total_value_gbp", new BigDecimal("1500.0"));
    assertThat((List<?>) withSentinels.get("allocation")).hasSize(2);
  }

  @Test
  void exposureUsesBackendSectorsAndDerivesOtherAvailableBreakdowns() {
    List<Map<String, Object>> sectors =
        List.of(Map.of("sector", "Technology", "market_value_gbp", 1000.0));
    when(client.portfolioSectors("steve")).thenReturn(sectors);
    when(client.portfolio("steve")).thenReturn(portfolio());
    // Historical endpoint is not available: graceful fallback.
    when(client.portfolioSectors("steve", 365))
        .thenThrow(new AllotMintApiException(404, "not found"));

    Map<String, Object> structured =
        structured(call(Map.of("action", "exposure", "owner", "steve")));

    assertThat(structured.get("sectors")).isEqualTo(sectors);
    assertThat((List<?>) structured.get("asset_classes")).hasSize(2);
    assertThat((List<?>) structured.get("currencies")).hasSize(2);
    verify(client).portfolioSectors("steve");
    verify(client).portfolioSectors("steve", 365);
    verify(client).portfolio("steve");
  }

  @Test
  void exposureEnrichesWithDefaultLookbackWhenOmitted() {
    List<Map<String, Object>> current =
        List.of(
            Map.of("sector", "Technology", "contribution_pct", 27.0),
            Map.of("sector", "Financials", "contribution_pct", 15.5));
    List<Map<String, Object>> historical =
        List.of(
            Map.of("sector", "Technology", "contribution_pct", 18.0),
            Map.of("sector", "Financials", "contribution_pct", 17.0));
    when(client.portfolioSectors("steve")).thenReturn(current);
    when(client.portfolioSectors("steve", 365)).thenReturn(historical);
    when(client.portfolio("steve")).thenReturn(portfolio());

    Map<String, Object> structured =
        structured(call(Map.of("action", "exposure", "owner", "steve")));

    @SuppressWarnings("unchecked")
    List<Map<String, Object>> sectors = (List<Map<String, Object>>) structured.get("sectors");
    assertThat(sectors).hasSize(2);
    assertThat(sectors.get(0))
        .containsEntry("sector", "Technology")
        .containsEntry("weight_pct_year_ago", new BigDecimal("18.0"));
    assertThat(sectors.get(1))
        .containsEntry("sector", "Financials")
        .containsEntry("weight_pct_year_ago", new BigDecimal("17.0"));
    verify(client).portfolioSectors("steve", 365);
  }

  @Test
  void exposureSkipsHistoricalLookupWhenLookbackDaysIsZero() {
    List<Map<String, Object>> sectors =
        List.of(Map.of("sector", "Technology", "market_value_gbp", 1000.0));
    when(client.portfolioSectors("steve")).thenReturn(sectors);
    when(client.portfolio("steve")).thenReturn(portfolio());

    Map<String, Object> structured =
        structured(call(Map.of("action", "exposure", "owner", "steve", "lookback_days", 0)));

    assertThat(structured.get("sectors")).isEqualTo(sectors);
    // Must not attempt the historical call when lookback_days is 0.
    verify(client, never()).portfolioSectors(anyString(), anyInt());
  }

  @Test
  void exposureEnrichesSectorsWithYearAgoWeightsWhenLookbackProvided() {
    List<Map<String, Object>> current =
        List.of(
            Map.of("sector", "Technology", "contribution_pct", 27.0),
            Map.of("sector", "Financials", "contribution_pct", 15.5));
    List<Map<String, Object>> historical =
        List.of(
            Map.of("sector", "technology", "contribution_pct", 18.0),
            Map.of("sector", "financials", "contribution_pct", 17.0));
    when(client.portfolioSectors("steve")).thenReturn(current);
    when(client.portfolioSectors("steve", 90)).thenReturn(historical);
    when(client.portfolio("steve")).thenReturn(portfolio());

    Map<String, Object> structured =
        structured(call(Map.of("action", "exposure", "owner", "steve", "lookback_days", 90)));

    @SuppressWarnings("unchecked")
    List<Map<String, Object>> sectors = (List<Map<String, Object>>) structured.get("sectors");
    assertThat(sectors).hasSize(2);
    assertThat(sectors.get(0))
        .containsEntry("sector", "Technology")
        .containsEntry("weight_pct_year_ago", new BigDecimal("18.0"));
    assertThat(sectors.get(1))
        .containsEntry("sector", "Financials")
        .containsEntry("weight_pct_year_ago", new BigDecimal("17.0"));
    verify(client).portfolioSectors("steve", 90);
  }

  @Test
  void exposureOmitsYearAgoWhenHistoricalSectorNameDoesNotMatch() {
    List<Map<String, Object>> current =
        List.of(Map.of("sector", "Technology", "contribution_pct", 27.0));
    List<Map<String, Object>> historical =
        List.of(Map.of("sector", "Healthcare", "contribution_pct", 12.0));
    when(client.portfolioSectors("steve")).thenReturn(current);
    when(client.portfolioSectors("steve", 180)).thenReturn(historical);
    when(client.portfolio("steve")).thenReturn(portfolio());

    Map<String, Object> structured =
        structured(call(Map.of("action", "exposure", "owner", "steve", "lookback_days", 180)));

    @SuppressWarnings("unchecked")
    List<Map<String, Object>> sectors = (List<Map<String, Object>>) structured.get("sectors");
    assertThat(sectors).hasSize(1);
    assertThat(sectors.get(0))
        .containsEntry("sector", "Technology")
        .doesNotContainKey("weight_pct_year_ago");
  }

  @Test
  void holdingsAreFlatSortedAndFilteredCaseInsensitively() {
    when(client.portfolio("steve")).thenReturn(portfolio());

    Map<String, Object> structured =
        structured(
            call(
                Map.of(
                    "action", "holdings",
                    "owner", "steve",
                    "account_type", "isa",
                    "currency", "usd")));

    @SuppressWarnings("unchecked")
    List<Map<String, Object>> holdings = (List<Map<String, Object>>) structured.get("holdings");
    assertThat(holdings)
        .singleElement()
        .satisfies(row -> assertThat(row.get("ticker")).isEqualTo("AAA"));
    assertThat(holdings.getFirst())
        .containsEntry("market_value_gbp", 1000.0)
        .containsEntry("account_type", "ISA")
        .containsEntry("account_currency", "GBP");
  }

  @Test
  void summaryExcludesHistoryByDefault() {
    Map<String, Object> perfWithHistory =
        Map.of(
            "owner",
            "steve",
            "max_drawdown",
            -0.12,
            "history",
            List.of(
                Map.of("date", "2026-08-05", "value_gbp", 1500.0),
                Map.of("date", "2026-08-04", "value_gbp", 1490.0)));
    when(client.portfolio("steve")).thenReturn(portfolio());
    when(client.performance("steve")).thenReturn(perfWithHistory);

    McpSchema.CallToolResult result = call(Map.of("action", "summary", "owner", "steve"));

    @SuppressWarnings("unchecked")
    Map<String, Object> perf = (Map<String, Object>) structured(result).get("performance");
    assertThat(perf).containsEntry("max_drawdown", -0.12).doesNotContainKey("history");
  }

  @Test
  void summaryIncludesHistoryWhenOptedIn() {
    Map<String, Object> perfWithHistory =
        Map.of(
            "owner",
            "steve",
            "max_drawdown",
            -0.12,
            "history",
            List.of(Map.of("date", "2026-08-05", "value_gbp", 1500.0)));
    when(client.portfolio("steve")).thenReturn(portfolio());
    when(client.performance("steve")).thenReturn(perfWithHistory);

    McpSchema.CallToolResult result =
        call(Map.of("action", "summary", "owner", "steve", "include_history", true));

    @SuppressWarnings("unchecked")
    Map<String, Object> perf = (Map<String, Object>) structured(result).get("performance");
    assertThat(perf).containsEntry("max_drawdown", -0.12).containsKey("history");
    assertThat((List<?>) perf.get("history")).hasSize(1);
  }

  @Test
  void backendErrorsBecomeMcpErrors() {
    when(client.portfolio("missing"))
        .thenThrow(new AllotMintApiException(404, "AllotMint backend returned 404: owner missing"));

    McpSchema.CallToolResult result = call(Map.of("action", "holdings", "owner", "missing"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("404").contains("owner missing");
  }

  @Test
  void unreachableBackendSurfacesAsMcpErrorInsteadOfUnhandledException() {
    // Simulates the AllotMint backend being down / connection refused: RestClient wraps that
    // as a ResourceAccessException around a ConnectException, not an AllotMintApiException.
    when(client.portfolio("steve"))
        .thenThrow(
            new ResourceAccessException(
                "I/O error on GET request", new ConnectException("Connection refused")));

    McpSchema.CallToolResult result = call(Map.of("action", "summary", "owner", "steve"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("Unable to reach the AllotMint backend");
  }

  private McpSchema.CallToolResult call(Map<String, Object> arguments) {
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_portfolio", arguments));
  }

  @SuppressWarnings("unchecked")
  private static Map<String, Object> structured(McpSchema.CallToolResult result) {
    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    return (Map<String, Object>) result.structuredContent();
  }

  private static String text(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().getFirst()).text();
  }

  private static Map<String, Object> portfolio() {
    return Map.of(
        "owner",
        "steve",
        "as_of",
        "2026-08-05",
        "accounts",
        List.of(
            Map.of(
                "account_type",
                "ISA",
                "currency",
                "GBP",
                "value_estimate_gbp",
                1000.0,
                "holdings",
                List.of(
                    Map.of(
                        "ticker",
                        "AAA",
                        "currency",
                        "USD",
                        "asset_class",
                        "Equity",
                        "sector",
                        "Technology",
                        "market_value_gbp",
                        1000.0,
                        "day_change_gbp",
                        5.0))),
            Map.of(
                "account_type",
                "SIPP",
                "currency",
                "GBP",
                "value_estimate_gbp",
                500.0,
                "holdings",
                List.of(
                    Map.of(
                        "ticker",
                        "BBB",
                        "currency",
                        "GBP",
                        "instrument_type",
                        "Bond",
                        "sector",
                        "Financials",
                        "market_value_gbp",
                        500.0,
                        "day_change_gbp",
                        2.5)))));
  }
}
