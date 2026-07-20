package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class EchoToolTest {

  @Test
  void toolMetadataDescribesTheEchoTool() {
    McpSchema.Tool tool = EchoTool.specification().tool();

    assertThat(tool.name()).isEqualTo("echo");
    assertThat(tool.description()).isEqualTo("Echoes back the provided message");
    assertThat(tool.inputSchema()).containsEntry("required", List.of(EchoTool.MESSAGE));
  }

  @Test
  void callHandlerEchoesBackTheProvidedMessage() {
    McpServerFeatures.SyncToolSpecification spec = EchoTool.specification();
    McpSchema.CallToolRequest request =
        new McpSchema.CallToolRequest("echo", Map.of(EchoTool.MESSAGE, "hello"));

    McpSchema.CallToolResult result = spec.callHandler().apply(null, request);

    assertThat(result.content())
        .singleElement()
        .isInstanceOfSatisfying(
            McpSchema.TextContent.class,
            text -> assertThat(text.text()).isEqualTo("You said: hello"));
  }
}
