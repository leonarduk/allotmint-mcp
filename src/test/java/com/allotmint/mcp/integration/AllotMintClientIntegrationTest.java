package com.allotmint.mcp.integration;

import com.allotmint.mcp.client.AllotMintClient;
import com.allotmint.mcp.client.AllotMintClientTest;
import com.allotmint.mcp.config.AllotMintClientConfig;
import com.allotmint.mcp.config.AllotMintClientConfigTest;
import com.allotmint.mcp.error.AllotMintApiException;
import com.allotmint.mcp.pojo.AllotMintHealthStatus;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Exercises {@link AllotMintClient} against a real, AWS-deployed AllotMint backend - as opposed to
 * {@link AllotMintClientTest} and {@link AllotMintClientConfigTest}, which stub the HTTP layer with
 * {@code MockRestServiceServer} and so cannot catch request/response contract drift, auth failures,
 * or network-level issues that only show up against the live service (see issue #150).
 *
 * <p>Every test here calls {@link Assumptions#assumeTrue} first and skips cleanly - rather than
 * failing - unless {@code ALLOTMINT_MCP_AUTH_TOKEN} and {@code ALLOTMINT_API_BASE} are both
 * resolvable, either as environment variables or as JVM system properties of the same name (see
 * {@link #resolve(String)}). The token is backend-issued and short-lived (~15 minutes; see the "AWS
 * backend" section of {@code README.md} for how to obtain one), so it is never hard-coded or logged
 * here - only read at test time.
 *
 * <p>Tagged {@code integration} so the {@code maven-surefire-plugin} configuration in {@code
 * pom.xml} excludes it from the default {@code mvn test} / {@code mvn verify} run. To run it
 * explicitly against a live backend, either as environment variables:
 *
 * <pre>{@code
 * ALLOTMINT_API_BASE=https://your-allotmint-backend.example.com ALLOTMINT_MCP_AUTH_TOKEN=<backend-issued-jwt> mvn test -Pintegration
 * }</pre>
 *
 * <p>or as {@code -D} system properties on the Maven command line (Surefire forwards these into the
 * forked test JVM, so both forms work identically):
 *
 * <pre>{@code
 * mvn test -Pintegration -DALLOTMINT_API_BASE=https://your-allotmint-backend.example.com -DALLOTMINT_MCP_AUTH_TOKEN=<backend-issued-jwt>
 * }</pre>
 */
@Tag("integration")
class AllotMintClientIntegrationTest {

  private static final String AUTH_TOKEN = resolve("ALLOTMINT_MCP_AUTH_TOKEN");
  private static final String API_BASE = resolve("ALLOTMINT_API_BASE");

  // Only used by the invalid-token test below, which never needs to resolve to a real owner:
  // auth is expected to be rejected before an owner lookup would even happen. Overridable in case
  // a future backend validates the owner slug before the token.
  private static final String TEST_OWNER =
      resolveOrDefault("ALLOTMINT_TEST_OWNER", "integration-test-owner");

  @Test
  void healthCheckSucceedsAgainstLiveBackendWithValidToken() {
    assumeLiveBackendConfigured();

    AllotMintClient client = newClient(AUTH_TOKEN);

    AllotMintHealthStatus status = client.health();

    assertThat(status.reachable()).isTrue();
    assertThat(status.baseUrl()).isEqualTo(API_BASE);
    assertThat(status.version()).isNotBlank();
  }

  @Test
  void portfolioCallFailsWithDocumentedAuthErrorWhenTokenIsInvalid() {
    assumeLiveBackendConfigured();

    // Tampering with a real (well-formed) token invalidates its signature without needing a
    // separately-managed "known bad" token fixture.
    AllotMintClient client = newClient(AUTH_TOKEN + "-tampered-to-invalidate");

    assertThatThrownBy(() -> client.portfolio(TEST_OWNER))
        .isInstanceOf(AllotMintApiException.class)
        .hasMessage(AllotMintClient.AUTH_ERROR_MESSAGE);
  }

  private static void assumeLiveBackendConfigured() {
    Assumptions.assumeTrue(
        hasText(AUTH_TOKEN),
        "ALLOTMINT_MCP_AUTH_TOKEN not set; skipping live AllotMint backend integration test");
    Assumptions.assumeTrue(
        hasText(API_BASE),
        "ALLOTMINT_API_BASE not set; skipping live AllotMint backend integration test");
  }

  private static AllotMintClient newClient(String token) {
    RestClient.Builder builder = RestClient.builder().baseUrl(API_BASE);
    RestClient restClient = AllotMintClientConfig.withAuthorization(builder, token).build();
    return new AllotMintClient(restClient, API_BASE);
  }

  private static boolean hasText(String value) {
    return value != null && !value.isBlank();
  }

  /**
   * Resolves {@code name} from the environment first, falling back to the JVM system property of
   * the same name. Supports both {@code NAME=value mvn ...} and {@code mvn ... -DNAME=value}
   * invocation styles, since Maven Surefire forwards command-line {@code -D} user properties into
   * the forked test JVM as system properties rather than environment variables.
   */
  private static String resolve(String name) {
    String envValue = System.getenv(name);
    return hasText(envValue) ? envValue : System.getProperty(name);
  }

  private static String resolveOrDefault(String name, String defaultValue) {
    String value = resolve(name);
    return hasText(value) ? value : defaultValue;
  }
}
