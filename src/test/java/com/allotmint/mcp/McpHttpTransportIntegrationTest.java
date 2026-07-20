package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.spec.McpClientTransport;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;

/**
 * Boots the full application over a real HTTP port and drives it with the MCP SDK's own
 * streamable-HTTP client, exercising the same wire protocol a real MCP client would use.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("http")
@TestPropertySource(properties = "mcp.stdio.enabled=false")
class McpHttpTransportIntegrationTest {

    @LocalServerPort
    private int port;

    private McpSyncClient client;

    @BeforeEach
    void connect() {
        McpClientTransport transport = HttpClientStreamableHttpTransport.builder("http://localhost:" + port)
                .endpoint("/mcp")
                .build();
        client = McpClient.sync(transport).build();
        client.initialize();
    }

    @AfterEach
    void disconnect() {
        client.closeGracefully();
    }

    @Test
    void echoToolIsRegisteredAndRespondsOverHttp() {
        McpSchema.ListToolsResult tools = client.listTools();
        assertThat(tools.tools()).extracting(McpSchema.Tool::name).containsExactly("echo");

        McpSchema.CallToolResult result = client.callTool(
                new McpSchema.CallToolRequest("echo", Map.of(EchoTool.MESSAGE, "integration-test")));

        assertThat(result.content())
                .singleElement()
                .isInstanceOfSatisfying(
                        McpSchema.TextContent.class,
                        text -> assertThat(text.text()).isEqualTo("You said: integration-test"));
    }
}
