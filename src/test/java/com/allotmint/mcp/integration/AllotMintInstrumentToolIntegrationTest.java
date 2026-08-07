package com.allotmint.mcp.integration;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.model.AllotMintHealthStatus;
import com.allotmint.mcp.tool.AllotMintInstrumentTool;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Exercises {@code allotmint_instrument} against a real AllotMint backend with demo data.
 *
 * <p>Start AllotMint locally with authentication disabled, then run this test with a valid ticker
 * that has price history (and ideally news/quote data) available:
 *
 * <pre>
 *   DISABLE_AUTH=true bash scripts/bash/run-local-api.sh
 *   ALLOTMINT_API_BASE=http://localhost:8000 \
 *     ALLOTMINT_TEST_TICKER=VWRL.L mvn test -Dtest=AllotMintInstrumentToolIntegrationTest
 * </pre>
 *
 * <p>The test skips when {@code ALLOTMINT_TEST_TICKER} is unset or the backend is unavailable so a
 * normal unit-test run does not require a separately running service.
 */
@SpringBootTest(properties = "mcp.stdio.enabled=false")
class AllotMintInstrumentToolIntegrationTest {

  @Autowired private AllotMintClient allotMintClient;

  @Test
  void returnsInstrumentActionsForRealTicker() {
    String ticker = System.getenv("ALLOTMINT_TEST_TICKER");
    assumeTrue(
        ticker != null && !ticker.isBlank(),
        "Set ALLOTMINT_TEST_TICKER to a valid ticker, e.g. VWRL.L");
    AllotMintHealthStatus status = allotMintClient.health();
    assumeTrue(status.reachable(), "No AllotMint backend reachable at " + status.baseUrl());

    assertSearch();
    assertAction(ticker, "detail", "ticker", "news");
    assertAction(ticker, "prices", "ticker", "quote");
    assertAction(ticker, "news", "ticker", "headlines");
  }

  private void assertSearch() {
    McpSchema.CallToolResult result =
        specification()
            .callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_instrument", Map.of("action", "search", "query", "vanguard")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent()).isInstanceOf(Map.class);

    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("action", "search").containsKey("matches");
  }

  private void assertAction(String ticker, String action, String... expectedKeys) {
    McpSchema.CallToolResult result =
        specification()
            .callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_instrument", Map.of("action", action, "ticker", ticker)));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent()).isInstanceOf(Map.class);

    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("action", action);
    assertThat(structured).containsKeys(expectedKeys);
  }

  private McpServerFeatures.SyncToolSpecification specification() {
    return AllotMintInstrumentTool.specification(allotMintClient);
  }
}
