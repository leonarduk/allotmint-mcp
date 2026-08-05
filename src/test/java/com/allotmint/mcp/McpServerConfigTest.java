package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

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
          .withUserConfiguration(McpServerConfig.class, McpJsonConfig.class)
          .withBean(AllotMintClient.class, () -> mock(AllotMintClient.class));

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

  @Test
  void startsSuccessfullyWithFilesFeatureDisabledByDefault() {
    // The default is allotmint.mcp.files.enabled=false — the server must
    // start without the allotmint_files tool and without any config errors.
    contextRunner
        .withPropertyValues("spring.profiles.active=http")
        .run(
            context -> {
              assertThat(context).hasSingleBean(McpSyncServer.class);
              assertThat(context).hasNotFailed();
            });
  }

  @Test
  void failsToStartWhenFilesEnabledButRootIsEmpty() {
    // Enabling the feature without configuring a root is a security risk —
    // Path.of("") would resolve to the CWD, exposing the entire working
    // directory.  The configuration must reject this explicitly.
    contextRunner
        .withPropertyValues(
            "spring.profiles.active=http",
            "allotmint.mcp.files.enabled=true",
            "allotmint.mcp.files.root=")
        .run(context -> assertThat(context).hasFailed());
  }
}
