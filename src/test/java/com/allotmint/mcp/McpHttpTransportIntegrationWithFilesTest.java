package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.spec.McpClientTransport;
import io.modelcontextprotocol.spec.McpSchema;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.TestPropertySource;

/**
 * Verifies the {@code allotmint_files} tool is registered and operational when {@code
 * ALLOTMINT_MCP_FILES_ENABLED=true} and a valid root is set.
 *
 * <p>Contrast with {@link McpHttpTransportIntegrationTest}, which tests the default (disabled)
 * case.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("http")
@TestPropertySource(properties = "mcp.stdio.enabled=false")
class McpHttpTransportIntegrationWithFilesTest {

  @LocalServerPort private int port;

  private McpSyncClient client;

  private static Path filesRoot;

  @BeforeAll
  static void createTempRoot() throws IOException {
    filesRoot = Files.createTempDirectory("allotmint-mcp-test-root-");
    Files.writeString(filesRoot.resolve("greeting.txt"), "Hello from files root!\n");
    Files.createDirectory(filesRoot.resolve("nested"));
    Files.writeString(filesRoot.resolve("nested").resolve("data.txt"), "nested content\n");
  }

  @DynamicPropertySource
  static void configureFiles(DynamicPropertyRegistry registry) {
    registry.add("allotmint.mcp.files.enabled", () -> "true");
    registry.add("allotmint.mcp.files.root", () -> filesRoot.toString());
  }

  @BeforeEach
  void connect() {
    McpClientTransport transport =
        HttpClientStreamableHttpTransport.builder("http://localhost:" + port)
            .endpoint("/mcp")
            .build();
    client = McpClient.sync(transport).build();
    client.initialize();
  }

  @AfterEach
  void disconnect() {
    if (client != null) {
      client.closeGracefully();
    }
  }

  @Test
  void bothEchoAndFilesToolsAreRegistered() {
    McpSchema.ListToolsResult tools = client.listTools();
    assertThat(tools.tools())
        .extracting(McpSchema.Tool::name)
        .containsExactlyInAnyOrder("echo", "allotmint_files");
  }

  @Test
  void readFileReturnsContent() {
    McpSchema.CallToolResult result =
        client.callTool(
            new McpSchema.CallToolRequest(
                "allotmint_files", Map.of("operation", "read", "path", "greeting.txt")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    assertThat(result.content())
        .anyMatch(
            c ->
                c instanceof McpSchema.TextContent tc
                    && tc.text().contains("Hello from files root!"));
  }

  @Test
  void listRootDirectory() {
    McpSchema.CallToolResult result =
        client.callTool(
            new McpSchema.CallToolRequest(
                "allotmint_files", Map.of("operation", "list", "path", "")));

    assertThat(result.isError()).isNotEqualTo(Boolean.TRUE);
    @SuppressWarnings("unchecked")
    Map<String, Object> structured = (Map<String, Object>) result.structuredContent();
    @SuppressWarnings("unchecked")
    java.util.List<Map<String, Object>> entries =
        (java.util.List<Map<String, Object>>) structured.get("entries");
    assertThat(entries).extracting(e -> e.get("name")).contains("greeting.txt", "nested");
  }

  @Test
  void traverseRejectedByServer() {
    // The MCP server throws a protocol-level error for path traversal attempts.
    // The SDK surfaces this as an exception rather than a CallToolResult.
    try {
      client.callTool(
          new McpSchema.CallToolRequest(
              "allotmint_files", Map.of("operation", "read", "path", "../../etc/passwd")));
      // Should not reach here
      throw new AssertionError("Expected traversal rejection but call succeeded");
    } catch (Exception e) {
      assertThat(e.getMessage()).containsAnyOf("traversal", "escapes", "rejected");
    }
  }
}
