package com.allotmint.mcp;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * Wires the {@link WebClient} used by {@link AllotMintClient} to talk to the AllotMint
 * backend. Base URL comes from {@code allotmint.api.base-url}, which in turn defaults to
 * the {@code ALLOTMINT_API_BASE} env var (see {@code application.properties}).
 */
@Configuration
class AllotMintClientConfig {

    @Bean
    WebClient allotMintWebClient(@Value("${allotmint.api.base-url:http://localhost:8000}") String baseUrl) {
        return WebClient.builder()
                .baseUrl(baseUrl)
                .build();
    }
}
