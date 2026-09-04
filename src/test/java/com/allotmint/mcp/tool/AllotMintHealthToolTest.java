package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.model.AllotMintHealthStatus;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AllotMintHealthToolTest {

  private static McpSchema.CallToolResult invoke(AllotMintClient client) {
    var specification = AllotMintHealthTool.specification(client);
    return specification
        .callHandler()
        .apply(null, new McpSchema.CallToolRequest("allotmint_health", Map.of()));
  }

  @Test
  void reachableBackendReportsVersionInStructuredContentAndSummary() {
    AllotMintClient client = mock(AllotMintClient.class);
    when(client.health())
        .thenReturn(new AllotMintHealthStatus(true, "1.2.3", "https://api.example.com"));

    McpSchema.CallToolResult result = invoke(client);

    assertThat(result.structuredContent())
        .isEqualTo(
            Map.of(
                "reachable", true,
                "baseUrl", "https://api.example.com",
                "version", "1.2.3"));
    assertThat(textOf(result))
        .isEqualTo("AllotMint backend reachable at https://api.example.com (version 1.2.3)");
  }

  @Test
  void reachableBackendWithoutVersionOmitsVersionKey() {
    AllotMintClient client = mock(AllotMintClient.class);
    when(client.health())
        .thenReturn(new AllotMintHealthStatus(true, null, "https://api.example.com"));

    McpSchema.CallToolResult result = invoke(client);

    assertThat(result.structuredContent())
        .isEqualTo(Map.of("reachable", true, "baseUrl", "https://api.example.com"));
  }

  @Test
  void unreachableBackendReportsUnreachableSummary() {
    AllotMintClient client = mock(AllotMintClient.class);
    when(client.health())
        .thenReturn(new AllotMintHealthStatus(false, null, "https://api.example.com"));

    McpSchema.CallToolResult result = invoke(client);

    assertThat(result.structuredContent())
        .isEqualTo(Map.of("reachable", false, "baseUrl", "https://api.example.com"));
    assertThat(textOf(result))
        .isEqualTo("AllotMint backend at https://api.example.com is not reachable");
  }

  @Test
  void exposesToolNameAndSchema() {
    AllotMintClient client = mock(AllotMintClient.class);
    var specification = AllotMintHealthTool.specification(client);

    assertThat(specification.tool().name()).isEqualTo("allotmint_health");
    assertThat(specification.tool().description()).isNotBlank();
  }

  private static String textOf(McpSchema.CallToolResult result) {
    return ((McpSchema.TextContent) result.content().get(0)).text();
  }
}
