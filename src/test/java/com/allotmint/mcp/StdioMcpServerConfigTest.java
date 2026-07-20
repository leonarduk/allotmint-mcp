package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

class StdioMcpServerConfigTest {

  private static final String BEAN_NAME = "stdioMcpSyncServer";

  private final ApplicationContextRunner contextRunner =
      new ApplicationContextRunner()
          .withUserConfiguration(StdioMcpServerConfig.class, McpJsonConfig.class);

  /**
   * Asserts on bean *definition* presence via the raw bean factory rather than {@code
   * context.getBean(...)}, since actually instantiating this bean attaches a real reader to
   * System.in (see {@link StdioMcpServerConfig}'s class javadoc).
   */
  @Test
  void registersTheStdioServerBeanDefinitionByDefault() {
    contextRunner.run(
        context -> assertThat(context.getBeanFactory().containsBeanDefinition(BEAN_NAME)).isTrue());
  }

  @Test
  void omitsTheStdioServerBeanDefinitionWhenExplicitlyDisabled() {
    contextRunner
        .withPropertyValues("mcp.stdio.enabled=false")
        .run(
            context ->
                assertThat(context.getBeanFactory().containsBeanDefinition(BEAN_NAME)).isFalse());
  }
}
