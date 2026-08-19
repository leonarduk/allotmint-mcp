package com.allotmint.mcp.tool;

import com.allotmint.mcp.client.AllotMintClient;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AllotMintOwnersToolTest {

  @Test
  void exposesOwnersAsStructuredContent() {
    AllotMintClient client = mock(AllotMintClient.class);
    List<Map<String, Object>> owners = List.of(Map.of("slug", "alice"), Map.of("slug", "bob"));
    when(client.owners()).thenReturn(owners);

    var specification = AllotMintOwnersTool.specification(client);
    McpSchema.CallToolResult result =
        specification
            .callHandler()
            .apply(null, new McpSchema.CallToolRequest("allotmint_owners", Map.of()));

    assertThat(specification.tool().name()).isEqualTo("allotmint_owners");
    assertThat(result.structuredContent()).isEqualTo(Map.of("owners", owners));
  }
}
