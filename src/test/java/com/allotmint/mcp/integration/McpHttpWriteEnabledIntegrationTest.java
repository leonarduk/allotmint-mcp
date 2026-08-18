package com.allotmint.mcp.integration;

import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.spec.McpClientTransport;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** Verifies the write-enabled environment configuration over the HTTP MCP transport. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("http")
@TestPropertySource(properties = {"mcp.stdio.enabled=false", "allotmint.mcp.write.enabled=true"})
class McpHttpWriteEnabledIntegrationTest {

  @LocalServerPort private int port;

  private McpSyncClient client;

  @BeforeEach
  void connect() {
    McpClientTransport transport =
        HttpClientStreamableHttpTransport.builder("http://localhost:" + port)
            .endpoint("/mcp")
            .build();
    client = McpClient.sync(transport).build();
    try {
      client.initialize();
    } catch (RuntimeException | Error initializationFailure) {
      try {
        client.closeGracefully();
      } catch (RuntimeException cleanupFailure) {
        initializationFailure.addSuppressed(cleanupFailure);
      }
      client = null;
      throw initializationFailure;
    }
  }

  @AfterEach
  void disconnect() {
    if (client != null) {
      client.closeGracefully();
    }
  }

  @Test
  void applyReconciliationToolIsRegisteredWithRequiredSchemaWhenWriteEnabled() {
    McpSchema.ListToolsResult tools = client.listTools();

    assertThat(tools.tools())
        .extracting(McpSchema.Tool::name)
        .contains("allotmint_reconcile", "allotmint_apply_reconciliation");

    McpSchema.Tool applyTool =
        tools.tools().stream()
            .filter(tool -> tool.name().equals("allotmint_apply_reconciliation"))
            .findFirst()
            .orElseThrow();
    assertThat(applyTool.inputSchema()).containsEntry("required", List.of("reconciliation_id"));
  }
}
