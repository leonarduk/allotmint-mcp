package com.allotmint.mcp.config;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.client.ResearchAgentClient;
import com.allotmint.mcp.tool.AllotMintFilesTool;
import com.allotmint.mcp.tool.AllotMintHealthTool;
import com.allotmint.mcp.tool.AllotMintInstrumentTool;
import com.allotmint.mcp.tool.AllotMintMarketTool;
import com.allotmint.mcp.tool.AllotMintPortfolioTool;
import com.allotmint.mcp.tool.AllotMintResearchTool;
import com.allotmint.mcp.tool.EchoTool;
import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.WebMvcStreamableServerTransportProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.ServerResponse;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * HTTP transport for the MCP server. Off by default: {@code java -jar app.jar} (how Claude Desktop
 * and the MCP Inspector launch this process) is stdio-only, since an embedded servlet container can
 * collide with port hints an MCP client sets via environment variables for its own use (Spring
 * Boot's relaxed env binding maps {@code SERVER_PORT} straight to {@code server.port}). Enable
 * explicitly with {@code --spring.profiles.active=http}.
 */
@Configuration
@Profile("http")
@EnableWebMvc
public class McpServerConfig {

  @Bean
  WebMvcStreamableServerTransportProvider transportProvider(McpJsonMapper jsonMapper) {
    return WebMvcStreamableServerTransportProvider.builder()
        .jsonMapper(jsonMapper)
        .mcpEndpoint("/mcp")
        .build();
  }

  @Bean
  RouterFunction<ServerResponse> mcpRouterFunction(
      WebMvcStreamableServerTransportProvider transportProvider) {
    return transportProvider.getRouterFunction();
  }

  @Bean
  McpSyncServer httpMcpSyncServer(
      WebMvcStreamableServerTransportProvider transportProvider,
      AllotMintClient allotMintClient,
      ResearchAgentClient researchAgentClient,
      @Value("${allotmint.mcp.files.enabled:false}") boolean filesEnabled,
      @Value("${allotmint.mcp.files.root:}") String filesRoot,
      @Value("${allotmint.mcp.research.enabled:false}") boolean researchEnabled) {
    List<McpServerFeatures.SyncToolSpecification> tools = new ArrayList<>();
    tools.add(EchoTool.specification());
    tools.add(AllotMintHealthTool.specification(allotMintClient));
    tools.add(AllotMintInstrumentTool.specification(allotMintClient));
    tools.add(AllotMintMarketTool.specification(allotMintClient));
    tools.add(AllotMintPortfolioTool.specification(allotMintClient));

    if (filesEnabled) {
      tools.add(AllotMintFilesTool.specification(Path.of(filesRoot)));
    }
    if (researchEnabled) {
      tools.add(AllotMintResearchTool.specification(researchAgentClient));
    }

    return McpServer.sync(transportProvider)
        .serverInfo("allotmint-mcp", "0.0.1")
        .tools(tools.toArray(McpServerFeatures.SyncToolSpecification[]::new))
        .build();
  }
}
