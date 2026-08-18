package com.allotmint.mcp.integration;

import com.allotmint.mcp.client.AllotMintClient;
import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.ServerParameters;
import io.modelcontextprotocol.client.transport.StdioClientTransport;
import io.modelcontextprotocol.json.McpJsonDefaults;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Packaging smoke test: launches the actual fat JAR produced by the {@code
 * spring-boot-maven-plugin} repackage goal as a real OS subprocess and drives it over stdio with
 * the MCP Java SDK's own client - the same {@code initialize} / {@code tools/list} handshake a real
 * client (Claude Desktop, MCP Inspector) uses, exercised in {@link McpHttpTransportIntegrationTest}
 * for the HTTP transport.
 *
 * <p>This class is named {@code *IT} (not {@code *Test}) so the {@code maven-failsafe-plugin} runs
 * it during the {@code integration-test} phase, which comes after {@code package}. The fat JAR this
 * test depends on does not exist yet during the earlier {@code test} phase where Surefire runs unit
 * tests, so this cannot be a plain Surefire test without an extra build step to produce the JAR
 * first.
 *
 * <p>No network calls are made: the process only needs to complete MCP's {@code initialize} and
 * {@code tools/list} exchange, so {@link AllotMintClient} is never invoked and no AllotMint backend
 * is required. The default {@code allotmint.api.base-url} (localhost:8000) is never contacted.
 */
class FatJarSmokeIT {

  /** README-documented startup budget: the server must be ready for MCP traffic within this. */
  private static final Duration STARTUP_BUDGET = Duration.ofSeconds(5);

  private McpSyncClient client;

  @AfterEach
  void disconnect() {
    if (client != null) {
      client.closeGracefully();
    }
  }

  @Test
  @Timeout(10)
  void fatJarStartsWithinBudgetAndRegistersAllotMintTools() {
    startServer(false);

    McpSchema.ListToolsResult tools = client.listTools();
    assertThat(tools.tools())
        .extracting(McpSchema.Tool::name)
        .contains(
            "allotmint_health",
            "allotmint_instrument",
            "allotmint_market",
            "allotmint_portfolio",
            "allotmint_reconcile",
            "allotmint_data_quality")
        // allotmint_apply_reconciliation is registered only when ALLOTMINT_MCP_WRITE_ENABLED is
        // explicitly set; allotmint_data_quality is registered by default but its write actions
        // (fix/dedupe/undo) are likewise gated on write being enabled. This smoke test never sets
        // the flag, so the apply tool must stay absent.
        .doesNotContain("allotmint_apply_reconciliation");
  }

  @Test
  @Timeout(10)
  void writeEnabledFatJarRegistersApplyToolWithRequiredSchema() {
    startServer(true);

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

  private void startServer(boolean writeEnabled) {
    Path jar = fatJarPath();
    assertThat(Files.isRegularFile(jar))
        .withFailMessage(
            "Fat jar not found at %s - expected `mvn package` to have built it before this"
                + " integration test ran",
            jar.toAbsolutePath())
        .isTrue();

    ServerParameters params =
        ServerParameters.builder("java")
            .args("-jar", jar.toAbsolutePath().toString())
            .addEnvVar("ALLOTMINT_MCP_WRITE_ENABLED", Boolean.toString(writeEnabled))
            .build();
    StdioClientTransport transport = new StdioClientTransport(params, McpJsonDefaults.getMapper());

    client =
        McpClient.sync(transport)
            .requestTimeout(STARTUP_BUDGET)
            .initializationTimeout(STARTUP_BUDGET)
            .build();

    // Performs the MCP initialize handshake; throws if the server isn't ready within the
    // configured initializationTimeout, which enforces the 5-second startup budget.
    client.initialize();
  }

  private Path fatJarPath() {
    String configured = System.getProperty("allotmint.mcp.smokeTest.fatJar");
    return configured != null && !configured.isBlank()
        ? Path.of(configured)
        : Path.of("target", "allotmint-mcp-server.jar");
  }
}
