package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

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
    assertThat(specification.tool().inputSchema().required())
        .containsExactly("action", "owner");
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
    when(client.performance("steve"))
        .thenReturn(Map.of("owner", "steve", "max_drawdown", -0.12));

    McpSchema.CallToolResult result =
        call(Map.of("action", "summary", "owner", "steve"));

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
  void exposureUsesBackendSectorsAndDerivesOtherAvailableBreakdowns() {
    List<Map<String, Object>> sectors =
        List.of(Map.of("sector", "Technology", "market_value_gbp", 1000.0));
    when(client.portfolioSectors("steve")).thenReturn(sectors);
    when(client.portfolio("steve")).thenReturn(portfolio());

    Map<String, Object> structured =
        structured(call(Map.of("action", "exposure", "owner", "steve")));

    assertThat(structured.get("sectors")).isSameAs(sectors);
    assertThat((List<?>) structured.get("asset_classes")).hasSize(2);
    assertThat((List<?>) structured.get("currencies")).hasSize(2);
    verify(client).portfolioSectors("steve");
    verify(client).portfolio("steve");
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
    List<Map<String, Object>> holdings =
        (List<Map<String, Object>>) structured.get("holdings");
    assertThat(holdings)
        .singleElement()
        .satisfies(row -> assertThat(row.get("ticker")).isEqualTo("AAA"));
    assertThat(holdings.getFirst())
        .containsEntry("market_value_gbp", 1000.0)
        .containsEntry("account_type", "ISA")
        .containsEntry("account_currency", "GBP");
  }

  @Test
  void backendErrorsBecomeMcpErrors() {
    when(client.portfolio("missing"))
        .thenThrow(new AllotMintApiException(404, "AllotMint backend returned 404: owner missing"));

    McpSchema.CallToolResult result =
        call(Map.of("action", "holdings", "owner", "missing"));

    assertThat(result.isError()).isTrue();
    assertThat(text(result)).contains("404").contains("owner missing");
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
