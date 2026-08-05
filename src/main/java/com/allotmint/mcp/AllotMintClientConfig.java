package com.allotmint.mcp;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

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
class AllotMintClientConfig {

  @Bean
  RestClient allotMintRestClient(
      @Value("${allotmint.api.base-url:http://localhost:8000}") String baseUrl) {
    return RestClient.builder().baseUrl(baseUrl).build();
  }
}
