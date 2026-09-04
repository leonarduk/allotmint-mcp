package com.allotmint.mcp.config;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.client.ResearchAgentClient;
import io.modelcontextprotocol.server.McpServerFeatures;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.LazyInitializationBeanFactoryPostProcessor;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

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

  @Test
  void selectsOnlyTheAlwaysOnToolsWhenEveryOptionalFeatureIsDisabled() {
    List<McpServerFeatures.SyncToolSpecification> tools =
        StdioMcpServerConfig.selectTools(
            mock(AllotMintClient.class), researchAgentClient(), false, "", false, false, false);

    assertThat(tools)
        .extracting(t -> t.tool().name())
        .containsExactly(
            "echo",
            "allotmint_health",
            "allotmint_instrument",
            "allotmint_market",
            "allotmint_owners",
            "allotmint_portfolio",
            "allotmint_reconcile");
  }

  @Test
  void addsTheDataQualityToolWhenDataQualityIsEnabled() {
    List<McpServerFeatures.SyncToolSpecification> tools =
        StdioMcpServerConfig.selectTools(
            mock(AllotMintClient.class), researchAgentClient(), false, "", false, true, false);

    assertThat(tools).extracting(t -> t.tool().name()).contains("allotmint_data_quality");
  }

  @Test
  void addsTheApplyReconciliationToolOnlyWhenWriteIsEnabled() {
    List<McpServerFeatures.SyncToolSpecification> tools =
        StdioMcpServerConfig.selectTools(
            mock(AllotMintClient.class), researchAgentClient(), false, "", false, false, true);

    assertThat(tools).extracting(t -> t.tool().name()).contains("allotmint_apply_reconciliation");
  }

  @Test
  void addsTheFilesToolWhenFilesAreEnabledWithAValidRoot(@TempDir Path filesRoot) {
    List<McpServerFeatures.SyncToolSpecification> tools =
        StdioMcpServerConfig.selectTools(
            mock(AllotMintClient.class),
            researchAgentClient(),
            true,
            filesRoot.toString(),
            false,
            false,
            false);

    assertThat(tools).extracting(t -> t.tool().name()).contains("allotmint_files");
  }

  @Test
  void addsTheResearchToolWhenResearchIsEnabled() {
    List<McpServerFeatures.SyncToolSpecification> tools =
        StdioMcpServerConfig.selectTools(
            mock(AllotMintClient.class), researchAgentClient(), false, "", true, false, false);

    assertThat(tools).extracting(t -> t.tool().name()).contains("allotmint_research");
  }
}
