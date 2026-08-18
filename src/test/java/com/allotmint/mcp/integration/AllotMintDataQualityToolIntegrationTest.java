package com.allotmint.mcp.integration;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.exception.AllotMintApiException;
import com.allotmint.mcp.model.AllotMintHealthStatus;
import com.allotmint.mcp.tool.AllotMintDataQualityTool;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Exercises {@code allotmint_data_quality} read actions against a real AllotMint backend.
 *
 * <p>Start AllotMint locally with authentication disabled (the data-quality admin endpoints from
 * leonarduk/allotmint#6724 must be present), then run:
 *
 * <pre>
 *   DISABLE_AUTH=true bash scripts/bash/run-local-api.sh
 *   ALLOTMINT_API_BASE=http://localhost:8000 mvn test -Dtest=AllotMintDataQualityToolIntegrationTest
 * </pre>
 *
 * <p>The test skips when the backend is unreachable or does not expose the data-quality admin
 * endpoints, so a normal unit-test run does not require a separately running service. Write actions
 * are not exercised here because they mutate user data; their gating is covered by {@code
 * AllotMintDataQualityToolTest}.
 */
@SpringBootTest(properties = "mcp.stdio.enabled=false")
class AllotMintDataQualityToolIntegrationTest {

  @Autowired private AllotMintClient allotMintClient;

  @Test
  void readActionsReturnStructuredDataWithoutAnOwner() {
    AllotMintHealthStatus status = allotMintClient.health();
    assumeTrue(status.reachable(), "No AllotMint backend reachable at " + status.baseUrl());
    assumeDataQualityEndpointsAvailable();

    McpServerFeatures.SyncToolSpecification specification =
        AllotMintDataQualityTool.specification(allotMintClient, false);

    assertAction(specification, "issues", "issues", "count");
    assertAction(specification, "series", "count", "positions");
    assertAction(specification, "audit", "entries", "count");

    String issueId = firstIssueId(specification);
    if (issueId != null) {
      assertThat(
              specification
                  .callHandler()
                  .apply(
                      null,
                      new McpSchema.CallToolRequest(
                          "allotmint_data_quality",
                          Map.of("action", "preview", "issue_id", issueId)))
                  .isError())
          .isNotEqualTo(Boolean.TRUE);
    }
  }

  private void assertAction(
      McpServerFeatures.SyncToolSpecification specification,
      String action,
      String... expectedKeys) {
    McpSchema.CallToolResult result =
        specification
            .callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest("allotmint_data_quality", Map.of("action", action)));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.structuredContent()).isInstanceOf(Map.class);

    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    assertThat(structured).containsEntry("action", action);
    assertThat(structured).containsKeys(expectedKeys);
  }

  private String firstIssueId(McpServerFeatures.SyncToolSpecification specification) {
    McpSchema.CallToolResult result =
        specification
            .callHandler()
            .apply(
                null,
                new McpSchema.CallToolRequest(
                    "allotmint_data_quality", Map.of("action", "issues")));
    if (Boolean.TRUE.equals(result.isError())
        || !(result.structuredContent() instanceof Map<?, ?> raw)) {
      return null;
    }
    Object issues = raw.get("issues");
    if (!(issues instanceof List<?> list) || list.isEmpty()) {
      return null;
    }
    Object first = list.getFirst();
    if (first instanceof Map<?, ?> issue) {
      Object id = issue.get("id");
      return id == null ? null : String.valueOf(id);
    }
    return null;
  }

  private void assumeDataQualityEndpointsAvailable() {
    try {
      allotMintClient.dataQualityIssues(Map.of());
    } catch (AllotMintApiException | RestClientException e) {
      assumeTrue(false, "Backend lacks /data-quality admin endpoints: " + e.getMessage());
    }
  }
}
