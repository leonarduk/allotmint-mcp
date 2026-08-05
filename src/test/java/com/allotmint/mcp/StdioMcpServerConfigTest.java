package com.allotmint.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import org.junit.jupiter.api.Test;
import org.springframework.boot.LazyInitializationBeanFactoryPostProcessor;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

class StdioMcpServerConfigTest {

  private static final String BEAN_NAME = "stdioMcpSyncServer";

  private final ApplicationContextRunner contextRunner =
      new ApplicationContextRunner()
          .withUserConfiguration(StdioMcpServerConfig.class, McpJsonConfig.class)
          .withBean(AllotMintClient.class, () -> mock(AllotMintClient.class));

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
  void failsToStartWhenFilesEnabledButRootIsEmpty() {
    contextRunner
        .withPropertyValues("allotmint.mcp.files.enabled=true", "allotmint.mcp.files.root=")
        .run(context -> assertThat(context).hasFailed());
  }
}
