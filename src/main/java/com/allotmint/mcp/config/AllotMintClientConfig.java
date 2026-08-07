package com.allotmint.mcp.config;

import com.allotmint.mcp.client.AllotMintClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;

import java.time.Duration;

/**
 * Wires the {@link RestClient} used by {@link AllotMintClient} to talk to the AllotMint backend.
 * Base URL comes from {@code allotmint.api.base-url}, which in turn defaults to the {@code
 * ALLOTMINT_API_BASE} env var (see {@code application.properties}).
 *
 * <p>{@link RestClient} (synchronous, from {@code spring-web}) rather than {@code WebClient}
 * (reactive, from {@code spring-boot-starter-webflux}): {@link AllotMintClient} only ever needs a
 * single blocking call per tool invocation, and pulling in the reactive stack costs a reactor-netty
 * dependency that failed the {@code dependency-check} CI gate on unrelated CVEs.
 */
@Configuration
public class AllotMintClientConfig {

  @Bean
  RestClient allotMintRestClient(
      @Value("${allotmint.api.base-url:http://localhost:8000}") String baseUrl,
      @Value("${allotmint.mcp.auth-token:}") String authToken,
      @Value("${allotmint.api.connect-timeout-seconds:5}") int connectTimeoutSeconds,
      @Value("${allotmint.api.read-timeout-seconds:15}") int readTimeoutSeconds) {
    SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
    requestFactory.setConnectTimeout(Duration.ofSeconds(connectTimeoutSeconds));
    requestFactory.setReadTimeout(Duration.ofSeconds(readTimeoutSeconds));
    return withAuthorization(
            RestClient.builder().baseUrl(baseUrl).requestFactory(requestFactory), authToken)
        .build();
  }

  /**
   * Attaches the configured backend-issued JWT as a default {@code Authorization} header, so every
   * request the resulting {@link RestClient} makes carries it - callers such as {@link
   * AllotMintClient} don't need to remember to add it themselves. Left blank (the default), no
   * header is added and requests go out unauthenticated, as against a local {@code
   * DISABLE_AUTH=true} backend.
   *
   * <p>Package-visible rather than private purely so tests can verify the header wiring against a
   * {@code MockRestServiceServer}-bound builder without needing a full Spring context.
   */
  public static RestClient.Builder withAuthorization(RestClient.Builder builder, String authToken) {
    if (StringUtils.hasText(authToken)) {
      builder.defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + authToken.trim());
    }
    return builder;
  }
}
