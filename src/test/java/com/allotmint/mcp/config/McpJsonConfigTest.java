package com.allotmint.mcp.config;

import io.modelcontextprotocol.json.McpJsonMapper;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class McpJsonConfigTest {

  private final ApplicationContextRunner contextRunner =
      new ApplicationContextRunner().withUserConfiguration(McpJsonConfig.class);

  @Test
  void registersASingleMcpJsonMapperBean() {
    contextRunner.run(context -> assertThat(context).hasSingleBean(McpJsonMapper.class));
  }
}
