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
    Files.writeString(directory.resolve(".env"), "DOTENV_INTEGRATION_VALUE=from-dotenv\n");

    try (ConfigurableApplicationContext context =
        new SpringApplicationBuilder(TestApplication.class)
            .properties(
                "spring.main.banner-mode=off",
                "spring.main.web-application-type=none",
                "springdotenv.directory=" + directory,
                "springdotenv.ignore-if-missing=false")
            .run()) {
      assertThat(context.getEnvironment().getProperty("DOTENV_INTEGRATION_VALUE"))
          .isEqualTo("from-dotenv");
    }
  }

  @SpringBootConfiguration
  static class TestApplication {}
}
