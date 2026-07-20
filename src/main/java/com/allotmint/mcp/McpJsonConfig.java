package com.allotmint.mcp;

import io.modelcontextprotocol.json.McpJsonDefaults;
import io.modelcontextprotocol.json.McpJsonMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Shared {@link McpJsonMapper} bean used by both the stdio and (optional) HTTP MCP transports.
 * Neither {@code mcp-core} nor {@code mcp-spring-webmvc} auto-configures this bean, so it must be
 * provided explicitly.
 */
@Configuration
class McpJsonConfig {

  @Bean
  McpJsonMapper mcpJsonMapper() {
    return McpJsonDefaults.getMapper();
  }
}
