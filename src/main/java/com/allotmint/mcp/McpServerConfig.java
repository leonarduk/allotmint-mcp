package com.allotmint.mcp;

import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.WebMvcStreamableServerTransportProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.ServerResponse;

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
class McpServerConfig {

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
  McpSyncServer httpMcpSyncServer(WebMvcStreamableServerTransportProvider transportProvider) {
    return McpServer.sync(transportProvider)
        .serverInfo("allotmint-mcp", "0.0.1")
        .tools(EchoTool.specification())
        .build();
  }
}
