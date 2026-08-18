package com.allotmint.mcp.integration;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.model.AllotMintHealthStatus;
import com.allotmint.mcp.tool.AllotMintHealthTool;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Exercises {@code allotmint_health} against a real AllotMint backend.
 *
 * <p>Per the issue: "Integration test passes against a local AllotMint backend started with {@code
 * DISABLE_AUTH=true}." Start the backend first, e.g. from the {@code allotmint} repo:
 *
 * <pre>
 *   DISABLE_AUTH=true bash scripts/bash/run-local-api.sh
 * </pre>
 *
 * then point this test at it, e.g. {@code ALLOTMINT_API_BASE=http://localhost:8000 mvn test
 * -Dtest=AllotMintHealthToolIntegrationTest}. No auth token is needed since the backend's {@code
 * /openapi.json} route (what {@link AllotMintClient#health()} calls) isn't gated.
 *
 * <p>When no backend is reachable at {@code allotmint.api.base-url} - e.g. a plain {@code mvn test}
 * in CI with nothing else running - the test skips itself via {@link
 * org.junit.jupiter.api.Assumptions#assumeTrue} rather than failing, since that's an environment
 * gap, not a code defect.
 */
@SpringBootTest(properties = "mcp.stdio.enabled=false")
class AllotMintHealthToolIntegrationTest {

  @Autowired private AllotMintClient allotMintClient;

  @Test
  void allotmintHealthReportsReachableBackend() {
    AllotMintHealthStatus status = allotMintClient.health();
    assumeTrue(
        status.reachable(),
        "No AllotMint backend reachable at "
            + status.baseUrl()
            + " - start one locally with DISABLE_AUTH=true to run this test "
            + "(see class Javadoc)");

    assertThat(status.version()).isNotBlank();
    assertThat(status.baseUrl()).isNotBlank();
  }

  @Test
  void allotmintHealthToolReturnsStructuredResult() {
    AllotMintHealthStatus status = allotMintClient.health();
    assumeTrue(status.reachable(), "No AllotMint backend reachable at " + status.baseUrl());

    McpServerFeatures.SyncToolSpecification spec =
        AllotMintHealthTool.specification(allotMintClient);
    McpSchema.CallToolResult result =
        spec.callHandler().apply(null, new McpSchema.CallToolRequest("allotmint_health", Map.of()));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent()).isInstanceOf(Map.class);

    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("reachable", true);
    assertThat(structured).containsKey("version");
    assertThat(structured).containsEntry("baseUrl", status.baseUrl());
  }
}
