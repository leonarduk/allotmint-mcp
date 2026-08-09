package com.allotmint.mcp.config;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class DotenvIntegrationTest {

  @Test
  void loadsDotenvValuesIntoSpringEnvironment(@TempDir Path directory) throws IOException {
    Files.writeString(
        directory.resolve(".env"),
        "ALLOTMINT_API_BASE=https://dotenv.example.test\n"
            + "ALLOTMINT_MCP_RESEARCH_ENABLED=true\n");

    try (ConfigurableApplicationContext context = application(directory).run()) {
      assertThat(context.getEnvironment().getProperty("allotmint.api.base-url"))
          .isEqualTo("https://dotenv.example.test");
      assertThat(context.getEnvironment().getProperty("allotmint.mcp.research.enabled"))
          .isEqualTo("true");
    }
  }

  @Test
  void systemPropertiesOverrideDotenvValues(@TempDir Path directory) throws IOException {
    Files.writeString(
        directory.resolve(".env"), "ALLOTMINT_API_BASE=https://dotenv.example.test\n");

    String propertyName = "ALLOTMINT_API_BASE";
    String previousValue = System.getProperty(propertyName);
    System.setProperty(propertyName, "https://deployment.example.test");
    try {
      try (ConfigurableApplicationContext context = application(directory).run()) {
        assertThat(context.getEnvironment().getProperty("allotmint.api.base-url"))
            .isEqualTo("https://deployment.example.test");
      }
    } finally {
      if (previousValue == null) {
        System.clearProperty(propertyName);
      } else {
        System.setProperty(propertyName, previousValue);
      }
    }
  }

  private SpringApplicationBuilder application(Path directory) {
    return new SpringApplicationBuilder(TestApplication.class)
        .properties(
            "spring.main.banner-mode=off",
            "spring.main.web-application-type=none",
            "springdotenv.directory=" + directory,
            "springdotenv.ignore-if-missing=false");
  }

  @SpringBootConfiguration
  static class TestApplication {}
}
