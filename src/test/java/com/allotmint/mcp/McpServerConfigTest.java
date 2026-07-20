package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.WebMvcStreamableServerTransportProvider;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.web.servlet.function.RouterFunction;

class McpServerConfigTest {

  // @EnableWebMvc needs a real ServletContext (even if mocked), which the plain
  // ApplicationContextRunner doesn't provide.
  private final WebApplicationContextRunner contextRunner =
      new WebApplicationContextRunner()
          .withUserConfiguration(McpServerConfig.class, McpJsonConfig.class);

  @Test
  void isInactiveWithoutTheHttpProfile() {
    contextRunner.run(
        context ->
            assertThat(context.getBeanFactory().containsBeanDefinition("httpMcpSyncServer"))
                .isFalse());
  }

  @Test
  void registersHttpTransportBeansWhenTheHttpProfileIsActive() {
    contextRunner
        .withPropertyValues("spring.profiles.active=http")
        .run(
            context -> {
              assertThat(context).hasSingleBean(WebMvcStreamableServerTransportProvider.class);
              assertThat(context).hasSingleBean(RouterFunction.class);
              assertThat(context).hasSingleBean(McpSyncServer.class);
            });
  }
}
