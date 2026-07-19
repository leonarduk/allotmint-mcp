package com.allotmint.mcp;

import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.StdioServerTransportProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers a second {@link McpSyncServer} on stdio (stdin/stdout), alongside the HTTP
 * transport wired in {@link McpServerConfig}, so Claude Desktop can connect directly to
 * this process's own stdin/stdout as well as over HTTP. Disable with
 * {@code mcp.stdio.enabled=false} (e.g. in tests, to avoid attaching to System.in).
 */
@Configuration
@ConditionalOnProperty(name = "mcp.stdio.enabled", havingValue = "true", matchIfMissing = true)
class StdioMcpServerConfig {

    @Bean
    McpSyncServer stdioMcpSyncServer(McpJsonMapper jsonMapper) {
        StdioServerTransportProvider transportProvider = new StdioServerTransportProvider(jsonMapper);
        return McpServer.sync(transportProvider)
                .serverInfo("allotmint-mcp", "0.0.1")
                .tools(EchoTool.specification())
                .build();
    }
}
