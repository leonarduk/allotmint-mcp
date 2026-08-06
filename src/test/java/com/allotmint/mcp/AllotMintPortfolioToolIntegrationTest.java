package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * Exercises {@code allotmint_portfolio} against a real AllotMint backend with demo data.
 *
 * <p>Start AllotMint locally with authentication disabled, then run this test with a valid demo
 * owner slug:
 *
 * <pre>
 *   DISABLE_AUTH=true bash scripts/bash/run-local-api.sh
 *   ALLOTMINT_API_BASE=http://localhost:8000 \
 *     ALLOTMINT_TEST_OWNER=demo mvn test -Dtest=AllotMintPortfolioToolIntegrationTest
 * </pre>
 *
 * <p>The test skips when {@code ALLOTMINT_TEST_OWNER} is unset or the backend is unavailable so a
 * normal unit-test run does not require a separately running service.
 */
@SpringBootTest(properties = "mcp.stdio.enabled=false")
class AllotMintPortfolioToolIntegrationTest {

  @Autowired private AllotMintClient allotMintClient;

  @Test
  void returnsPortfolioActionsForRealOwner() {
    String owner = System.getenv("ALLOTMINT_TEST_OWNER");
    assumeTrue(
        owner != null && !owner.isBlank(),
        "Set ALLOTMINT_TEST_OWNER to a valid slug from GET /owners");
    AllotMintHealthStatus status = allotMintClient.health();
    assumeTrue(status.reachable(), "No AllotMint backend reachable at " + status.baseUrl());

    assertAction(owner, "summary", "total_value_gbp", "performance");
    assertAction(owner, "exposure", "sectors", "currencies");
    assertAction(owner, "holdings", "holdings");
  }

  private void assertAction(String owner, String action, String... expectedKeys) {
    McpServerFeatures.SyncToolSpecification specification =
        AllotMintPortfolioTool.specification(allotMintClient);
    McpSchema.CallToolResult result =
        specification
            .callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_portfolio", Map.of("action", action, "owner", owner)));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent()).isInstanceOf(Map.class);

    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("action", action).containsEntry("owner", owner);
    assertThat(structured).containsKeys(expectedKeys);
    if (action.equals("holdings")) {
      assertThat(structured.get("holdings")).isInstanceOf(List.class);
    }
  }
}
