package com.allotmint.mcp.config;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.client.ResearchAgentClient;
import com.allotmint.mcp.tool.AllotMintApplyReconciliationTool;
import com.allotmint.mcp.tool.AllotMintDataQualityTool;
import com.allotmint.mcp.tool.AllotMintFilesTool;
import com.allotmint.mcp.tool.AllotMintHealthTool;
import com.allotmint.mcp.tool.AllotMintInstrumentTool;
import com.allotmint.mcp.tool.AllotMintMarketTool;
import com.allotmint.mcp.tool.AllotMintOwnersTool;
import com.allotmint.mcp.tool.AllotMintPortfolioTool;
import com.allotmint.mcp.tool.AllotMintReconcileTool;
import com.allotmint.mcp.tool.AllotMintResearchTool;
import com.allotmint.mcp.tool.EchoTool;
import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.StdioServerTransportProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Registers a second {@link McpSyncServer} on stdio (stdin/stdout), alongside the HTTP transport
 * wired in {@link McpServerConfig}, so Claude Desktop can connect directly to this process's own
 * stdin/stdout as well as over HTTP. Disable with {@code mcp.stdio.enabled=false} (e.g. in tests,
 * to avoid attaching to System.in).
 */
@Configuration
@ConditionalOnProperty(name = "mcp.stdio.enabled", havingValue = "true", matchIfMissing = true)
public class StdioMcpServerConfig {

  @Bean
  McpSyncServer stdioMcpSyncServer(
      McpJsonMapper jsonMapper,
      AllotMintClient allotMintClient,
      ResearchAgentClient researchAgentClient,
      @Value("${allotmint.mcp.files.enabled:false}") boolean filesEnabled,
      @Value("${allotmint.mcp.files.root:}") String filesRoot,
      @Value("${allotmint.mcp.research.enabled:false}") boolean researchEnabled,
      @Value("${allotmint.mcp.data-quality.enabled:true}") boolean dataQualityEnabled,
      @Value("${allotmint.mcp.write.enabled:false}") boolean writeEnabled) {
    StdioServerTransportProvider transportProvider = new StdioServerTransportProvider(jsonMapper);

    List<McpServerFeatures.SyncToolSpecification> tools =
        selectTools(
            allotMintClient,
            researchAgentClient,
            filesEnabled,
            filesRoot,
            researchEnabled,
            dataQualityEnabled,
            writeEnabled);

    return McpServer.sync(transportProvider)
        .serverInfo("allotmint-mcp", "0.0.1")
        .tools(tools.toArray(McpServerFeatures.SyncToolSpecification[]::new))
        .build();
  }

  /**
   * Picks which tool specifications to register, based on the feature flags. Split out from {@link
   * #stdioMcpSyncServer} so this branching logic can be unit-tested directly - actually invoking
   * the {@code @Bean} method attaches a real {@link StdioServerTransportProvider} to stdin (see the
   * class javadoc), which this method never touches.
   */
  static List<McpServerFeatures.SyncToolSpecification> selectTools(
      AllotMintClient allotMintClient,
      ResearchAgentClient researchAgentClient,
      boolean filesEnabled,
      String filesRoot,
      boolean researchEnabled,
      boolean dataQualityEnabled,
      boolean writeEnabled) {
    List<McpServerFeatures.SyncToolSpecification> tools = new ArrayList<>();
    tools.add(EchoTool.specification());
    tools.add(AllotMintHealthTool.specification(allotMintClient));
    tools.add(AllotMintInstrumentTool.specification(allotMintClient));
    tools.add(AllotMintMarketTool.specification(allotMintClient));
    tools.add(AllotMintOwnersTool.specification(allotMintClient));
    tools.add(AllotMintPortfolioTool.specification(allotMintClient));
    tools.add(AllotMintReconcileTool.specification(allotMintClient));

    if (dataQualityEnabled) {
      tools.add(AllotMintDataQualityTool.specification(allotMintClient, writeEnabled));
    }

    if (writeEnabled) {
      tools.add(AllotMintApplyReconciliationTool.specification(allotMintClient));
    }

    if (filesEnabled) {
      tools.add(AllotMintFilesTool.specification(Path.of(filesRoot)));
    }
    if (researchEnabled) {
      tools.add(AllotMintResearchTool.specification(researchAgentClient));
    }

    return tools;
  }
}
