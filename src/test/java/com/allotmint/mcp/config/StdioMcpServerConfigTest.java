package com.allotmint.mcp.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.allotmint.mcp.AllotMintClient;
import com.allotmint.mcp.ResearchAgentClient;
import org.junit.jupiter.api.Test;
import org.springframework.boot.LazyInitializationBeanFactoryPostProcessor;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

class StdioMcpServerConfigTest {

  private static final String BEAN_NAME = "stdioMcpSyncServer";

  private final ApplicationContextRunner contextRunner =
      new ApplicationContextRunner()
          .withUserConfiguration(StdioMcpServerConfig.class, McpJsonConfig.class)
          .withBean(AllotMintClient.class, () -> mock(AllotMintClient.class))
          .withBean(ResearchAgentClient.class, StdioMcpServerConfigTest::researchAgentClient);

  private static ResearchAgentClient researchAgentClient() {
    ResearchAgentClient client = mock(ResearchAgentClient.class);
    when(client.baseUrl()).thenReturn("http://localhost:8100");
    return client;
  }

  /**
   * Asserts on bean *definition* presence rather than instantiating it, since actually
   * instantiating this bean attaches a real reader to System.in (see {@link StdioMcpServerConfig}'s
   * class javadoc). {@code ApplicationContextRunner.run()} eagerly pre-instantiates every non-lazy
   * singleton during refresh regardless of what the assertion itself touches, so the postprocessor
   * below is required to actually defer construction - without it, this test attaches a live stdin
   * reader in every run, which on CI (where stdin is already at EOF) intermittently made the JVM
   * exit mid-suite and zeroed out JaCoco's coverage data for the whole build.
   */
  @Test
  void registersTheStdioServerBeanDefinitionByDefault() {
    contextRunner
        .withInitializer(
            context ->
                context.addBeanFactoryPostProcessor(
                    new LazyInitializationBeanFactoryPostProcessor()))
        .run(
            context ->
                assertThat(context.getBeanFactory().containsBeanDefinition(BEAN_NAME)).isTrue());
  }

  @Test
  void omitsTheStdioServerBeanDefinitionWhenExplicitlyDisabled() {
    contextRunner
        .withPropertyValues("mcp.stdio.enabled=false")
        .run(
            context ->
                assertThat(context.getBeanFactory().containsBeanDefinition(BEAN_NAME)).isFalse());
  }

  @Test
  void startsSuccessfullyWithFilesFeatureDisabledByDefault() {
    contextRunner
        .withInitializer(
            context ->
                context.addBeanFactoryPostProcessor(
                    new LazyInitializationBeanFactoryPostProcessor()))
        .run(
            context ->
                assertThat(context.getBeanFactory().containsBeanDefinition(BEAN_NAME)).isTrue());
  }

  @Test
  void registersTheResearchToolWhenEnabled() {
    contextRunner
        .withPropertyValues("allotmint.mcp.research.enabled=true")
        .withInitializer(
            context ->
                context.addBeanFactoryPostProcessor(
                    new LazyInitializationBeanFactoryPostProcessor()))
        .run(
            context ->
                assertThat(context.getBeanFactory().containsBeanDefinition(BEAN_NAME)).isTrue());
  }

  @Test
  void failsToStartWhenResearchEnabledButSidecarUrlIsEmpty() {
    ResearchAgentClient unconfigured = mock(ResearchAgentClient.class);
    when(unconfigured.baseUrl()).thenReturn("");

    new ApplicationContextRunner()
        .withUserConfiguration(StdioMcpServerConfig.class, McpJsonConfig.class)
        .withBean(AllotMintClient.class, () -> mock(AllotMintClient.class))
        .withBean(ResearchAgentClient.class, () -> unconfigured)
        .withPropertyValues("allotmint.mcp.research.enabled=true")
        .run(context -> assertThat(context).hasFailed());
  }

  @Test
  void failsToStartWhenFilesEnabledButRootIsEmpty() {
    contextRunner
        .withPropertyValues("allotmint.mcp.files.enabled=true", "allotmint.mcp.files.root=")
        .run(context -> assertThat(context).hasFailed());
  }
}
