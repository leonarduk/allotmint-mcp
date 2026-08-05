package com.allotmint.mcp;

import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.StdioServerTransportProvider;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers a second {@link McpSyncServer} on stdio (stdin/stdout), alongside the HTTP transport
 * wired in {@link McpServerConfig}, so Claude Desktop can connect directly to this process's own
 * stdin/stdout as well as over HTTP. Disable with {@code mcp.stdio.enabled=false} (e.g. in tests,
 * to avoid attaching to System.in).
 */
@Configuration
@ConditionalOnProperty(name = "mcp.stdio.enabled", havingValue = "true", matchIfMissing = true)
class StdioMcpServerConfig {

  @Bean
  McpSyncServer stdioMcpSyncServer(
      McpJsonMapper jsonMapper,
      AllotMintClient allotMintClient,
      @Value("${allotmint.mcp.files.enabled:false}") boolean filesEnabled,
      @Value("${allotmint.mcp.files.root:}") String filesRoot) {
    StdioServerTransportProvider transportProvider = new StdioServerTransportProvider(jsonMapper);

    List<McpServerFeatures.SyncToolSpecification> tools = new ArrayList<>();
    tools.add(EchoTool.specification());
    tools.add(AllotMintHealthTool.specification(allotMintClient));
    tools.add(AllotMintInstrumentTool.specification(allotMintClient));
    tools.add(AllotMintMarketTool.specification(allotMintClient));
    tools.add(AllotMintPortfolioTool.specification(allotMintClient));

    if (filesEnabled) {
      tools.add(AllotMintFilesTool.specification(Path.of(filesRoot)));
    }

    return McpServer.sync(transportProvider)
        .serverInfo("allotmint-mcp", "0.0.1")
        .tools(tools.toArray(McpServerFeatures.SyncToolSpecification[]::new))
        .build();
  }
}
